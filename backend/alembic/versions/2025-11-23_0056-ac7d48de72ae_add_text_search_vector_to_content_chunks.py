"""add_text_search_vector_to_content_chunks

Revision ID: ac7d48de72ae
Revises: a1b2c3d4e5f6
Create Date: 2025-11-23 00:56:13.440944+00:00

Adds text_search_vector column for full-text search capabilities.
This complements the semantic search (embedding) with keyword-based search.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR


# revision identifiers, used by Alembic.
revision = 'ac7d48de72ae'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add text_search_vector column and GIN index for full-text search."""
    # Add the tsvector column
    op.add_column(
        'content_chunks',
        sa.Column(
            'text_search_vector',
            TSVECTOR,
            nullable=True,
            comment='Full-text search vector for keyword/lexical search'
        )
    )
    
    # Create GIN index for fast full-text search
    # GIN (Generalized Inverted Index) is optimal for tsvector columns
    op.execute("""
        CREATE INDEX ix_content_chunks_text_search_vector_gin
        ON content_chunks
        USING gin(text_search_vector)
    """)
    
    # Optional: Populate existing chunks with tsvector
    # This uses English text search configuration
    # Note: You can change 'english' to other languages as needed
    op.execute("""
        UPDATE content_chunks
        SET text_search_vector = to_tsvector('english', chunk_text)
        WHERE text_search_vector IS NULL
    """)


def downgrade() -> None:
    """Remove text_search_vector column and its index."""
    # Drop the GIN index first
    op.execute("DROP INDEX IF EXISTS ix_content_chunks_text_search_vector_gin")
    
    # Drop the column
    op.drop_column('content_chunks', 'text_search_vector')
