"""One immutable send state per IST date, strategy and Telegram destination."""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telegram_daily_reports",
        sa.Column("report_date", sa.String(10), primary_key=True),
        sa.Column("strategy", sa.String(80), primary_key=True),
        sa.Column("chat_id", sa.String(20), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.BigInteger(), nullable=False),
        sa.Column("claimed_at", sa.BigInteger()),
        sa.Column("sent_at", sa.BigInteger()),
        sa.Column("message_id", sa.BigInteger()),
        sa.Column("error_code", sa.String(60)),
        sa.Column("payload_json", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("telegram_daily_reports")
