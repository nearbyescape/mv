"""V7Sonic five-minute paper cycle journal isolated from V4/V3 plans.

All new tables are NON-PUBLISHABLE and separate from legacy signal_plans,
signal_events, telegram_deliveries and published-signal analytics.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "v7_decision_cycles",
        sa.Column("boundary_ms", sa.BigInteger(), primary_key=True),
        sa.Column("strategy", sa.String(80), nullable=False),
        sa.Column("batch_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("original_http_sha256", sa.String(64), nullable=False),
        sa.Column("receipt_recorded_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("batch_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "v7_decision_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("boundary_ms", sa.BigInteger(),
                  sa.ForeignKey("v7_decision_cycles.boundary_ms"), nullable=False),
        sa.Column("symbol", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("candidate_id", sa.String(64), unique=True),
        sa.Column("expires_at_ms", sa.BigInteger()),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("boundary_ms", "symbol", name="uq_v7_decision_boundary_market"),
    )
    op.create_index("ix_v7_decisions_symbol", "v7_decision_records", ["symbol"])
    op.create_table(
        "v7_delivery_drafts",
        sa.Column("candidate_id", sa.String(64),
                  sa.ForeignKey("v7_decision_records.candidate_id"), primary_key=True),
        sa.Column("boundary_ms", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(30), nullable=False),
        sa.Column("destination_type", sa.String(20), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
    )


def downgrade():
    # Explicit drop order preserves existing V4/V3 model tables and histories.
    op.drop_table("v7_delivery_drafts")
    op.drop_index("ix_v7_decisions_symbol", table_name="v7_decision_records")
    op.drop_table("v7_decision_records")
    op.drop_table("v7_decision_cycles")
