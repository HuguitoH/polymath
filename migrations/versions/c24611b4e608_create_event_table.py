"""create event table

Revision ID: c24611b4e608
Revises:
Create Date: 2026-08-26 23:34:49.997712

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c24611b4e608"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE event (
            id                uuid PRIMARY KEY,
            occurred_at       timestamptz NOT NULL,
            ingested_at       timestamptz NOT NULL DEFAULT now(),
            source            text NOT NULL,
            modality          text NOT NULL,
            content           text NOT NULL CHECK (length(content) > 0),
            raw_uri           text,
            embedding         vector(1024) NOT NULL,
            embedding_model   text NOT NULL,
            embedding_version smallint NOT NULL DEFAULT 1,
            salience          real NOT NULL DEFAULT 0.5
                              CHECK (salience >= 0 AND salience <= 1),
            metadata          jsonb NOT NULL DEFAULT '{}'::jsonb
        )
    """)

    op.execute("CREATE INDEX event_occurred_at_idx ON event (occurred_at DESC)")
    op.execute("CREATE INDEX event_source_idx ON event (source)")
    op.execute("""
        CREATE INDEX event_embedding_idx ON event
        USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE event")
