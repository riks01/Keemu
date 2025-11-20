"""
Tests for RAG embedding Celery tasks.

This module tests:
- Content item processing (chunking + embedding)
- Batch embedding of pending chunks
- Reprocessing failed chunks
- Periodic task for unprocessed content
- Task monitoring and statistics
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timezone
import numpy as np

from app.models.content import ContentItem, ContentChunk, ProcessingStatus, Channel, ContentSourceType
from app.models.user import User
from app.tasks.embedding_tasks import (
    process_content_item,
    batch_embed_pending,
    reprocess_failed_chunks,
    process_all_unprocessed_content,
    cleanup_orphaned_chunks,
    get_processing_stats
)


# ========================================
# Fixtures
# ========================================

@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user = User(
        email="test@example.com",
        full_name="Test User",
        hashed_password="hashedpassword123"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_channel(db_session):
    """Create a test YouTube channel."""
    channel = Channel(
        name="Test Channel",
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="UC_test123",
        is_active=True
    )
    db_session.add(channel)
    db_session.commit()
    db_session.refresh(channel)
    return channel


@pytest.fixture
def test_content_item(db_session, test_channel):
    """Create a test content item with processed status."""
    content_item = ContentItem(
        channel_id=test_channel.id,
        external_id="test_video_123",
        title="Test Video: Introduction to Testing",
        content_body="This is a test video about testing. " * 50,  # Make it long enough
        author="Test Author",
        published_at=datetime.now(timezone.utc),
        processing_status=ProcessingStatus.PROCESSED,
        content_metadata={
            "video_id": "test_video_123",
            "duration_seconds": 600,
            "view_count": 1000
        }
    )
    db_session.add(content_item)
    db_session.commit()
    db_session.refresh(content_item)
    return content_item


@pytest.fixture
def test_content_chunk(db_session, test_content_item):
    """Create a test content chunk."""
    chunk = ContentChunk(
        content_item_id=test_content_item.id,
        chunk_index=0,
        chunk_text="This is a test chunk with some content about testing.",
        chunk_metadata={"start_time": 0, "end_time": 30},
        processing_status=ProcessingStatus.PENDING
    )
    db_session.add(chunk)
    db_session.commit()
    db_session.refresh(chunk)
    return chunk


# ========================================
# Test process_content_item
# ========================================

@pytest.mark.asyncio
async def test_process_content_item_success(db_session, test_content_item):
    """Test successful processing of a content item."""
    with patch('app.tasks.embedding_tasks.ContentChunker') as mock_chunker_class, \
         patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder:
        
        # Mock chunker
        mock_chunker = Mock()
        mock_chunker_class.return_value = mock_chunker
        
        # Mock chunks
        mock_chunks = [
            {
                'index': 0,
                'text': 'Chunk 0 text',
                'metadata': {'start_time': 0}
            },
            {
                'index': 1,
                'text': 'Chunk 1 text',
                'metadata': {'start_time': 30}
            }
        ]
        mock_chunker.chunk_content = AsyncMock(return_value=mock_chunks)
        
        # Mock embedder
        mock_embedder = Mock()
        mock_embeddings = [
            np.random.rand(768),
            np.random.rand(768)
        ]
        mock_embedder.embed_texts_batch = AsyncMock(return_value=mock_embeddings)
        mock_get_embedder.return_value = mock_embedder
        
        # Run task
        result = process_content_item(test_content_item.id)
        
        # Assertions
        assert result['success'] is True
        assert result['content_item_id'] == test_content_item.id
        assert result['chunks_created'] == 2
        assert result['chunks_embedded'] == 2
        assert 'processing_time_seconds' in result
        
        # Verify chunks were created in database
        db_session.expire_all()
        chunks = db_session.query(ContentChunk).filter_by(
            content_item_id=test_content_item.id
        ).all()
        assert len(chunks) == 2
        assert chunks[0].processing_status == ProcessingStatus.PROCESSED
        assert chunks[0].embedding is not None


@pytest.mark.asyncio
async def test_process_content_item_not_found(db_session):
    """Test processing non-existent content item."""
    result = process_content_item(99999)
    
    assert result['success'] is False
    assert 'not found' in result['error'].lower()


@pytest.mark.asyncio
async def test_process_content_item_already_chunked(db_session, test_content_item, test_content_chunk):
    """Test processing content item that already has chunks."""
    result = process_content_item(test_content_item.id)
    
    assert result['success'] is True
    assert result.get('skipped') is True
    assert 'already chunked' in result['message'].lower()


@pytest.mark.asyncio
async def test_process_content_item_insufficient_content(db_session, test_channel):
    """Test processing content item with insufficient content body."""
    # Create content with short body
    content_item = ContentItem(
        channel_id=test_channel.id,
        external_id="short_video",
        title="Short Video",
        content_body="Too short",  # < 100 chars
        author="Test Author",
        published_at=datetime.now(timezone.utc),
        processing_status=ProcessingStatus.PROCESSED
    )
    db_session.add(content_item)
    db_session.commit()
    db_session.refresh(content_item)
    
    result = process_content_item(content_item.id)
    
    assert result['success'] is False
    assert 'insufficient content' in result['error'].lower()


@pytest.mark.asyncio
async def test_process_content_item_no_chunks_created(db_session, test_content_item):
    """Test when chunker returns empty list."""
    with patch('app.tasks.embedding_tasks.ContentChunker') as mock_chunker_class:
        mock_chunker = Mock()
        mock_chunker_class.return_value = mock_chunker
        mock_chunker.chunk_content = AsyncMock(return_value=[])
        
        result = process_content_item(test_content_item.id)
        
        assert result['success'] is False
        assert 'no chunks created' in result['error'].lower()


# ========================================
# Test batch_embed_pending
# ========================================

@pytest.mark.asyncio
async def test_batch_embed_pending_success(db_session, test_content_item):
    """Test batch embedding of pending chunks."""
    # Create pending chunks
    chunks = []
    for i in range(3):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"Chunk {i} text for testing",
            chunk_metadata={'index': i},
            processing_status=ProcessingStatus.PENDING
        )
        db_session.add(chunk)
        chunks.append(chunk)
    
    db_session.commit()
    
    with patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder:
        mock_embedder = Mock()
        mock_embeddings = [np.random.rand(768) for _ in range(3)]
        mock_embedder.embed_texts_batch = AsyncMock(return_value=mock_embeddings)
        mock_get_embedder.return_value = mock_embedder
        
        result = batch_embed_pending(batch_size=10)
        
        assert result['success'] is True
        assert result['chunks_processed'] == 3
        assert result['chunks_failed'] == 0
        assert result['total_chunks'] == 3
        
        # Verify chunks were updated
        db_session.expire_all()
        for chunk in chunks:
            db_session.refresh(chunk)
            assert chunk.processing_status == ProcessingStatus.PROCESSED
            assert chunk.embedding is not None


@pytest.mark.asyncio
async def test_batch_embed_pending_no_chunks(db_session):
    """Test batch embedding when no pending chunks exist."""
    result = batch_embed_pending(batch_size=10)
    
    assert result['success'] is True
    assert result['chunks_processed'] == 0
    assert 'no pending chunks' in result['message'].lower()


@pytest.mark.asyncio
async def test_batch_embed_pending_with_failures(db_session, test_content_item):
    """Test batch embedding when some embeddings fail."""
    # Create pending chunks
    chunks = []
    for i in range(3):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"Chunk {i} text",
            chunk_metadata={},
            processing_status=ProcessingStatus.PENDING
        )
        db_session.add(chunk)
        chunks.append(chunk)
    
    db_session.commit()
    
    with patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder:
        mock_embedder = Mock()
        # Return mix of successful and failed embeddings
        mock_embeddings = [
            np.random.rand(768),
            None,  # Failed
            np.random.rand(768)
        ]
        mock_embedder.embed_texts_batch = AsyncMock(return_value=mock_embeddings)
        mock_get_embedder.return_value = mock_embedder
        
        result = batch_embed_pending(batch_size=10)
        
        assert result['success'] is True
        assert result['chunks_processed'] == 2
        assert result['chunks_failed'] == 1
        
        # Verify statuses
        db_session.expire_all()
        statuses = []
        for chunk in chunks:
            db_session.refresh(chunk)
            statuses.append(chunk.processing_status)
        
        assert statuses.count(ProcessingStatus.PROCESSED) == 2
        assert statuses.count(ProcessingStatus.FAILED) == 1


# ========================================
# Test reprocess_failed_chunks
# ========================================

@pytest.mark.asyncio
async def test_reprocess_failed_chunks_success(db_session, test_content_item):
    """Test reprocessing of failed chunks."""
    # Create failed chunks
    chunks = []
    for i in range(2):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"Failed chunk {i}",
            chunk_metadata={},
            processing_status=ProcessingStatus.FAILED
        )
        db_session.add(chunk)
        chunks.append(chunk)
    
    db_session.commit()
    
    with patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder:
        mock_embedder = Mock()
        mock_embeddings = [np.random.rand(768) for _ in range(2)]
        mock_embedder.embed_texts_batch = AsyncMock(return_value=mock_embeddings)
        mock_get_embedder.return_value = mock_embedder
        
        result = reprocess_failed_chunks(limit=50)
        
        assert result['success'] is True
        assert result['chunks_reprocessed'] == 2
        assert result['chunks_fixed'] == 2
        assert result['chunks_still_failed'] == 0
        
        # Verify chunks are now processed
        db_session.expire_all()
        for chunk in chunks:
            db_session.refresh(chunk)
            assert chunk.processing_status == ProcessingStatus.PROCESSED
            assert chunk.embedding is not None


@pytest.mark.asyncio
async def test_reprocess_failed_chunks_none_found(db_session):
    """Test reprocessing when no failed chunks exist."""
    result = reprocess_failed_chunks(limit=50)
    
    assert result['success'] is True
    assert result['chunks_reprocessed'] == 0
    assert 'no failed chunks' in result['message'].lower()


@pytest.mark.asyncio
async def test_reprocess_failed_chunks_still_failing(db_session, test_content_item):
    """Test reprocessing when some chunks still fail."""
    # Create failed chunks
    chunks = []
    for i in range(2):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"Failed chunk {i}",
            chunk_metadata={},
            processing_status=ProcessingStatus.FAILED
        )
        db_session.add(chunk)
        chunks.append(chunk)
    
    db_session.commit()
    
    with patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder:
        mock_embedder = Mock()
        # One succeeds, one fails again
        mock_embeddings = [np.random.rand(768), None]
        mock_embedder.embed_texts_batch = AsyncMock(return_value=mock_embeddings)
        mock_get_embedder.return_value = mock_embedder
        
        result = reprocess_failed_chunks(limit=50)
        
        assert result['success'] is True
        assert result['chunks_fixed'] == 1
        assert result['chunks_still_failed'] == 1


# ========================================
# Test process_all_unprocessed_content
# ========================================

@pytest.mark.asyncio
async def test_process_all_unprocessed_content_success(db_session, test_channel):
    """Test processing all unprocessed content items."""
    # Create unprocessed content items (no chunks)
    content_items = []
    for i in range(3):
        content_item = ContentItem(
            channel_id=test_channel.id,
            external_id=f"video_{i}",
            title=f"Video {i}",
            content_body="This is test content. " * 20,  # Long enough
            author="Test Author",
            published_at=datetime.now(timezone.utc),
            processing_status=ProcessingStatus.PROCESSED
        )
        db_session.add(content_item)
        content_items.append(content_item)
    
    db_session.commit()
    
    with patch('app.tasks.embedding_tasks.process_content_item') as mock_task:
        # Mock the apply_async method
        mock_async_result = Mock()
        mock_async_result.id = "mock-task-id"
        mock_task.apply_async.return_value = mock_async_result
        
        result = process_all_unprocessed_content()
        
        assert result['success'] is True
        assert result['total_items'] == 3
        assert result['items_queued'] == 3
        assert len(result['task_ids']) == 3
        
        # Verify tasks were queued
        assert mock_task.apply_async.call_count == 3


@pytest.mark.asyncio
async def test_process_all_unprocessed_content_none_found(db_session):
    """Test when no unprocessed content exists."""
    result = process_all_unprocessed_content()
    
    assert result['success'] is True
    assert result['items_queued'] == 0
    assert 'no unprocessed content' in result['message'].lower()


@pytest.mark.asyncio
async def test_process_all_unprocessed_content_skip_insufficient(db_session, test_channel):
    """Test skipping content items with insufficient content."""
    # Create content with short body
    content_item = ContentItem(
        channel_id=test_channel.id,
        external_id="short_video",
        title="Short Video",
        content_body="Too short",
        author="Test Author",
        published_at=datetime.now(timezone.utc),
        processing_status=ProcessingStatus.PROCESSED
    )
    db_session.add(content_item)
    db_session.commit()
    
    result = process_all_unprocessed_content()
    
    assert result['success'] is True
    assert result['items_queued'] == 0  # Skipped due to short content


@pytest.mark.asyncio
async def test_process_all_unprocessed_content_skip_with_chunks(db_session, test_content_item, test_content_chunk):
    """Test that content items with existing chunks are skipped."""
    result = process_all_unprocessed_content()
    
    assert result['success'] is True
    assert result['items_queued'] == 0  # Already has chunks


# ========================================
# Test cleanup_orphaned_chunks
# ========================================

@pytest.mark.asyncio
async def test_cleanup_orphaned_chunks(db_session, test_content_item):
    """Test cleanup of orphaned chunks."""
    # Create chunk
    chunk = ContentChunk(
        content_item_id=test_content_item.id,
        chunk_index=0,
        chunk_text="Test chunk",
        chunk_metadata={},
        processing_status=ProcessingStatus.PROCESSED
    )
    db_session.add(chunk)
    db_session.commit()
    chunk_id = chunk.id
    
    # Delete content item to create orphan
    db_session.delete(test_content_item)
    db_session.commit()
    
    result = cleanup_orphaned_chunks()
    
    assert result['success'] is True
    assert result['chunks_deleted'] == 1
    
    # Verify chunk was deleted
    orphaned = db_session.query(ContentChunk).filter_by(id=chunk_id).first()
    assert orphaned is None


@pytest.mark.asyncio
async def test_cleanup_orphaned_chunks_none_found(db_session):
    """Test cleanup when no orphaned chunks exist."""
    result = cleanup_orphaned_chunks()
    
    assert result['success'] is True
    assert result['chunks_deleted'] == 0
    assert 'no orphaned chunks' in result['message'].lower()


# ========================================
# Test get_processing_stats
# ========================================

@pytest.mark.asyncio
async def test_get_processing_stats(db_session, test_content_item):
    """Test getting processing statistics."""
    # Create chunks with different statuses
    for i, status in enumerate([ProcessingStatus.PENDING, ProcessingStatus.PROCESSED, ProcessingStatus.FAILED]):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"Chunk {i}",
            chunk_metadata={},
            processing_status=status
        )
        db_session.add(chunk)
    
    db_session.commit()
    
    result = get_processing_stats()
    
    assert 'content_items' in result
    assert 'chunks' in result
    
    assert result['content_items']['total'] >= 1
    assert result['content_items']['with_chunks'] >= 1
    
    assert result['chunks']['total'] == 3
    assert result['chunks']['pending'] == 1
    assert result['chunks']['processed'] == 1
    assert result['chunks']['failed'] == 1


@pytest.mark.asyncio
async def test_get_processing_stats_empty_database(db_session):
    """Test stats with empty database."""
    result = get_processing_stats()
    
    assert result['content_items']['total'] == 0
    assert result['content_items']['with_chunks'] == 0
    assert result['chunks']['total'] == 0

