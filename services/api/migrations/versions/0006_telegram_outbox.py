"""Durable Telegram delivery records; original financial records unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("telegram_deliveries",
        sa.Column("event_id",sa.String(36),sa.ForeignKey("signal_events.id"),primary_key=True),
        sa.Column("signal_id",sa.String(64),sa.ForeignKey("signal_plans.id"),nullable=False),
        sa.Column("chat_id",sa.String(20),nullable=False),sa.Column("status",sa.String(20),nullable=False),
        sa.Column("attempts",sa.Integer(),nullable=False),sa.Column("next_attempt_at",sa.BigInteger(),nullable=False),
        sa.Column("claimed_at",sa.BigInteger()),sa.Column("sent_at",sa.BigInteger()),sa.Column("message_id",sa.BigInteger()),
        sa.Column("error_code",sa.String(60)),sa.Column("payload_json",sa.JSON(),nullable=False),
        sa.Column("payload_hash",sa.String(64),nullable=False),sa.Column("evidence_hash",sa.String(64),nullable=False),
        sa.Column("plan_hash",sa.String(64),nullable=False))
    op.create_index("ix_telegram_deliveries_signal_id","telegram_deliveries",["signal_id"])
    op.create_index("ix_telegram_deliveries_status","telegram_deliveries",["status"])


def downgrade():
    op.drop_table("telegram_deliveries")
