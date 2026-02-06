"""update_vector_dimension_to_384

Revision ID: a1b2c3d4e5f6
Revises: e7f8a9b0c1d2
Create Date: 2025-11-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Update embedding vector dimension from 768 to 384.
    
    This migration:
    1. Drops the HNSW index on the old vector column
    2. Drops the old embedding column (vector(768))
    3. Creates a new embedding column (vector(384))
    4. Recreates the HNSW index on the new vector column
    
    WARNING: This will delete all existing embeddings!
    After running this migration, you need to regenerate embeddings
    for all content chunks using the new model.
    """
    
    # Drop the HNSW index first (can't alter column with index)
    op.execute('DROP INDEX IF EXISTS ix_content_chunks_embedding_hnsw')
    
    # Drop the old embedding column
    op.execute('ALTER TABLE content_chunks DROP COLUMN IF EXISTS embedding')
    
    # Add new embedding column with 384 dimensions
    op.execute('ALTER TABLE content_chunks ADD COLUMN embedding vector(384)')
    
    # Recreate HNSW index for the new vector dimension
    # HNSW (Hierarchical Navigable Small World) for fast similarity search
    # m=16 (max connections per layer), ef_construction=64 (quality during build)
    op.execute("""
        CREATE INDEX ix_content_chunks_embedding_hnsw 
        ON content_chunks 
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    
    # Reset processing status for all chunks so they can be re-embedded
    op.execute("""
        UPDATE content_chunks 
        SET processing_status = 'pending' 
        WHERE processing_status = 'processed'
    """)


def downgrade() -> None:
    """
    Downgrade back to 768-dimensional vectors.
    
    WARNING: This will also delete all existing embeddings!
    """
    
    # Drop the HNSW index
    op.execute('DROP INDEX IF EXISTS ix_content_chunks_embedding_hnsw')
    
    # Drop the current embedding column
    op.execute('ALTER TABLE content_chunks DROP COLUMN IF EXISTS embedding')
    
    # Add embedding column with 768 dimensions (old size)
    op.execute('ALTER TABLE content_chunks ADD COLUMN embedding vector(768)')
    
    # Recreate HNSW index for 768 dimensions
    op.execute("""
        CREATE INDEX ix_content_chunks_embedding_hnsw 
        ON content_chunks 
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    
    # Reset processing status for all chunks
    op.execute("""
        UPDATE content_chunks 
        SET processing_status = 'pending' 
        WHERE processing_status = 'processed'
    """)

