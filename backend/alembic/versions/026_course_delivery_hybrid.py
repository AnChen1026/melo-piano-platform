"""課程上課方式加上 hybrid（線上或實體皆可），不再用空值代表「皆可」。

原本只有 online、in_person，示範資料「線上／實體皆可」的課只能存成空值，篩選和卡片提醒都要猜空值是什麼意思。
現在空值只代表老師沒填。介紹裡寫著「上課方式：線上／實體皆可。」的空值課（示範資料匯入時寫的）轉成 hybrid；
其他空值維持不變。

Revision ID: 026_course_delivery_hybrid
Revises: 025_course_chat_starters
"""

from alembic import op

revision = "026_course_delivery_hybrid"
down_revision = "025_course_chat_starters"
branch_labels = None
depends_on = None

HYBRID_SENTENCE = "上課方式：線上／實體皆可。"


def upgrade():
    op.drop_constraint("ck_courses_delivery_mode", "courses", type_="check")
    op.create_check_constraint(
        "ck_courses_delivery_mode",
        "courses",
        "delivery_mode IS NULL OR delivery_mode IN ('online', 'in_person', 'hybrid')",
    )
    op.execute(
        f"UPDATE courses SET delivery_mode = 'hybrid' "
        f"WHERE delivery_mode IS NULL AND description LIKE '%{HYBRID_SENTENCE}%'"
    )


def downgrade():
    op.execute("UPDATE courses SET delivery_mode = NULL WHERE delivery_mode = 'hybrid'")
    op.drop_constraint("ck_courses_delivery_mode", "courses", type_="check")
    op.create_check_constraint(
        "ck_courses_delivery_mode",
        "courses",
        "delivery_mode IS NULL OR delivery_mode IN ('online', 'in_person')",
    )
