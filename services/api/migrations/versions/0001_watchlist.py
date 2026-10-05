"""Create selected-coin configuration; defaults await user selection."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table("watchlist", sa.Column("symbol", sa.String(30), primary_key=True), sa.Column("sort_order", sa.Integer(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()))
    op.bulk_insert(table, [{"symbol": "BTCUSDT", "sort_order": 0}, {"symbol": "ETHUSDT", "sort_order": 1}])


def downgrade():
    op.drop_table("watchlist")
