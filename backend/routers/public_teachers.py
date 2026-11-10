"""訪客讀取首頁「認識老師」的老師。不需要登入。

只挑有已發布課程、帳號啟用中的老師，名字和資料都來自資料庫，點「看這位老師的課」和 AI 找課都找得到。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.models.student import Course
from backend.models.teacher import TeacherDB
from backend.models.user import User

router = APIRouter(prefix="/api/teachers", tags=["老師"])


class FeaturedTeacherResponse(BaseModel):
    id: uuid.UUID
    name: str
    specialty: str | None
    bio: str | None
    photo_url: str | None


def _first_item(text: str | None) -> str | None:
    """專長常寫成「電影與動畫改編、遊戲 BGM 的循環銜接、…」，卡片只放第一項。"""
    first = (text or "").split("、")[0].strip()
    return first or None


@router.get("/featured", response_model=list[FeaturedTeacherResponse])
def featured_teachers(limit: int = Query(4, ge=1, le=12), db: Session = Depends(get_db)):
    """有照片的老師優先，其餘隨機，讓首頁每次介紹不同的老師。"""
    has_published = exists().where(Course.teacher_id == User.id, Course.status == "published")
    rows = db.execute(
        select(User.id, User.name, TeacherDB.expertise, TeacherDB.short_intros, TeacherDB.photo_path)
        .outerjoin(TeacherDB, TeacherDB.user_id == User.id)
        .where(User.role == "teacher", User.is_active.is_(True), has_published)
        .order_by(TeacherDB.photo_path.is_(None), func.random())
        .limit(limit)
    ).all()
    return [
        {
            "id": user_id,
            "name": name,
            "specialty": _first_item(expertise),
            "bio": intro,
            "photo_url": f"/api/images/teachers/{user_id}" if photo_path else None,
        }
        for user_id, name, expertise, intro, photo_path in rows
    ]
