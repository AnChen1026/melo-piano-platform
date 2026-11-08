"""AI 找課的推薦問題：使用者沒頭緒時，從驗證過的問題隨機給 3 句。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    String,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base

CATEGORIES = ("course_search", "criteria", "platform_howto")


class CourseChatStarter(Base):
    __tablename__ = "course_chat_starters"
    __table_args__ = (
        CheckConstraint(
            "category IN ('course_search', 'criteria', 'platform_howto')", name="ck_course_chat_starters_category"
        ),
        Index("ix_course_chat_starters_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    # course_search：找某種課；criteria：條件組合（地區、預算、時段）；platform_howto：平台怎麼用
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # 驗證沒過就不給使用者看
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_model_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 驗證結果的說明，例如「前 3 名沒有預期主題」
    check_note: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
