"""Durable decisions, immutable signal plans, slots and append-only events."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("engine_status", sa.Column("id", sa.String(30), primary_key=True), sa.Column("state", sa.String(30), nullable=False), sa.Column("updated_at", sa.BigInteger(), nullable=False), sa.Column("last_decision_at", sa.BigInteger(), nullable=True), sa.Column("error", sa.Text(), nullable=True))
    op.create_table("engine_cursors", sa.Column("symbol", sa.String(30), primary_key=True), sa.Column("strategy", sa.String(80), primary_key=True), sa.Column("last_open_time", sa.BigInteger(), nullable=False), sa.Column("initialized_at", sa.BigInteger(), nullable=False))
    op.create_table("signal_decisions", sa.Column("id", sa.String(64), primary_key=True), sa.Column("symbol", sa.String(30), nullable=False), sa.Column("strategy", sa.String(80), nullable=False), sa.Column("source_open_time", sa.BigInteger(), nullable=False), sa.Column("direction", sa.String(8), nullable=True), sa.Column("outcome", sa.String(30), nullable=False), sa.Column("reason", sa.String(100), nullable=False), sa.Column("updated_at", sa.BigInteger(), nullable=False), sa.Column("expires_at", sa.BigInteger(), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("evidence_json", sa.JSON(), nullable=False), sa.UniqueConstraint("symbol", "strategy", "source_open_time", name="uq_decision_source"))
    for name in ("symbol", "outcome"):
        op.create_index(f"ix_signal_decisions_{name}", "signal_decisions", [name])
    op.create_table("signal_plans", sa.Column("id", sa.String(64), sa.ForeignKey("signal_decisions.id"), primary_key=True), sa.Column("symbol", sa.String(30), nullable=False), sa.Column("strategy", sa.String(80), nullable=False), sa.Column("created_at", sa.BigInteger(), nullable=False), sa.Column("expires_at", sa.BigInteger(), nullable=False), sa.Column("plan_json", sa.JSON(), nullable=False), sa.Column("evidence_json", sa.JSON(), nullable=False), sa.Column("evidence_hash", sa.String(64), nullable=False))
    for name in ("symbol", "created_at"):
        op.create_index(f"ix_signal_plans_{name}", "signal_plans", [name])
    op.create_table("signal_slots", sa.Column("symbol", sa.String(30), primary_key=True), sa.Column("strategy", sa.String(80), primary_key=True), sa.Column("signal_id", sa.String(64), sa.ForeignKey("signal_plans.id"), nullable=False, unique=True), sa.Column("state", sa.String(12), nullable=False))
    op.create_table("signal_events", sa.Column("id", sa.String(36), primary_key=True), sa.Column("signal_id", sa.String(64), sa.ForeignKey("signal_plans.id"), nullable=False), sa.Column("type", sa.String(30), nullable=False), sa.Column("created_at", sa.BigInteger(), nullable=False), sa.Column("payload_json", sa.JSON(), nullable=False))
    op.create_index("ix_signal_events_signal_id", "signal_events", ["signal_id"])


def downgrade():
    for table in ("signal_events", "signal_slots", "signal_plans", "signal_decisions", "engine_cursors", "engine_status"):
        op.drop_table(table)
