"""Allow retries to reuse their original persisted user message."""
from alembic import op
import sqlalchemy as sa

revision = "0003_message_idempotency"
down_revision = "0002_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("client_message_id", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_chat_message_client_id", "chat_messages", ["session_id", "client_message_id"])


def downgrade() -> None:
    op.drop_constraint("uq_chat_message_client_id", "chat_messages", type_="unique")
    op.drop_column("chat_messages", "client_message_id")
