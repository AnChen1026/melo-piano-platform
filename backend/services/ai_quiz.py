"""AI 出題：從老師上傳的教材（PDF／TXT）讀出文字，請 LLM 出題，再檢查格式。

出題邏輯（system prompt、讀教材、剔除格式錯誤的題目）沿用宇鈞在 ai-quiz 分支寫的版本，
改成走專案共用的 backend/services/llm.py：預設用 OpenAI（OPENAI_API_KEY），.env 寫 QUIZ_GENERATION_LLM_PROVIDER=gemini
換回 Gemini，寫 local 改用 Ollie 電腦上的千問等本機模型（QUIZ_GENERATION_LLM_MODEL 選模型），並加上多選題、是非題、難易度與作答提示。
掃描的 PDF 頁面用 Tesseract OCR 辨識（同樣來自宇鈞的 ai-quiz 分支），這裡改用 PyMuPDF 內建的 OCR 呼叫。

這裡只負責「出題」：背景工作與進度在 services/quiz_jobs.py，老師審查後題目跟作業一起由 services/assignment.py 存起來。
"""

import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path

from backend.services import llm

logger = logging.getLogger(__name__)

QUESTION_TYPES = ("single", "multiple", "truefalse")
QUESTION_TYPE_LABELS = {"single": "單選題", "multiple": "多選題", "truefalse": "是非題"}
DIFFICULTIES = ("easy", "medium", "hard", "mixed")
DIFFICULTY_LABELS = {"easy": "簡單", "medium": "中等", "hard": "困難", "mixed": "混合"}
TRUE_FALSE_OPTIONS = ["正確", "錯誤"]

MIN_QUESTIONS = 1
MAX_QUESTIONS = 30
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_MATERIAL_CHARS = 30000  # 送進模型的教材長度上限
SOURCE_SUFFIXES = (".pdf", ".txt")
# 掃描的 PDF 沒有文字層，改用 OCR（Tesseract，Dockerfile 有安裝繁中與英文語言包）
OCR_LANGUAGES = "chi_tra+eng"
OCR_DPI = 300
OCR_MIN_PAGE_CHARS = 20  # 一頁讀到的字比這少，就當成掃描頁
MAX_OCR_PAGES = 30  # 一頁約 1～3 秒，避免上傳等太久
# 一次出很多題時模型要想比較久
GENERATION_TIMEOUT_SECONDS = 120.0
# 本機模型（千問等）：閘道每則訊息最多 12000 字、一次最多回 1400 token，所以每批讀一段教材、出幾題
LOCAL_BATCH_SIZE = 4
LOCAL_CHUNK_CHARS = 6000
# 模型忙碌時（本機閘道同時只處理一個請求、雲端 503）等一下再試
BUSY_ATTEMPTS = 4
BUSY_WAIT_SECONDS = 15
BUSY_MARKERS = ("429", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "high demand", "沒有回應", "忙碌")

SYSTEM_PROMPT = """你是一位專業的鋼琴與樂理出題老師，負責根據使用者提供的教材內容出題。

# 出題原則
1. 題目必須完全根據教材內容，不可使用教材以外的知識，也不可捏造教材沒有的資訊。
2. 只出使用者指定的題型：
   - single（單選題）：4 個選項，有且只有 1 個正確答案。
   - multiple（多選題）：4 個選項，有 2～4 個正確答案。
   - truefalse（是非題）：選項固定是 ["正確", "錯誤"]，題目是一句可以判斷對錯的敘述。
3. 題目要涵蓋教材中不同的重要概念，避免重複或過度集中在同一段落。
4. 依照指定的難易度出題：easy 考記憶與理解，medium 考理解與簡單應用，hard 考應用、比較與綜合判斷；mixed 由淺入深混合。
5. 干擾選項要合理、有迷惑性，但不可有爭議或同時正確的情況。
6. 題目與選項使用與教材相同的語言（教材為中文則用繁體中文）。
7. 每題附上：
   - topic：這題考的單元或概念名稱，10 個字以內，例如「五線譜與譜號」。
   - hint：作答提示，引導學生回想教材的哪個概念，不可以直接說出答案或刪去選項。
   - explanation：簡短解析，說明為什麼答案正確，必要時指出教材依據。
8. 若教材內容不足以出到要求的題數，就只出能出的題數，不要硬湊。
9. 每題寫完都要對照教材自我檢查：answers 標的每個選項都必須正確、沒標的都必須錯誤，explanation 要和 answers 一致。
   多選題尤其要逐一檢查每個選項；不確定的題目寧可不出。

# 輸出格式
只輸出一個 JSON 物件，不要有任何其他文字或 Markdown，格式如下：
{
  "questions": [
    {
      "type": "single",
      "difficulty": "easy",
      "topic": "<10 字內的單元名稱>",
      "question": "<題目>",
      "options": ["<選項>", "<選項>", "<選項>", "<選項>"],
      "answers": [0],
      "hint": "<這題自己的作答提示>",
      "explanation": "<這題自己的解析>"
    }
  ]
}
其中 answers 是正確選項在 options 中的索引（從 0 開始）。options 內容不要包含 A/B/C/D 前綴。
difficulty 只能是 easy、medium、hard。"""


class QuizGenerationError(Exception):
    """出題失敗，訊息可以直接給老師看。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ---------- 讀教材


def decode_text_bytes(data: bytes) -> str:
    """TXT 解碼：依序嘗試常見編碼。"""
    for encoding in ("utf-8-sig", "big5", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def extract_pdf_text(data: bytes) -> str:
    """有文字層的頁面直接讀；掃描的頁面（幾乎讀不到字）改用 OCR 辨識。"""
    import pymupdf

    pages = []
    total = 0
    ocr_pages = 0
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for page in pdf:
            if total >= MAX_MATERIAL_CHARS:
                break  # 超過的部分本來就不會送進模型，不用再辨識
            text = page.get_text().strip()
            if len(text) < OCR_MIN_PAGE_CHARS and ocr_pages < MAX_OCR_PAGES:
                ocr_pages += 1
                text = ocr_page(page) or text
            if text:
                pages.append(text)
                total += len(text)
    return "\n\n".join(pages)


def ocr_page(page) -> str:
    """用 Tesseract 辨識整頁。電腦沒裝 Tesseract 或辨識失敗時回傳空字串，讓呼叫端照原本的訊息處理。"""
    try:
        textpage = page.get_textpage_ocr(language=OCR_LANGUAGES, dpi=OCR_DPI, full=True)
        return page.get_text(textpage=textpage).strip()
    except Exception as error:  # 沒裝 Tesseract 時 PyMuPDF 丟 RuntimeError
        logger.warning("PDF 第 %s 頁 OCR 失敗：%s", page.number + 1, error)
        return ""


def extract_text(filename: str, data: bytes) -> str:
    """回傳教材的純文字。檔案不能讀時丟 QuizGenerationError。"""
    if not data:
        raise QuizGenerationError("教材檔案是空的。")
    if len(data) > MAX_SOURCE_BYTES:
        raise QuizGenerationError("教材檔案最大 20 MB。")
    suffix = Path(filename).suffix.lower()
    if suffix not in SOURCE_SUFFIXES:
        raise QuizGenerationError("題庫檔案目前只支援 PDF 與 TXT。")
    try:
        text = decode_text_bytes(data).strip() if suffix == ".txt" else extract_pdf_text(data)
    except Exception as error:
        raise QuizGenerationError(f"讀不出這個檔案的內容：{error}") from error
    if not text.strip():
        raise QuizGenerationError("這個檔案讀不到文字。掃描的 PDF 會自動辨識文字，可能是圖片太模糊；請改上傳較清楚的 PDF 或 TXT。")
    return text


# ---------- 檢查題目


def clean_question(raw: dict, allowed_types: tuple[str, ...] = QUESTION_TYPES) -> dict | None:
    """把一題整理成固定格式；格式不對就回傳 None。老師手動改過、要存的題目也走這裡。"""
    if not isinstance(raw, dict):
        return None
    question_type = str(raw.get("type") or raw.get("question_type") or "single").strip().lower()
    question = raw.get("question")
    options = raw.get("options")
    answers = raw.get("answers")
    if answers is None and isinstance(raw.get("answer"), int):
        answers = [raw["answer"]]  # 宇鈞原本的格式：answer 是一個數字
    if question_type not in allowed_types or not isinstance(question, str) or not question.strip():
        return None
    if question_type == "truefalse":
        options = list(TRUE_FALSE_OPTIONS)
    if not isinstance(options, list) or not isinstance(answers, list):
        return None
    options = [str(item).strip() for item in options]
    if any(not item for item in options) or len(set(options)) != len(options):
        return None
    expected = 2 if question_type == "truefalse" else 4
    if len(options) != expected:
        return None
    if not answers or not all(isinstance(item, int) and not isinstance(item, bool) for item in answers):
        return None
    answers = sorted(set(answers))
    if any(not 0 <= item < len(options) for item in answers):
        return None
    if question_type == "multiple" and len(answers) < 2:
        return None
    if question_type != "multiple" and len(answers) != 1:
        return None
    difficulty = str(raw.get("difficulty") or "").strip().lower()
    return {
        "type": question_type,
        "difficulty": difficulty if difficulty in DIFFICULTIES[:3] else None,
        "topic": _text_or_none(raw.get("topic"), 100),
        "question": question.strip(),
        "options": options,
        "answers": answers,
        "hint": _text_or_none(raw.get("hint")),
        "explanation": _text_or_none(raw.get("explanation")),
    }


# 模型偶爾會把格式範例原封不動抄進來，這些當成沒寫
PLACEHOLDERS = {"提示文字", "解析文字", "單元名稱", "題目文字", "選項內容"}


def _text_or_none(value, limit: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text or text in PLACEHOLDERS or (text.startswith("<") and text.endswith(">")):
        return None
    return text[:limit] if limit else text


def _parse_json(text: str) -> dict:
    """模型有時會包在 ```json ``` 裡，或前後多講幾句話，只取出 JSON 物件。"""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    body = fenced.group(1) if fenced else text
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("回覆裡沒有 JSON")
    return json.loads(body[start : end + 1])


# ---------- 出題


def check_settings(count: int, types: list[str], difficulty: str) -> tuple[int, tuple[str, ...], str]:
    if not MIN_QUESTIONS <= count <= MAX_QUESTIONS:
        raise QuizGenerationError(f"出題數量請填 {MIN_QUESTIONS}～{MAX_QUESTIONS} 題。")
    chosen = tuple(item for item in QUESTION_TYPES if item in types)
    if not chosen or len(chosen) != len(set(types)):
        raise QuizGenerationError("請至少選一種題目類型（單選、多選、是非）。")
    if difficulty not in DIFFICULTIES:
        raise QuizGenerationError("難易度請選簡單、中等、困難或混合。")
    return count, chosen, difficulty


def generate_questions(
    material: str,
    count: int,
    types: list[str],
    difficulty: str,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """請 LLM 出題，回傳檢查過的題目（含答案、提示、解析）。

    雲端模型（Gemini、OpenAI）一次出完。本機模型（千問等）每次能讀、能寫的字數都有限，
    所以分批：每批讀一段教材、出 LOCAL_BATCH_SIZE 題，並告訴模型前面出過哪些題目避免重複。
    on_progress(已出題數, 目標題數) 讓背景工作更新進度。
    """
    count, chosen, difficulty = check_settings(count, types, difficulty)
    local = llm.provider_for(llm.FEATURE_QUIZ_GENERATION) == "local"
    batch_size = LOCAL_BATCH_SIZE if local else count
    chunks = _split_material(material, LOCAL_CHUNK_CHARS) if local else [material[:MAX_MATERIAL_CHARS]]
    questions: list[dict] = []
    seen: set[str] = set()
    empty_batches = 0
    batch = 0
    while len(questions) < count and empty_batches < 2 and batch < count + 2:
        wanted = min(batch_size, count - len(questions))
        chunk = chunks[batch % len(chunks)]
        avoid = [item["question"][:40] for item in questions][-30:]
        new_ones = [
            item
            for item in _generate_batch(chunk, wanted, chosen, difficulty, avoid)
            if _normalized(item["question"]) not in seen
        ][:wanted]
        batch += 1
        if not new_ones:
            empty_batches += 1
            continue
        empty_batches = 0
        for item in new_ones:
            seen.add(_normalized(item["question"]))
        questions.extend(new_ones)
        if on_progress:
            on_progress(len(questions), count)
        if not local:
            break
    if not questions:
        raise QuizGenerationError("AI 沒有產生有效的題目，請再試一次或換一份教材。", status_code=502)
    return questions[:count]


def _generate_batch(material: str, count: int, chosen: tuple[str, ...], difficulty: str, avoid: list[str]) -> list[dict]:
    """呼叫一次模型出 count 題。本機模型忙碌（同時只能處理一個）時等一下再試。"""
    instruction = (
        f"請根據以上教材出 {count} 題，題型只能用：{', '.join(chosen)}"
        f"（{'、'.join(QUESTION_TYPE_LABELS[item] for item in chosen)}），"
        + ("各題型數量盡量平均，" if len(chosen) > 1 else "")
        + f"難易度：{difficulty}（{DIFFICULTY_LABELS[difficulty]}）。請依照指定的 JSON 格式輸出。"
    )
    if avoid:
        instruction += "\n前面已經出過下列題目，不要重複或換句話說再出一次：\n" + "\n".join(f"- {item}" for item in avoid)
    content = f"以下是教材內容：\n\n{material}\n\n---\n\n{instruction}"
    for attempt in range(1, BUSY_ATTEMPTS + 1):
        text, reason = llm.generate_text_with_reason(
            SYSTEM_PROMPT,
            content,
            feature=llm.FEATURE_QUIZ_GENERATION,
            temperature=0.7,
            timeout_seconds=GENERATION_TIMEOUT_SECONDS,
        )
        if text is not None:
            break
        reason = reason or ""
        busy = any(marker in reason for marker in BUSY_MARKERS)
        if busy and attempt < BUSY_ATTEMPTS:
            time.sleep(BUSY_WAIT_SECONDS)
            continue
        if busy:
            raise QuizGenerationError("AI 服務現在比較忙，請過一兩分鐘再試一次。", status_code=503)
        if "沒有設定" in reason:
            raise QuizGenerationError(f"AI 出題還沒設定好：{reason}請管理員在 .env 設定。", status_code=503)
        raise QuizGenerationError(f"AI 出題失敗：{reason}", status_code=502)
    try:
        raw = _parse_json(text)
    except (ValueError, json.JSONDecodeError):
        return []
    return [item for item in (clean_question(q, chosen) for q in raw.get("questions", []) or []) if item]


def _split_material(material: str, size: int) -> list[str]:
    """教材切成每段不超過 size 字，盡量在段落換行處切開。"""
    text = material[:MAX_MATERIAL_CHARS].strip()
    chunks: list[str] = []
    while len(text) > size:
        cut = text.rfind("\n", size // 2, size)
        cut = cut if cut > 0 else size
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks or [""]


def _normalized(question: str) -> str:
    return re.sub(r"\s+|[，。？?！!、：:；;「」（）()]", "", question)


def grade(answers: list[int], selected: list[int]) -> bool:
    """全對才算對；多選題少選或多選都算錯。"""
    return sorted(set(selected)) == sorted(set(answers))
