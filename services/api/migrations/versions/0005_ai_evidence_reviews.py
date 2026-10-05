"""Asynchronous commentary and a durable request budget; financial records unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("ai_reviews",
        sa.Column("signal_id",sa.String(64),sa.ForeignKey("signal_plans.id"),primary_key=True),
        sa.Column("evidence_hash",sa.String(64),nullable=False),sa.Column("plan_hash",sa.String(64),nullable=False),
        sa.Column("model",sa.String(100),nullable=False),sa.Column("status",sa.String(20),nullable=False),
        sa.Column("attempts",sa.Integer(),nullable=False),sa.Column("next_attempt_at",sa.BigInteger(),nullable=False),
        sa.Column("completed_at",sa.BigInteger()),sa.Column("error_code",sa.String(60)),sa.Column("response_json",sa.JSON()))
    op.create_table("ai_requests",
        sa.Column("id",sa.String(36),primary_key=True),sa.Column("signal_id",sa.String(64),sa.ForeignKey("signal_plans.id")),
        sa.Column("started_at",sa.BigInteger(),nullable=False),sa.Column("completed_at",sa.BigInteger()),
        sa.Column("status",sa.String(20),nullable=False),sa.Column("usage_json",sa.JSON()),sa.Column("error_code",sa.String(60)))
    op.create_index("ix_ai_requests_signal_id","ai_requests",["signal_id"])
    op.create_index("ix_ai_requests_started_at","ai_requests",["started_at"])

def downgrade():
    op.drop_table("ai_requests")
    op.drop_table("ai_reviews")
