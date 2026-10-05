"""Persistent exchange metadata, source candles, indicator history and collector health."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("market_contracts", sa.Column("symbol", sa.String(30), primary_key=True), sa.Column("valid", sa.Boolean(), nullable=False), sa.Column("reason", sa.Text(), nullable=False), sa.Column("checked_at", sa.BigInteger(), nullable=False), sa.Column("metadata_json", sa.JSON(), nullable=False))
    fields = [sa.Column("symbol", sa.String(30), primary_key=True), sa.Column("timeframe", sa.String(4), primary_key=True), sa.Column("open_time", sa.BigInteger(), primary_key=True), sa.Column("close_time", sa.BigInteger(), nullable=False)]
    fields += [sa.Column(name, sa.String(80), nullable=False) for name in ("open", "high", "low", "close", "volume")]
    fields.append(sa.Column("source_hash", sa.String(64), nullable=False))
    op.create_table("candles", *fields)
    fields = [sa.Column("symbol", sa.String(30), primary_key=True), sa.Column("timeframe", sa.String(4), primary_key=True), sa.Column("open_time", sa.BigInteger(), primary_key=True)]
    fields += [sa.Column(name, sa.String(80), nullable=True) for name in ("ema20", "ema50", "sma200", "atr")]
    fields.append(sa.Column("lineage", sa.String(64), nullable=False))
    op.create_table("indicator_snapshots", *fields)
    op.create_table("indicator_checkpoints", sa.Column("symbol", sa.String(30), primary_key=True), sa.Column("timeframe", sa.String(4), primary_key=True), sa.Column("state_json", sa.JSON(), nullable=False))
    op.create_table("collector_status", sa.Column("id", sa.String(30), primary_key=True), sa.Column("state", sa.String(30), nullable=False), sa.Column("updated_at", sa.BigInteger(), nullable=False), sa.Column("last_event_at", sa.BigInteger(), nullable=True), sa.Column("clock_offset_ms", sa.BigInteger(), nullable=False), sa.Column("reconnects", sa.Integer(), nullable=False), sa.Column("error", sa.Text(), nullable=True))


def downgrade():
    for table in ("collector_status", "indicator_checkpoints", "indicator_snapshots", "candles", "market_contracts"):
        op.drop_table(table)
