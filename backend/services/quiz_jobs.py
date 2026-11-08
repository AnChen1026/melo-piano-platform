"""AI 出題的背景工作。

老師送出教材與出題設定 → 建一筆 queued 工作、立刻回應 → 背景出題（本機千問可能要好幾分鐘）
→ succeeded 後老師在作業頁收到通知、審查並修改答案 → 發成題庫作業（published）。

AI 原本的題目留在 questions，老師發出去的版本留在 final_questions，之後可以拿來比對 AI 常錯在哪。
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import SessionLocal
from backend.models.quiz_job import QuizGenerationJob
from backend.models.student import Course
from backend.services import llm
from backend.services.ai_quiz import QuizGenerationError, check_settings, extract_text, generate_questions
from backend.services.student import StudentBusinessError, _commit

logger = logging.getLogger(__name__)

# 測試時會換成共用同一個交易的 Session
session_factory = SessionLocal

# 出題中的工作超過這麼久沒有更新，當成伺服器重開而中斷
STALE_AFTER = timedelta(minutes=20)
ACTIVE = ("queued", "running")
LISTED = ("queued", "running", "succeeded", "failed")


def create_job(
    db: Session,
    teacher_id: uuid.UUID,
    filename: str,
    data: bytes,
    count: int,
    types: list[str],
    difficulty: str,
    title: str | None = None,
    course_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
    use_ocr: bool = False,
) -> QuizGenerationJob:
    """先檢查檔案與設定（有錯馬上告訴老師），再建一筆排隊中的工作。真正出題在 run_job。"""
    try:
        count, chosen, difficulty = check_settings(count, types, difficulty)
        text = extract_text(filename, data, use_ocr)
    except QuizGenerationError as error:
        raise StudentBusinessError(error.status_code, str(error)) from error
    if course_id is not None:
        course = db.get(Course, course_id)
        if course is None or course.teacher_id != teacher_id:
            course_id = None
    provider = llm.provider_for(llm.FEATURE_QUIZ_GENERATION)
    job = QuizGenerationJob(
        id=uuid.uuid4(),
        teacher_id=teacher_id,
        status="queued",
        title=(title or "").strip()[:200] or None,
        course_id=course_id,
        student_id=student_id,
        due_at=due_at,
        settings={"count": count, "types": list(chosen), "difficulty": difficulty},
        source_filename=filename.replace("\\", "/").rsplit("/", 1)[-1][-255:] or "教材",
        source_text=text,
        provider=provider,
        model=llm.model_for(llm.FEATURE_QUIZ_GENERATION, provider) if provider in llm.DEFAULT_MODELS else None,
        progress=0,
    )
    db.add(job)
    _commit(db)
    db.refresh(job)
    return job


def run_job(job_id: uuid.UUID) -> None:
    """背景執行：出題、隨時更新進度，成功或失敗都記下來。"""
    db: Session = session_factory()
    try:
        job = db.get(QuizGenerationJob, job_id)
        if job is None or job.status != "queued":
            return
        job.status = "running"
        db.commit()

        def progress(done: int, total: int) -> None:
            job.progress = done
            db.commit()

        try:
            questions = generate_questions(
                job.source_text, job.settings["count"], job.settings["types"], job.settings["difficulty"], on_progress=progress
            )
        except QuizGenerationError as error:
            _finish(db, job, "failed", error=str(error))
            return
        except Exception:  # 不讓背景工作卡在 running
            logger.exception("AI 出題工作 %s 失敗", job_id)
            _finish(db, job, "failed", error="AI 出題時發生錯誤，請重新送出。")
            return
        job.progress = len(questions)
        _finish(db, job, "succeeded", questions=questions)
    finally:
        db.close()


def _finish(db: Session, job: QuizGenerationJob, state: str, questions: list | None = None, error: str | None = None) -> None:
    job.status = state
    job.questions = questions
    job.error = error
    job.finished_at = datetime.now(timezone.utc)
    db.commit()


def _expire_stale(db: Session, jobs: list[QuizGenerationJob]) -> None:
    """伺服器重開時背景工作會中斷，太久沒動的出題中工作改成失敗，老師才知道要重送。"""
    now = datetime.now(timezone.utc)
    changed = False
    for job in jobs:
        if job.status in ACTIVE and now - job.updated_at > STALE_AFTER:
            job.status = "failed"
            job.error = "出題中斷了（伺服器可能重新啟動），請重新送出。"
            job.finished_at = now
            changed = True
    if changed:
        _commit(db)


def list_jobs(db: Session, teacher_id: uuid.UUID) -> list[QuizGenerationJob]:
    """出題紀錄：排隊中、出題中、待審查、失敗的，新的在前；已發出或刪掉的不列。"""
    jobs = list(
        db.scalars(
            select(QuizGenerationJob)
            .where(QuizGenerationJob.teacher_id == teacher_id, QuizGenerationJob.status.in_(LISTED))
            .order_by(QuizGenerationJob.created_at.desc())
            .limit(30)
        )
    )
    _expire_stale(db, jobs)
    return jobs


def own_job(db: Session, teacher_id: uuid.UUID, job_id: uuid.UUID) -> QuizGenerationJob:
    job = db.get(QuizGenerationJob, job_id)
    if job is None or job.teacher_id != teacher_id:
        raise StudentBusinessError(status.HTTP_404_NOT_FOUND, "找不到這次出題。")
    _expire_stale(db, [job])
    return job


def discard_job(db: Session, teacher_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """老師不要這次的題目：標成 discarded（資料留著，之後可以看 AI 哪些題目被整份放棄）。"""
    job = own_job(db, teacher_id, job_id)
    if job.status == "published":
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "這次出題已經發成作業了。")
    job.status = "discarded"
    _commit(db)


def retry_job(db: Session, teacher_id: uuid.UUID, job_id: uuid.UUID) -> QuizGenerationJob:
    """「重新生成題目」：用同一份教材與設定再出一次，舊的那次標成 discarded。"""
    old = own_job(db, teacher_id, job_id)
    if old.status in ACTIVE or old.status == "published":
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "這次出題還在進行中，或已經發成作業了。")
    provider = llm.provider_for(llm.FEATURE_QUIZ_GENERATION)
    job = QuizGenerationJob(
        id=uuid.uuid4(),
        teacher_id=teacher_id,
        status="queued",
        title=old.title,
        course_id=old.course_id,
        student_id=old.student_id,
        due_at=old.due_at,
        settings=old.settings,
        source_filename=old.source_filename,
        source_text=old.source_text,
        provider=provider,
        model=llm.model_for(llm.FEATURE_QUIZ_GENERATION, provider) if provider in llm.DEFAULT_MODELS else None,
        progress=0,
    )
    old.status = "discarded"
    db.add(job)
    _commit(db)
    db.refresh(job)
    return job


def mark_published(db: Session, teacher_id: uuid.UUID, job_id: uuid.UUID, assignment_id: uuid.UUID, final_questions: list) -> None:
    """老師審查完發成作業：記下發出去的版本（可能改過答案、刪過題目）。"""
    job = own_job(db, teacher_id, job_id)
    job.status = "published"
    job.assignment_id = assignment_id
    job.final_questions = final_questions
    _commit(db)


def check_publishable(db: Session, teacher_id: uuid.UUID, job_id: uuid.UUID) -> QuizGenerationJob:
    job = own_job(db, teacher_id, job_id)
    if job.status != "succeeded":
        raise StudentBusinessError(status.HTTP_400_BAD_REQUEST, "這次出題還沒完成，或已經發過作業了。")
    return job
