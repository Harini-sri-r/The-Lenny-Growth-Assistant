"""Link each persisted assistant message to its originating user turn."""
from alembic import op
import sqlalchemy as sa

revision = "0004_message_reply_link"
down_revision = "0003_message_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("reply_to_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_chat_messages_reply_to", "chat_messages", "chat_messages", ["reply_to_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_chat_messages_reply_to", "chat_messages", ["reply_to_id"])


def downgrade() -> None:
    op.drop_constraint("uq_chat_messages_reply_to", "chat_messages", type_="unique")
    op.drop_constraint("fk_chat_messages_reply_to", "chat_messages", type_="foreignkey")
    op.drop_column("chat_messages", "reply_to_id")
