"""Add account credentials and revocable opaque login sessions."""
from alembic import op
import sqlalchemy as sa

revision = "0002_accounts"
down_revision = "0001_chat_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_users", sa.Column("email", sa.String(254), nullable=True))
    op.add_column("chat_users", sa.Column("password_hash", sa.String(256), nullable=True))
    op.create_index("ix_chat_users_email", "chat_users", ["email"], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("chat_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_chat_users_email", table_name="chat_users")
    op.drop_column("chat_users", "password_hash")
    op.drop_column("chat_users", "email")
