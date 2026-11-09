"""首頁 AI 找課聊天 API。訪客不用登入；對話存在瀏覽器，每次把整段對話送上來。"""

import hashlib
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.services.ai_rate_limit import RateLimiter
from backend.services.course_chat import reply

router = APIRouter(prefix="/api/course-chat", tags=["首頁推薦"])
limiter = RateLimiter()
MAX_MESSAGES = 20


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("訊息不能是空白。")
        return value.strip()


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)

    @field_validator("messages")
    @classmethod
    def ends_with_user(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if value[-1].role != "user":
            raise ValueError("最後一則要是你說的話。")
        if len(value[-1].content) > 1000:
            raise ValueError("一次最多 1000 字。")
        # 太長的對話只留最近的部分，模型讀得下
        return value[-MAX_MESSAGES:]


class ChatCourse(BaseModel):
    id: str
    title: str
    teacher_name: str
    level: str | None = None
    style: str | None = None
    delivery_mode: str | None = None
    region: str | None = None
    price_per_lesson: int | None = None
    time_slots: str | None = None
    description: str | None = None
    image_url: str | None = None
    teacher_photo_url: str | None = None
    warnings: list[str] = []
    """程式核對價格與地區後的提醒，例如超過預算、不在指定地區。"""


class ChatResponse(BaseModel):
    reply: str
    courses: list[ChatCourse]
    """回覆裡提到的課程，資料直接來自資料庫。"""


def _owner(request: Request) -> str:
    owner = request.session.get("recommendation_owner")
    if not owner:
        owner = secrets.token_urlsafe(32)
        request.session["recommendation_owner"] = owner
    return hashlib.sha256(owner.encode()).hexdigest()


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request, db: Session = Depends(get_db)):
    if not limiter.allow(_owner(request)):
        raise HTTPException(status_code=429, detail="訊息送得太頻繁，請稍後再試。", headers={"Retry-After": "60"})
    return reply(db, [message.model_dump() for message in payload.messages])


STARTER_COUNT = 3


class ChatStarter(BaseModel):
    text: str
    category: str
    """course_search：找某種課；criteria：條件組合；platform_howto：平台怎麼用。"""


@router.get("/starters", response_model=list[ChatStarter])
def starters(db: Session = Depends(get_db)):
    """對話是空的時候給的推薦問題：從驗證通過（is_active）的問題裡隨機挑 3 句。

    三種類型（找課、條件組合、平台使用）各挑一句，讓使用者一眼看到助理能做哪些事；
    某一類沒有可用的問題時，從其他類補滿。
    """
    import random

    from sqlalchemy import select

    from backend.models.course_chat_starter import CATEGORIES, CourseChatStarter

    active = db.scalars(select(CourseChatStarter).where(CourseChatStarter.is_active.is_(True))).all()
    pools = {category: [row for row in active if row.category == category] for category in CATEGORIES}
    picked = [random.choice(pool) for pool in pools.values() if pool]
    rest = [row for row in active if row not in picked]
    picked += random.sample(rest, min(len(rest), STARTER_COUNT - len(picked)))
    random.shuffle(picked)
    return [ChatStarter(text=row.text, category=row.category) for row in picked[:STARTER_COUNT]]
