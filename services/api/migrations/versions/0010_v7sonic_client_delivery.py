"""Separate signed V7 client-release authority and fenced outbox.

Paper journals remain blocked; this migration grants no publication rights.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "v7_client_approvals",
        sa.Column("candidate_id", sa.String(64),
                  sa.ForeignKey("v7_decision_records.candidate_id"),
                  primary_key=True),
        sa.Column("decision_boundary_ms", sa.BigInteger(), nullable=False),
        sa.Column("batch_sha256", sa.String(64), nullable=False),
        sa.Column("destination_chat_id", sa.String(20), nullable=False),
        sa.Column("approved_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("expires_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("approval_json", sa.JSON(), nullable=False),
        sa.Column("signature_hmac", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
    )
    op.create_table(
        "v7_client_deliveries",
        sa.Column("candidate_id", sa.String(64),
                  sa.ForeignKey("v7_client_approvals.candidate_id"),
                  primary_key=True),
        sa.Column("destination_chat_id", sa.String(20), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("claimed_at_ms", sa.BigInteger()),
        sa.Column("sent_at_ms", sa.BigInteger()),
        sa.Column("message_id", sa.BigInteger()),
        sa.Column("error_code", sa.String(60)),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_v7_client_deliveries_status",
        "v7_client_deliveries", ["status", "expires_at_ms"]
    )


def downgrade():
    op.drop_index("ix_v7_client_deliveries_status", table_name="v7_client_deliveries")
    op.drop_table("v7_client_deliveries")
    op.drop_table("v7_client_approvals")
