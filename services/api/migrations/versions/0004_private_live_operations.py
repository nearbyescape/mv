"""Invite-only identities, durable notification delivery, audit and singleton service leases."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users", sa.Column("id",sa.String(36),primary_key=True), sa.Column("email",sa.String(254),nullable=False,unique=True), sa.Column("name",sa.String(80),nullable=False),sa.Column("role",sa.String(12),nullable=False),sa.Column("password_hash",sa.Text(),nullable=False),sa.Column("enabled",sa.Boolean(),nullable=False),sa.Column("created_at",sa.BigInteger(),nullable=False))
    op.create_table("user_sessions",sa.Column("token_hash",sa.String(64),primary_key=True),sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id"),nullable=False),sa.Column("created_at",sa.BigInteger(),nullable=False),sa.Column("expires_at",sa.BigInteger(),nullable=False),sa.Column("revoked_at",sa.BigInteger(),nullable=True))
    op.create_index("ix_user_sessions_user_id","user_sessions",["user_id"])
    op.create_table("invites",sa.Column("token_hash",sa.String(64),primary_key=True),sa.Column("email",sa.String(254),nullable=False),sa.Column("role",sa.String(12),nullable=False),sa.Column("created_at",sa.BigInteger(),nullable=False),sa.Column("expires_at",sa.BigInteger(),nullable=False),sa.Column("used_at",sa.BigInteger(),nullable=True),sa.Column("created_by",sa.String(36),nullable=True))
    op.create_table("auth_throttles",sa.Column("key",sa.String(64),primary_key=True),sa.Column("count",sa.Integer(),nullable=False),sa.Column("window_at",sa.BigInteger(),nullable=False))
    op.create_table("audit_events",sa.Column("id",sa.String(36),primary_key=True),sa.Column("actor_id",sa.String(36),nullable=True),sa.Column("action",sa.String(60),nullable=False),sa.Column("created_at",sa.BigInteger(),nullable=False),sa.Column("detail_json",sa.JSON(),nullable=False))
    op.create_index("ix_audit_events_created_at","audit_events",["created_at"])
    op.create_table("web_notifications",sa.Column("id",sa.String(36),sa.ForeignKey("signal_events.id"),primary_key=True),sa.Column("signal_id",sa.String(64),sa.ForeignKey("signal_plans.id"),nullable=False),sa.Column("type",sa.String(30),nullable=False),sa.Column("created_at",sa.BigInteger(),nullable=False),sa.Column("payload_json",sa.JSON(),nullable=False))
    op.create_index("ix_web_notifications_signal_id","web_notifications",["signal_id"])
    op.create_index("ix_web_notifications_created_at","web_notifications",["created_at"])
    op.create_table("notification_reads",sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id"),primary_key=True),sa.Column("notification_id",sa.String(36),sa.ForeignKey("web_notifications.id"),primary_key=True),sa.Column("read_at",sa.BigInteger(),nullable=False))
    op.create_table("service_leases",sa.Column("name",sa.String(30),primary_key=True),sa.Column("owner",sa.String(36),nullable=False),sa.Column("heartbeat",sa.BigInteger(),nullable=False))


def downgrade():
    for name in ("service_leases","notification_reads","web_notifications","audit_events","auth_throttles","invites","user_sessions","users"):
        op.drop_table(name)
