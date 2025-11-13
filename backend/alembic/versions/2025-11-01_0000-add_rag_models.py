"""add_rag_models_content_chunks_conversations_messages

Revision ID: e7f8a9b0c1d2
Revises: 3cec1d1491c3
Create Date: 2025-11-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = '3cec1d1491c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Upgrade database schema to add RAG models.
    
    Creates the following tables:
    1. content_chunks - Text chunks with embeddings for RAG
    2. conversations - User chat sessions
    3. messages - Individual messages in conversations
    4. message_chunks - Junction table linking messages to chunks
    
    Also creates necessary indexes for performance:
    - HNSW index for vector similarity search
    - GIN index for full-text search
    - B-tree indexes for foreign keys and queries
    """
    
    # ================================
    # Enable pgvector extension if not already enabled
    # ================================
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # ================================
    # Create content_chunks table
    # ================================
    op.create_table(
        'content_chunks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='Auto-incrementing primary key'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='Timestamp when record was created (UTC)'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, comment='Timestamp when record was last updated (UTC)'),
        sa.Column('content_item_id', sa.Integer(), nullable=False, comment='Foreign key to content_items table'),
        sa.Column('chunk_index', sa.Integer(), nullable=False, comment='Order of this chunk within the content item (0-indexed)'),
        sa.Column('chunk_text', sa.Text(), nullable=False, comment='The actual text content of this chunk'),
        sa.Column('chunk_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Content-type specific metadata (timestamps, section info, etc.)'),
        sa.Column('processing_status', sa.String(length=20), nullable=False, server_default='pending', comment='Processing status: pending, processing, processed, failed'),
        sa.ForeignKeyConstraint(['content_item_id'], ['content_items.id'], name=op.f('fk_content_chunks_content_item_id_content_items'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_content_chunks')),
        sa.UniqueConstraint('content_item_id', 'chunk_index', name='uq_content_item_chunk_index'),
        comment='Stores text chunks with embeddings for RAG'
    )
    
    # Add vector column for embeddings (768 dimensions for google/embeddinggemma-300m)
    op.execute('ALTER TABLE content_chunks ADD COLUMN embedding vector(768)')
    
    # Add tsvector column for full-text search
    op.execute('ALTER TABLE content_chunks ADD COLUMN text_search_vector tsvector')
    
    # Create indexes for content_chunks
    op.create_index('ix_content_chunks_content_item_id', 'content_chunks', ['content_item_id'])
    op.create_index('ix_content_chunks_processing_status', 'content_chunks', ['processing_status'])
    
    # Create HNSW index for vector similarity search (cosine distance)
    # HNSW (Hierarchical Navigable Small World) is better than IVFFlat for most cases
    # m=16 (max connections per layer), ef_construction=64 (quality during build)
    op.execute("""
        CREATE INDEX ix_content_chunks_embedding_hnsw 
        ON content_chunks 
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    
    # Create GIN index for full-text search
    op.execute("""
        CREATE INDEX ix_content_chunks_text_search 
        ON content_chunks 
        USING gin(text_search_vector)
    """)
    
    # Create trigger to automatically update text_search_vector
    op.execute("""
        CREATE OR REPLACE FUNCTION content_chunks_tsvector_update() RETURNS trigger AS $$
        BEGIN
            NEW.text_search_vector := to_tsvector('english', COALESCE(NEW.chunk_text, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)
    
    op.execute("""
        CREATE TRIGGER tsvector_update_content_chunks
        BEFORE INSERT OR UPDATE ON content_chunks
        FOR EACH ROW EXECUTE FUNCTION content_chunks_tsvector_update();
    """)
    
    # ================================
    # Create conversations table
    # ================================
    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='Auto-incrementing primary key'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='Timestamp when record was created (UTC)'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, comment='Timestamp when record was last updated (UTC)'),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='Foreign key to users table'),
        sa.Column('title', sa.String(length=255), nullable=False, server_default='New Conversation', comment='Conversation title (auto-generated or user-provided)'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='Whether conversation is currently active'),
        sa.Column('archived', sa.Boolean(), nullable=False, server_default='false', comment='Whether conversation is archived'),
        sa.Column('conversation_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Conversation-specific metadata (filters, settings, stats)'),
        sa.Column('message_count', sa.Integer(), nullable=False, server_default='0', comment='Total number of messages in conversation'),
        sa.Column('total_tokens_used', sa.Integer(), nullable=False, server_default='0', comment='Total tokens used in this conversation (for cost tracking)'),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True, comment='Timestamp of last message in conversation (UTC)'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversations_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations')),
        comment='Stores user chat sessions with the RAG system'
    )
    
    # Create indexes for conversations
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])
    op.create_index('ix_conversations_last_message_at', 'conversations', ['last_message_at'])
    op.create_index('ix_conversations_is_active', 'conversations', ['is_active'])
    
    # ================================
    # Create messages table
    # ================================
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='Auto-incrementing primary key'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='Timestamp when record was created (UTC)'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, comment='Timestamp when record was last updated (UTC)'),
        sa.Column('conversation_id', sa.Integer(), nullable=False, comment='Foreign key to conversations table'),
        sa.Column('role', sa.String(length=20), nullable=False, comment='Message role: user, assistant, or system'),
        sa.Column('content', sa.Text(), nullable=False, comment='Message text content'),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0', comment='Number of tokens in prompt (query + context)'),
        sa.Column('completion_tokens', sa.Integer(), nullable=False, server_default='0', comment='Number of tokens in completion (generated response)'),
        sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0', comment='Total tokens used (prompt + completion)'),
        sa.Column('message_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Message-specific metadata (model, temperature, filters, etc.)'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_messages')),
        comment='Stores individual messages in conversations'
    )
    
    # Create indexes for messages
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])
    op.create_index('ix_messages_role', 'messages', ['role'])
    op.create_index('ix_messages_created_at', 'messages', ['created_at'])
    
    # ================================
    # Create message_chunks junction table
    # ================================
    op.create_table(
        'message_chunks',
        sa.Column('message_id', sa.Integer(), nullable=False, comment='Foreign key to messages table'),
        sa.Column('chunk_id', sa.Integer(), nullable=False, comment='Foreign key to content_chunks table'),
        sa.Column('relevance_score', sa.Float(), nullable=True, comment='Relevance score from retrieval (0-1)'),
        sa.Column('rank', sa.Integer(), nullable=True, comment='Rank in retrieval results (1=most relevant)'),
        sa.ForeignKeyConstraint(['chunk_id'], ['content_chunks.id'], name=op.f('fk_message_chunks_chunk_id_content_chunks'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_message_chunks_message_id_messages'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('message_id', 'chunk_id', name=op.f('pk_message_chunks')),
        comment='Junction table linking messages to retrieved content chunks'
    )
    
    # Create indexes for message_chunks
    op.create_index('ix_message_chunks_message_id', 'message_chunks', ['message_id'])
    op.create_index('ix_message_chunks_chunk_id', 'message_chunks', ['chunk_id'])
    op.create_index('ix_message_chunks_relevance_score', 'message_chunks', ['relevance_score'])


def downgrade() -> None:
    """Downgrade database schema by removing RAG models."""
    
    # Drop tables in reverse order (handle foreign key dependencies)
    op.drop_table('message_chunks')
    op.drop_table('messages')
    op.drop_table('conversations')
    
    # Drop trigger and function for content_chunks
    op.execute('DROP TRIGGER IF EXISTS tsvector_update_content_chunks ON content_chunks')
    op.execute('DROP FUNCTION IF EXISTS content_chunks_tsvector_update()')
    
    op.drop_table('content_chunks')
    
    # Note: We don't drop the vector extension in downgrade
    # because other tables might be using it in production

