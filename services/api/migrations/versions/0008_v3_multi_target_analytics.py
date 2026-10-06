"""V3 multi-target analytics identity and exact target levels."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("signal_outcomes", sa.Column("strategy", sa.String(80), nullable=True))
    op.add_column("signal_outcomes", sa.Column("tp1", sa.String(80)))
    op.add_column("signal_outcomes", sa.Column("tp2", sa.String(80)))
    op.add_column("signal_outcomes", sa.Column("tp3", sa.String(80)))
    op.add_column("signal_outcomes", sa.Column("tp1_r", sa.String(80)))
    op.add_column("signal_outcomes", sa.Column("tp2_r", sa.String(80)))
    op.add_column("signal_outcomes", sa.Column("tp3_r", sa.String(80)))

    op.execute(
        "UPDATE signal_outcomes "
        "SET strategy='MV-TREND-DUAL-v2', tp3=target, tp3_r=target_r "
        "WHERE strategy IS NULL"
    )
    with op.batch_alter_table("signal_outcomes") as batch:
        batch.alter_column(
            "strategy",
            existing_type=sa.String(80),
            nullable=False,
        )
    op.create_index("ix_signal_outcomes_strategy", "signal_outcomes", ["strategy"])


def downgrade():
    op.drop_index("ix_signal_outcomes_strategy", table_name="signal_outcomes")
    op.drop_column("signal_outcomes", "tp3_r")
    op.drop_column("signal_outcomes", "tp2_r")
    op.drop_column("signal_outcomes", "tp1_r")
    op.drop_column("signal_outcomes", "tp3")
    op.drop_column("signal_outcomes", "tp2")
    op.drop_column("signal_outcomes", "tp1")
    op.drop_column("signal_outcomes", "strategy")
