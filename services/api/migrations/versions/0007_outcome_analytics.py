"""Observational V2 outcome analytics; no financial decision tables changed."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "signal_outcomes",
        sa.Column("signal_id", sa.String(64), sa.ForeignKey("signal_plans.id"), primary_key=True),
        sa.Column("symbol", sa.String(30), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("setup_type", sa.String(40), nullable=False),
        sa.Column("trend_regime", sa.String(20), nullable=False),
        sa.Column("published_at", sa.BigInteger(), nullable=False),
        sa.Column("first_observed_minute", sa.BigInteger(), nullable=False),
        sa.Column("last_minute_open_time", sa.BigInteger()),
        sa.Column("entry", sa.String(80), nullable=False),
        sa.Column("stop", sa.String(80), nullable=False),
        sa.Column("target", sa.String(80), nullable=False),
        sa.Column("risk_distance", sa.String(80), nullable=False),
        sa.Column("target_r", sa.String(80), nullable=False),
        sa.Column("frozen_atr", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("terminal_at", sa.BigInteger()),
        sa.Column("conservative_r", sa.String(80)),
        sa.Column("mfe_r", sa.String(80), nullable=False),
        sa.Column("mae_r", sa.String(80), nullable=False),
        sa.Column("favorable_050_at", sa.BigInteger()),
        sa.Column("favorable_100_at", sa.BigInteger()),
        sa.Column("favorable_150_at", sa.BigInteger()),
        sa.Column("favorable_200_at", sa.BigInteger()),
        sa.Column("adverse_050_at", sa.BigInteger()),
        sa.Column("adverse_100_at", sa.BigInteger()),
        sa.Column("intrabar_ambiguous", sa.Boolean(), nullable=False),
        sa.Column("source_revised", sa.Boolean(), nullable=False),
        sa.Column("observed_bars", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("error_code", sa.String(80)),
    )
    op.create_index("ix_signal_outcomes_symbol", "signal_outcomes", ["symbol"])
    op.create_index("ix_signal_outcomes_status", "signal_outcomes", ["status"])
    op.create_index("ix_signal_outcomes_published_at", "signal_outcomes", ["published_at"])

    op.create_table(
        "decision_opportunities",
        sa.Column("decision_id", sa.String(64), sa.ForeignKey("signal_decisions.id"), primary_key=True),
        sa.Column("symbol", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(8)),
        sa.Column("source_open_time", sa.BigInteger(), nullable=False),
        sa.Column("observed_from", sa.BigInteger(), nullable=False),
        sa.Column("observed_until", sa.BigInteger(), nullable=False),
        sa.Column("anchor_close", sa.String(80), nullable=False),
        sa.Column("frozen_atr", sa.String(80), nullable=False),
        sa.Column("max_up_atr", sa.String(80), nullable=False),
        sa.Column("max_down_atr", sa.String(80), nullable=False),
        sa.Column("observed_bars", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_decision_opportunities_symbol", "decision_opportunities", ["symbol"])
    op.create_index("ix_decision_opportunities_reason", "decision_opportunities", ["reason"])
    op.create_index("ix_decision_opportunities_status", "decision_opportunities", ["status"])


def downgrade():
    op.drop_table("decision_opportunities")
    op.drop_table("signal_outcomes")
