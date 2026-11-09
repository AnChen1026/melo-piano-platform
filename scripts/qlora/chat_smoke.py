"""端對端抽查：用網站的 course_chat.reply() 跑幾段對話，比較規則解析與微調解析。

走真的資料庫、真的 pgvector 檢索、真的千問回覆，只差在需求解析用哪一種。
結果存成 Markdown 供開發紀錄引用。

用法（閘道要開放 COURSE_PARSER_LLM_MODEL 指定的模型）：
    AI_COURSE_GATEWAY_URL=http://127.0.0.1:18763 AI_COURSE_GATEWAY_TOKEN=... AI_COURSE_EMBEDDING_VERSION=... \\
    uv run python -m scripts.qlora.chat_smoke --model melo-qwen3-4b-ft
"""

import argparse
import os
import time
from pathlib import Path

from backend.core.database import SessionLocal
from backend.services import course_chat
from backend.services.ai_course_parser import parse_conversation

OUT = Path(__file__).resolve().parents[2] / "docs/ai-course-finder/training/chat_smoke.md"

DIALOGUES = [
    ("規則看不懂的預算說法", ["想學爵士鋼琴，一堂一千二以內"]),
    ("「兒童」是對象不是曲風", ["想準備兒童鋼琴檢定"]),
    ("時段口語", ["下班後想學流行鋼琴，在台北"]),
    ("多輪：先找課再改上課方式", ["我零基礎想自彈自唱", "我比較想要線上的"]),
    ("平台使用", ["請假要提前多久講"]),
    ("無關問題", ["鋼琴要多久調音一次"]),
]


def run(dialogue, use_model):
    if use_model:
        os.environ["COURSE_PARSER_LLM_MODEL"] = use_model
    else:
        os.environ["COURSE_PARSER_LLM_MODEL"] = " "  # 空白：視為沒設定，走規則
    messages, rows = [], []
    with SessionLocal() as db:
        for text in dialogue:
            messages.append({"role": "user", "content": text})
            parsed = parse_conversation(messages) if use_model else None
            began = time.perf_counter()
            result = course_chat.reply(db, messages)
            seconds = time.perf_counter() - began
            messages.append({"role": "assistant", "content": result["reply"]})
            rows.append((text, parsed, result, seconds))
    return rows


def render(title, method, rows):
    lines = [f"**{method}**", ""]
    for text, parsed, result, seconds in rows:
        lines.append(f"- 學生：{text}（{seconds:.1f} 秒）")
        if parsed:
            fields = {k: v for k, v in parsed.items() if v not in (None, "")}
            lines.append(f"  - 解析：`{fields}`")
        cards = [f"{c['title']}（{c.get('delivery_mode') or '未填'}，{c.get('region') or '—'}，{c.get('price_per_lesson')}）"
                 + (f" ⚠ {'；'.join(c['warnings'])}" if c.get("warnings") else "") for c in result["courses"]]
        lines.append(f"  - 卡片 {len(cards)} 張：" + ("、".join(cards) if cards else "無"))
        reply = result["reply"].replace("\n", " ")
        lines.append(f"  - 回覆：{reply[:160]}{'…' if len(reply) > 160 else ''}")
    lines.append("")
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    out = ["# AI 找課端對端抽查：規則解析 vs 微調解析", "",
           "同一個資料庫、同一套 pgvector 檢索、同一個回覆模型（千問 4B），只換需求解析。由 `scripts/qlora/chat_smoke.py` 產生。", ""]
    for title, dialogue in DIALOGUES:
        print("==", title, flush=True)
        out += [f"## {title}", ""]
        out += render(title, "規則解析（原本）", run(dialogue, None))
        out += render(title, f"微調解析（{args.model}）", run(dialogue, args.model))
    OUT.write_text("\n".join(out), encoding="utf-8")
    print("saved", OUT)


if __name__ == "__main__":
    main()
