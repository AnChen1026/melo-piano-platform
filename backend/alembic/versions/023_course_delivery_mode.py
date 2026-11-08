"""課程上課方式只留 online、in_person：早期種子資料存成中文，找課篩選比對不到。

「線上與實體」兩種都可以的課歸為實體：實體課通常也能談線上，反過來不一定。
其他認不得的值改成未填（NULL），確保加上檢查限制時不會因為意料外的舊資料而失敗。

Revision ID: 023_course_delivery_mode
Revises: 022_quiz_generation_jobs
"""

from alembic import op

revision = "023_course_delivery_mode"
down_revision = "022_quiz_generation_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE courses SET delivery_mode = 'online' WHERE delivery_mode = '線上'")
    op.execute("UPDATE courses SET delivery_mode = 'in_person' WHERE delivery_mode IN ('實體', '線上與實體')")
    op.execute("UPDATE courses SET delivery_mode = NULL WHERE delivery_mode NOT IN ('online', 'in_person')")
    op.create_check_constraint(
        "ck_courses_delivery_mode",
        "courses",
        "delivery_mode IS NULL OR delivery_mode IN ('online', 'in_person')",
    )


def downgrade():
    op.drop_constraint("ck_courses_delivery_mode", "courses", type_="check")
