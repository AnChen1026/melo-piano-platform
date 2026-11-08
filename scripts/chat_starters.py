"""驗證並寫入 AI 找課的推薦問題（scripts/data/chat_starters.json）。

每一句都用網站實際的檢索（backend.services.rag_retrieval.retrieve_courses）跑一次：
- course_search：沒被門檻擋下，前 3 名至少一門是預期主題（示範課程才查得到主題，沒有就略過這項）
- criteria：解析出預期的條件，前 3 名都符合條件
- platform_howto：平台說明真的寫到這個主題（關鍵字都在 PLATFORM_GUIDE 裡）

預設只驗證、印出結果並寫報告；加 --apply 和相符的 --confirm-database 才寫入資料庫。
寫入前 JSON 的 reviewed 必須是 true（人工審過）。課程或索引改過後要重跑，沒過的會自動停用。

需要閘道與 bge-m3：AI_COURSE_GATEWAY_URL、AI_COURSE_GATEWAY_TOKEN、AI_COURSE_EMBEDDING_VERSION。
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/data/chat_starters.json"
REPORT = ROOT / "docs/ai-course-finder/starters/verification.json"


def criteria_for(text):
    from backend.services.course_chat import SHORT_CITY
    from backend.services.recommendation import parse_criteria

    return parse_criteria(SHORT_CITY.sub(r"\1市", text))


def check(db, starter, themes_by_course):
    from backend.services.course_chat import PLATFORM_GUIDE
    from backend.services.rag_retrieval import retrieve_courses

    if starter["category"] == "platform_howto":
        missing = [word for word in starter["guide_keywords"] if word not in PLATFORM_GUIDE]
        return (not missing, None, "平台說明沒寫到：" + "、".join(missing) if missing else "平台說明有寫到")
    criteria = criteria_for(starter["text"])
    result = retrieve_courses(db, [starter["text"]], criteria)
    top = result.rows[:3]
    if result.status != "ready":
        return False, result.top_score, f"向量索引不完整（{result.status}），無法驗證"
    if result.gated or not top:
        return False, result.top_score, "被門檻擋下，沒有課程"
    if starter["category"] == "criteria":
        wrong = {k: criteria.get(k) for k, v in starter["expected_criteria"].items() if criteria.get(k) != v}
        if wrong:
            return False, result.top_score, f"條件解析不符：{wrong}"
        if len(top) < 3 or any(row[0].id not in result.matching for row in top):
            return False, result.top_score, "前 3 名有課程不符合條件"
        return True, result.top_score, "前 3 名都符合條件"
    found = [themes_by_course.get(row[0].id) for row in top]
    if not any(found):
        return True, result.top_score, "沒有示範課程主題可比對，只確認有結果"
    if not set(found) & set(starter["expected_themes"]):
        return False, result.top_score, f"前 3 名沒有預期主題（找到 {', '.join(t or '?' for t in found)}）"
    return True, result.top_score, "前 3 名有預期主題"


def main():
    import os

    from sqlalchemy import select
    from sqlalchemy.engine import make_url

    from backend.core.config import get_database_url
    from backend.core.database import SessionLocal
    from backend.models.course_chat_starter import CourseChatStarter
    from scripts.evaluate_rag_retrieval import catalog_truth

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database", default="")
    args = parser.parse_args()
    version = os.environ.get("AI_COURSE_EMBEDDING_VERSION", "")
    if not version:
        parser.error("AI_COURSE_EMBEDDING_VERSION is required")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    target = make_url(get_database_url()).database
    if args.apply:
        if not source.get("reviewed"):
            parser.error("scripts/data/chat_starters.json 還沒有人工審核（reviewed 不是 true）")
        if not target or args.confirm_database != target:
            parser.error("--confirm-database must match the target database name")

    themes_by_course = {course_id: info["theme"] for course_id, info in catalog_truth().items()}
    now = datetime.now(UTC)
    results = []
    with SessionLocal() as db:
        for starter in source["starters"]:
            ok, score, note = check(db, starter, themes_by_course)
            results.append({**starter, "passed": ok, "top_score": None if score is None else round(score, 4), "note": note})
        if args.apply:
            existing = {row.text: row for row in db.scalars(select(CourseChatStarter))}
            listed = {item["text"] for item in results}
            for item in results:
                row = existing.get(item["text"]) or CourseChatStarter(text=item["text"])
                db.add(row)
                row.category = item["category"]
                row.is_active = item["passed"]
                row.verified_at = now
                row.verified_model_version = version
                row.top_score = item["top_score"]
                row.check_note = item["note"][:300]
            # JSON 裡拿掉的問題停用，不刪除，保留驗證紀錄
            for text, row in existing.items():
                if text not in listed:
                    row.is_active = False
            db.commit()

    passed = sum(item["passed"] for item in results)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {"verified_at": now.isoformat(timespec="seconds"), "embedding_version": version, "passed": passed,
             "total": len(results), "reviewed": source.get("reviewed"), "results": results},
            ensure_ascii=False, indent=1,
        ) + "\n",
        encoding="utf-8",
    )
    for item in results:
        score = "  -  " if item["top_score"] is None else f"{item['top_score']:.3f}"
        print(f"{'✅' if item['passed'] else '❌'} {score} {item['category']:<14} {item['text']}　{item['note']}")
    print(f"passed={passed}/{len(results)} mode={'apply' if args.apply else 'dry-run'}")


if __name__ == "__main__":
    main()
