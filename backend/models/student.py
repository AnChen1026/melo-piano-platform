"""學生找課之後用到的資料表。

課程、接洽對話、綁定碼、課表、可上課時段、課務申請、練習錄音和練習回饋。
每筆資料都記老師與課程，不能只靠學生查詢。
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class Course(Base):
    """老師發布的一門鋼琴課。只有已發布可以洽詢。"""

    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_courses_status",
        ),
        CheckConstraint(
            "delivery_mode IS NULL OR delivery_mode IN ('online', 'in_person')",
            name="ck_courses_delivery_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    price_per_lesson: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_slots: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    reference_midi_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 課程圖片，沒有上傳時前端用預設圖
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    @property
    def has_reference_midi(self) -> bool:
        return bool(self.reference_midi_path)

    @property
    def image_url(self) -> str | None:
        return f"/api/images/courses/{self.id}" if self.image_path else None


class ReferenceMidi(Base):
    """一門課目前使用的參考 MIDI metadata；檔案內容放在檔案儲存。"""

    __tablename__ = "reference_midis"
    __table_args__ = (
        UniqueConstraint("course_id", name="uq_reference_midis_course_id"),
        CheckConstraint(
            "file_size_bytes >= 0",
            name="ck_reference_midis_file_size_nonnegative",
        ),
        Index("ix_reference_midis_teacher_course", "teacher_id", "course_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class RecommendationSession(Base):
    """訪客在首頁找課時的一段對談與已確認條件。"""

    __tablename__ = "recommendation_sessions"
    __table_args__ = (
        CheckConstraint(
            "question_count >= 0 AND question_count <= 2",
            name="ck_recommendation_sessions_question_count",
        ),
        CheckConstraint(
            "status IN ('asking', 'done', 'unsupported')",
            name="ck_recommendation_sessions_status",
        ),
        Index("ix_recommendation_sessions_owner_hash", "owner_hash"),
        Index("ix_recommendation_sessions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    messages: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, default=list)
    criteria: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    asked_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="asking")
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationItem(Base):
    """一次推薦的單筆結果；course_id 保證它來自正式課程資料。"""

    __tablename__ = "recommendation_items"
    __table_args__ = (
        UniqueConstraint("session_id", "course_id", name="uq_recommendation_items_session_course"),
        UniqueConstraint("session_id", "position", name="uq_recommendation_items_session_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "recommendation_sessions.id",
            ondelete="CASCADE",
            name="fk_recommendation_items_session_id_recommendation_sessions",
        ),
        nullable=False,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "courses.id",
            ondelete="CASCADE",
            name="fk_recommendation_items_course_id_courses",
        ),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    matched: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    unknown: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InquiryConversation(Base):
    """一位學生和一門已發布課程的接洽對話。綁定前後是同一段。"""

    __tablename__ = "inquiry_conversations"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uq_inquiry_conversations_student_course"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConversationMessage(Base):
    """接洽對話裡的一則訊息。"""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_conversation_messages_client_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inquiry_conversations.id"), nullable=False
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # 用送出當下的時間，同一個交易裡的多則訊息才排得出先後
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CourseBinding(Base):
    """學生和一門課的上課資格。解除後對話還在，教學功能關閉。"""

    __tablename__ = "course_bindings"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uq_course_bindings_student_course"),
        CheckConstraint("status IN ('bound', 'unbound')", name="ck_course_bindings_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="bound")
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BindingCode(Base):
    """只給一位學生、一門課使用的綁定碼。"""

    __tablename__ = "binding_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inquiry_conversations.id"), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CourseJoinCode(Base):
    """老師替一門課產生的限時綁定碼。期限內任何拿到碼的學生都能加入這門課；一門課同時只有一組。"""

    __tablename__ = "course_join_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LessonSession(Base):
    """正式課表上的一堂課。老師同意且時段空著之後才會寫入或修改。"""

    __tablename__ = "lesson_sessions"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_lesson_sessions_time_order"),
        CheckConstraint("status IN ('scheduled', 'cancelled')", name="ck_lesson_sessions_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")
    # 由哪個固定上課時間排出來的；單獨排的課是空的
    recurring_lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recurring_lessons.id", ondelete="SET NULL", name="fk_lesson_sessions_recurring_lesson_id"),
        nullable=True,
    )


class WeeklyAvailability(Base):
    """老師每週固定可上課的一段時間，例如週一 18:00-21:00。時間是台灣時間當天的第幾分鐘。"""

    __tablename__ = "weekly_availability"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_weekly_availability_weekday"),
        CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND end_minute > start_minute",
            name="ck_weekly_availability_time",
        ),
        Index("ix_weekly_availability_teacher", "teacher_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # 0 是週一
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    end_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    generated_through: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecurringLesson(Base):
    """老師和學生談好的固定上課時間，例如每週二 19:15-20:15。時間是台灣時間當天的第幾分鐘。"""

    __tablename__ = "recurring_lessons"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_recurring_lessons_weekday"),
        CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND end_minute > start_minute",
            name="ck_recurring_lessons_time",
        ),
        Index("ix_recurring_lessons_teacher", "teacher_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    # 0 是週一
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    end_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    generated_through: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AvailabilitySlot(Base):
    """老師開放給已綁定學生預約的一段時間。

    open：可預約；held：有學生點選、等老師完成約課；booked：已排進正式課表。
    """

    __tablename__ = "availability_slots"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_availability_slots_time_order"),
        CheckConstraint("status IN ('open', 'held', 'booked')", name="ck_availability_slots_status"),
        CheckConstraint(
            "status = 'open' OR (student_id IS NOT NULL AND course_id IS NOT NULL)",
            name="ck_availability_slots_holder",
        ),
        Index("ix_availability_slots_teacher_starts", "teacher_id", "starts_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    # 預約的學生與課程；open 時是空的
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    course_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=True)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lesson_sessions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # 由每週可上課時間產生的；老師改每週時間時，只有這些且還沒人預約的會重算
    from_weekly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    def reopen(self) -> None:
        """取消預約：回到可預約，誰預約過不再保留。"""
        self.status = "open"
        self.student_id = None
        self.course_id = None
        self.lesson_id = None


class ChangeRequest(Base):
    """約課、請假或調課。送出後正式課表先不變。"""

    __tablename__ = "change_requests"
    __table_args__ = (
        CheckConstraint("request_type IN ('booking', 'leave', 'reschedule')", name="ck_change_requests_type"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_change_requests_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("lesson_sessions.id"), nullable=True)
    # 學生點選老師的可上課時段送出的約課；自己填時間的約課是空的
    availability_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("availability_slots.id", ondelete="SET NULL", name="fk_change_requests_availability_slot_id"),
        nullable=True,
    )
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proposed_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PracticeRecording(Base):
    """已綁定學生送出的一次練習錄音。"""

    __tablename__ = "practice_recordings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_practice_recordings_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # 繳交哪一份作業；舊資料或直接照課程參考曲練習的是空的
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assignments.id", ondelete="SET NULL"), nullable=True
    )
    # 送出當時用的參考 MIDI（作業的或課程的）。老師之後換曲子，舊練習仍知道是跟哪一首比的
    reference_midi_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 錄音時有開節拍器就記下速度，節奏照它評分；沒開或上傳音檔時是空的
    metronome_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PracticeFeedback(Base):
    """一筆練習錄音自己的音高、節奏與文字。失敗時分數保持空白，不顯示 0 分。"""

    __tablename__ = "practice_feedbacks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_practice_feedbacks_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practice_recordings.id"), unique=True, nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    pitch_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rhythm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 答案與學生上下對照的樂譜（MusicXML）存放位置；產生失敗或舊資料是空的
    score_sheet_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    @property
    def has_score_sheet(self) -> bool:
        return bool(self.score_sheet_path)


class LessonPreparationSummary(Base):
    """老師上課前看的練習整理：上一堂結束到這一堂開始前。和每一筆練習回饋分開保存。"""

    __tablename__ = "lesson_preparation_summaries"
    __table_args__ = (
        UniqueConstraint("lesson_id", name="uq_lesson_preparation_summaries_lesson"),
        CheckConstraint("written_by IN ('llm', 'rules')", name="ck_lesson_preparation_summaries_written_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lesson_sessions.id"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 來源錄音與狀態的雜湊；和現在算出來的不同，就代表摘要需要更新
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_recording_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    written_by: Mapped[str] = mapped_column(String(16), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
