"""AI 找課的檢索（RAG 的 R）：把對話整理成一句查詢，用 pgvector 找出最相關的已發布課程。

流程：
1. 查詢改寫：多輪對話時，「那有沒有進階一點的？」單看找不到課，要和上一句合併。
2. 相似度：在資料庫用 pgvector 算每門已發布課程和查詢的餘弦相似度。
3. 門檻：最相關的課都低於門檻，代表課程裡沒有這個主題，不交給模型硬湊答案。

門檻與 top-k 由 scripts/evaluate_rag_retrieval.py 在驗證集上決定，結果見
docs/ai-course-finder/retrieval/report.md。
"""

import os
import re

# 學生在追問（需要接上一句才看得懂）的線索：指代詞、比較、補充條件的開頭
FOLLOW_UP = re.compile(r"^(那|這|它|他|她|有沒有|還有|要|是|我是|可是|但是|不要|換|更|比較)|(一點|的呢|嗎？?$|呢？?$)")
FOLLOW_UP_MAX_LENGTH = 12
RECENT_TURNS = 3


def build_query(user_turns: list[str], strategy: str = "follow_up") -> str:
    """把學生說過的話整理成一句檢索查詢。

    strategy：
    - last：只看最後一句
    - recent：最近三句全部接起來（PR #48 原本的做法）
    - follow_up：最後一句像追問（很短，或以「那、有沒有…」開頭）才接上前一句，否則只看最後一句
    """
    turns = [turn.strip() for turn in user_turns if turn and turn.strip()]
    if not turns:
        return ""
    if strategy == "last":
        return turns[-1]
    if strategy == "recent":
        return "\n".join(turns[-RECENT_TURNS:])
    if strategy == "follow_up":
        last = turns[-1]
        if len(turns) > 1 and (len(last) < FOLLOW_UP_MAX_LENGTH or FOLLOW_UP.search(last)):
            return turns[-2] + "\n" + last
        return last
    raise ValueError(f"unknown strategy: {strategy}")


def embedding_version() -> str:
    return os.environ.get("AI_COURSE_EMBEDDING_VERSION", "")


def published_course_scores(db, query_vector, version: str | None = None) -> dict:
    """所有已發布、向量是最新版本且內容沒改過的課程 → 餘弦相似度。在資料庫用 pgvector 計算。"""
    from sqlalchemy import Float, select

    from backend.models.rag_document import SOURCE_COURSE, RagDocument
    from backend.models.student import Course
    from backend.services.ai_semantic import course_hash

    version = version or embedding_version()
    distance = RagDocument.embedding.op("OPERATOR(extensions.<=>)", return_type=Float)(query_vector)
    statement = (
        select(Course, (1 - distance).label("score"), RagDocument.content_hash)
        .join(RagDocument, RagDocument.course_id == Course.id)
        .where(
            Course.status == "published",
            RagDocument.source_type == SOURCE_COURSE,
            RagDocument.model_version == version,
        )
    )
    return {
        course.id: float(score)
        for course, score, content_hash in db.execute(statement)
        if content_hash == course_hash(course)
    }


# 以下參數由 scripts/evaluate_rag_retrieval.py 在 dev 集決定，數字與原因見 docs/ai-course-finder/retrieval/report.md
QUERY_STRATEGY = "recent"
# 保守門檻：dev 上「該有結果的查詢」至少保留 98% 的最高門檻。bge-m3 在這份課程上，
# 無關查詢的最高相似度也有 0.66，和相關查詢重疊很多，所以門檻只用來擋「明顯無關」的話
MIN_SIMILARITY = 0.574
# 交給模型的課程數：dev／test 的 Recall@6 都約 98%，再多也幾乎沒有提升，只會讓提示詞變長
TOP_K = 6
MAX_CANDIDATES = 1000


class Retrieval:
    """一次檢索的結果。rows 是 (Course, 老師名字, 老師照片) 依序排好；gated 表示被門檻擋下。"""

    def __init__(self, rows, scores, matching, status, gated, top_score):
        self.rows = rows
        self.scores = scores
        self.matching = matching
        self.status = status
        self.gated = gated
        self.top_score = top_score


def teacher_key(name: str | None) -> str:
    """比對用的老師名字：去掉空白和結尾的「老師」。資料庫裡有些名字本身就寫成「劉欣儀老師」。"""
    key = "".join((name or "").split())
    return key[: -len("老師")] if key.endswith("老師") else key


def mentioned_teachers(teacher_names, user_turns: list[str]) -> set[str]:
    """學生最近幾句話直接提到的老師。

    課程索引只有課名、曲風和介紹，沒有老師名字，所以「劉欣儀老師」用向量比對找不到她的課，
    還會被門檻當成無關。老師名字是精確的資訊，直接比對文字。少於兩個字的名字不比，避免誤判。
    """
    text = "".join("".join(turn.split()) for turn in user_turns[-RECENT_TURNS:])
    return {name for name in teacher_names if len(teacher_key(name)) >= 2 and teacher_key(name) in text}


def mentions_teacher(db, user_turns: list[str]) -> bool:
    """學生有沒有提到任何一位有已發布課程的老師。"""
    from sqlalchemy import select

    from backend.models.student import Course
    from backend.models.user import User

    names = db.scalars(
        select(User.name).join(Course, Course.teacher_id == User.id).where(Course.status == "published").distinct()
    )
    return bool(mentioned_teachers(names, user_turns))


def should_gate(status: str, criteria: dict, top_score: float | None) -> bool:
    """要不要因為「和課程無關」而不給課程。

    只有向量完整（ready）、學生沒說任何條件、而且最相關的課也低於門檻時才擋。
    學生說了地區、預算這類條件時，相似度本來就不高（約 0.52～0.56），但照條件篩出的課就是答案。
    """
    has_criteria = any(value is not None for value in criteria.values())
    return status == "ready" and not has_criteria and top_score is not None and top_score < MIN_SIMILARITY


def retrieve_courses(db, user_turns: list[str], criteria: dict, k: int = TOP_K, query: str | None = None) -> Retrieval:
    """學生點名的老師的課最前面，再來是符合條件的課，同一組裡依相似度排序；
    學生沒說任何條件、沒提到老師、最相關的課又低於門檻時，不給課程。

    向量服務沒開或索引不完整時（status 不是 ready），照最新課程排序，不套門檻，
    和改造前一樣能用，只是比較不準。
    query：需求解析模型整理好的主題（search_query）；沒有就用最近三句對話。
    """
    from sqlalchemy import select

    from backend.models.student import Course
    from backend.models.teacher import TeacherDB
    from backend.models.user import User
    from backend.services.ai_semantic import embed_texts
    from backend.services.recommendation import _apply_required_filters

    statement = (
        select(Course, User.name, TeacherDB.photo_path)
        .join(User, User.id == Course.teacher_id)
        .outerjoin(TeacherDB, TeacherDB.user_id == Course.teacher_id)
        .where(Course.status == "published")
        .order_by(Course.created_at.desc(), Course.id)
        .limit(MAX_CANDIDATES)
    )
    rows = db.execute(statement).all()
    matching = set(db.scalars(_apply_required_filters(select(Course.id).where(Course.status == "published"), criteria)))
    query = query or build_query(user_turns, QUERY_STRATEGY)
    scores, status = {}, "unavailable"
    version = embedding_version()
    if query and rows and version:
        vectors = embed_texts([query[:1000]])
        if vectors:
            scores = published_course_scores(db, vectors[0], version)
            covered = sum(1 for row in rows if row[0].id in scores)
            status = "ready" if covered == len(rows) else ("partial" if covered else "unavailable")
    top_score = max(scores.values()) if scores else None
    named = mentioned_teachers({row[1] for row in rows}, user_turns)
    gated = not named and should_gate(status, criteria, top_score)
    if gated:
        return Retrieval([], scores, matching, status, True, top_score)
    # 穩定排序：先依原本的新到舊，再依相似度，再把符合條件的排前面，最後把點名的老師排最前面
    ranked = sorted(rows, key=lambda row: scores.get(row[0].id, float("-inf")), reverse=True) if scores else list(rows)
    ranked.sort(key=lambda row: row[0].id not in matching)
    ranked.sort(key=lambda row: row[1] not in named)
    return Retrieval(ranked[:k], scores, matching, status, False, top_score)
