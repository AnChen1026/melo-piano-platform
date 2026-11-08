from fastapi import FastAPI
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from backend.core.config import get_session_secret_key, read_env_value
from backend.core.database import SessionLocal
from backend.routers.admin import router as admin_router
from backend.routers.assignments import router as assignments_router
from backend.routers.health import router as health_router
from backend.routers.images import router as images_router
from backend.routers.public_courses import router as public_courses_router
from backend.routers.recommendations import router as recommendations_router
from backend.routers.course_chat import router as course_chat_router
from backend.routers.auth import router as auth_router
from backend.routers.student import router as student_router
from backend.routers.support import router as support_router
from backend.routers.chat_ws import router as chat_ws_router
from backend.routers.teacher_chat import router as teacher_chat_router
from backend.routers.teacher_courses import router as teacher_courses_router
from backend.routers.teacher_inquiries import router as teacher_inquiries_router
from backend.routers.teacher_availability import router as teacher_availability_router
from backend.routers.teacher_lessons import router as teacher_lessons_router
from backend.routers.teacher_materials import router as teacher_materials_router
from backend.routers.teacher_practice import router as teacher_practice_router
from backend.routers.teacher_profile import router as teacher_profile_router
from backend.routers.teacher_quizzes import router as teacher_quizzes_router
from backend.routers.teacher_students import router as teacher_students_router
from backend.routers.teacher_studio import router as teacher_studio_router
from backend.services.admin import seed_admin_if_needed
from backend.services.demo_accounts import seed_demo_accounts_if_needed
from backend.services import teacher_sync  # 註冊老師資料同步，讓老師登入時補上 teacher_profiles

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret_key(),
    same_site="lax",
    https_only=(read_env_value("SESSION_HTTPS_ONLY") or "false").lower() == "true",
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(public_courses_router)
app.include_router(images_router)
app.include_router(recommendations_router)
app.include_router(course_chat_router)
app.include_router(admin_router)
app.include_router(student_router)
app.include_router(assignments_router)
app.include_router(support_router)
app.include_router(chat_ws_router)
# 老師端 API
for teacher_module in (
    teacher_profile_router,
    teacher_students_router,
    teacher_studio_router,
    teacher_chat_router,
    teacher_courses_router,
    teacher_inquiries_router,
    teacher_lessons_router,
    teacher_availability_router,
    teacher_materials_router,
    teacher_practice_router,
    teacher_quizzes_router,
):
    app.include_router(teacher_module)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",       # 這是 Docker 前端 Nginx 的網址
        "http://127.0.0.1",
        "http://localhost:5173",  # 本機 Vite 開發環境（可選）
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """本機測試：若 .env 有管理員、demo 帳密就建立帳號。資料表一律用 alembic upgrade head 建立。"""
    db = SessionLocal()
    try:
        seed_admin_if_needed(db)
        seed_demo_accounts_if_needed(db)
    finally:
        db.close()


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
