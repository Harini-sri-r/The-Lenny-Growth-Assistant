"""Store each account's appearance mode and pastel palette."""
from alembic import op
import sqlalchemy as sa

revision = "0005_account_appearance"
down_revision = "0004_message_reply_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_users", sa.Column("appearance_mode", sa.String(8), nullable=False, server_default="light"))
    op.add_column("chat_users", sa.Column("pastel_palette", sa.String(16), nullable=False, server_default="pink"))


def downgrade() -> None:
    op.drop_column("chat_users", "pastel_palette")
    op.drop_column("chat_users", "appearance_mode")
