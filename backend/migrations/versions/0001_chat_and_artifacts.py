"""Initial users, chat history, and artifacts."""
from alembic import op
import sqlalchemy as sa

revision = "0001_chat_artifacts"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("chat_users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table("chat_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("chat_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_table("chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role in ('user', 'assistant')", name="ck_chat_message_role"),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_table("chat_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("chat_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("artifact_format", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_artifacts_user_id", "chat_artifacts", ["user_id"])
    op.create_index("ix_chat_artifacts_session_id", "chat_artifacts", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_artifacts_session_id", table_name="chat_artifacts")
    op.drop_index("ix_chat_artifacts_user_id", table_name="chat_artifacts")
    op.drop_table("chat_artifacts")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_table("chat_users")
