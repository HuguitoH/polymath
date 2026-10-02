"""create paper and chunk tables

Revision ID: 5b1e7c2a9d40
Revises: c24611b4e608
Create Date: 2026-10-02 03:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b1e7c2a9d40"
down_revision: str | Sequence[str] | None = "c24611b4e608"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per paper. Zotero keys arrive with Zotero ingestion; until then they are
    # NULL rather than invented.
    op.execute("""
        CREATE TABLE paper (
            id              uuid PRIMARY KEY,
            citekey         text NOT NULL UNIQUE,
            title           text NOT NULL CHECK (length(title) > 0),
            pdf_sha256      text NOT NULL CHECK (length(pdf_sha256) = 64),
            zotero_key      text UNIQUE,
            attachment_key  text,
            collections     text[] NOT NULL DEFAULT '{}',
            ingested_at     timestamptz NOT NULL DEFAULT now()
        )
    """)

    # Chunks are derived from the PDF: replaced when the PDF changes, never edited.
    op.execute("""
        CREATE TABLE chunk (
            id               uuid PRIMARY KEY,
            paper_id         uuid NOT NULL REFERENCES paper (id) ON DELETE CASCADE,
            ordinal          integer NOT NULL CHECK (ordinal >= 0),
            section          text[] NOT NULL,
            page_start       integer NOT NULL CHECK (page_start >= 1),
            page_end         integer NOT NULL CHECK (page_end >= page_start),
            page_label       text,
            content          text NOT NULL CHECK (length(content) > 0),
            embedding        vector(1024) NOT NULL,
            embedding_model  text NOT NULL,
            tsv              tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
            UNIQUE (paper_id, ordinal)
        )
    """)

    op.execute("CREATE INDEX chunk_embedding_idx ON chunk USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX chunk_tsv_idx ON chunk USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP TABLE chunk")
    op.execute("DROP TABLE paper")
