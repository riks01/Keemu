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
import pytest_asyncio
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

@pytest_asyncio.fixture
async def test_user(db_session):
    """Create a test user."""
    user = User(
        email="test@example.com",
        full_name="Test User",
        hashed_password="hashedpassword123"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_channel(db_session):
    """Create a test YouTube channel."""
    channel = Channel(
        name="Test Channel",
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="UC_test123",
        is_active=True
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return channel


@pytest_asyncio.fixture
async def test_content_item(db_session, test_channel):
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
    await db_session.commit()
    await db_session.refresh(content_item)
    return content_item


@pytest_asyncio.fixture
async def test_content_chunk(db_session, test_content_item):
    """Create a test content chunk."""
    chunk = ContentChunk(
        content_item_id=test_content_item.id,
        chunk_index=0,
        chunk_text="This is a test chunk with some content about testing.",
        chunk_metadata={"start_time": 0, "end_time": 30},
        processing_status=ProcessingStatus.PENDING
    )
    db_session.add(chunk)
    await db_session.commit()
    await db_session.refresh(chunk)
    return chunk


# ========================================
# Test process_content_item
# ========================================

@pytest.mark.asyncio
async def test_process_content_item_success(db_session, test_content_item):
    """Test successful processing of a content item."""
    with patch('app.tasks.embedding_tasks.ContentChunker') as mock_chunker_class, \
         patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder, \
         patch('app.tasks.embedding_tasks.get_content_item_by_id') as mock_get_content, \
         patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock get_content_item_by_id to return our test item
        mock_get_content.return_value = test_content_item
        
        # Mock the existing chunks check to return None (no existing chunks)
        mock_execute_result = Mock()
        mock_execute_result.scalar_one_or_none = Mock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
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
            np.random.rand(384),
            np.random.rand(384)
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
        
        # Verify the mocked session methods were called
        assert mock_session.add.called
        assert mock_session.commit.called


@pytest.mark.asyncio
async def test_process_content_item_not_found(db_session):
    """Test processing non-existent content item."""
    result = process_content_item(99999)
    
    assert result['success'] is False
    assert 'not found' in result['error'].lower()


@pytest.mark.asyncio
async def test_process_content_item_already_chunked(db_session, test_content_item, test_content_chunk):
    """Test processing content item that already has chunks."""
    with patch('app.tasks.embedding_tasks.get_content_item_by_id') as mock_get, \
         patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock get_content_item_by_id to return our test item
        mock_get.return_value = test_content_item
        
        # Mock the existing chunks check to return a chunk (chunks exist)
        mock_execute_result = Mock()
        mock_execute_result.scalar_one_or_none.return_value = test_content_chunk
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
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
    await db_session.commit()
    await db_session.refresh(content_item)
    
    # Mock the database access to return our test content_item
    with patch('app.tasks.embedding_tasks.get_content_item_by_id') as mock_get:
        mock_get.return_value = content_item
        
        # Mock the chunk check to return None (no existing chunks)
        with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session
            
            mock_result = Mock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute.return_value = mock_result
            
            result = process_content_item(content_item.id)
    
    assert result['success'] is False
    assert 'insufficient content' in result['error'].lower()


@pytest.mark.asyncio
async def test_process_content_item_no_chunks_created(db_session, test_content_item):
    """Test when chunker returns empty list."""
    with patch('app.tasks.embedding_tasks.ContentChunker') as mock_chunker_class, \
         patch('app.tasks.embedding_tasks.get_content_item_by_id') as mock_get, \
         patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock get_content_item_by_id
        mock_get.return_value = test_content_item
        
        # Mock no existing chunks
        mock_execute_result = Mock()
        mock_execute_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
        # Mock chunker to return empty list
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
    # Create mock chunks
    chunks = []
    for i in range(3):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"Chunk {i} text for testing",
            chunk_metadata={'index': i},
            processing_status=ProcessingStatus.PENDING
        )
        chunk.id = i + 1  # Mock ID
        chunks.append(chunk)
    
    with patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder, \
         patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return pending chunks
        mock_execute_result = Mock()
        mock_execute_result.scalars().all.return_value = chunks
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
        # Mock embedder
        mock_embedder = Mock()
        mock_embeddings = [np.random.rand(384) for _ in range(3)]
        mock_embedder.embed_texts_batch = AsyncMock(return_value=mock_embeddings)
        mock_get_embedder.return_value = mock_embedder
        
        result = batch_embed_pending(batch_size=10)
        
        assert result['success'] is True
        assert result['chunks_processed'] == 3
        assert result['chunks_failed'] == 0
        assert result['total_chunks'] == 3
        
        # Verify session methods were called
        assert mock_session.commit.called


@pytest.mark.asyncio
async def test_batch_embed_pending_no_chunks(db_session):
    """Test batch embedding when no pending chunks exist."""
    with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return empty list
        mock_execute_result = Mock()
        mock_execute_result.scalars().all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
        result = batch_embed_pending(batch_size=10)
    
    assert result['success'] is True
    assert result['chunks_processed'] == 0
    assert 'no pending chunks' in result['message'].lower()


@pytest.mark.asyncio
async def test_batch_embed_pending_with_failures(db_session, test_content_item):
    """Test batch embedding when some embeddings fail."""
    # Create mock chunks
    chunks = []
    for i in range(3):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"Chunk {i} text",
            chunk_metadata={},
            processing_status=ProcessingStatus.PENDING
        )
        chunk.id = i + 1
        chunks.append(chunk)
    
    with patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder, \
         patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return pending chunks
        mock_execute_result = Mock()
        mock_execute_result.scalars().all.return_value = chunks
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
        # Mock embedder
        mock_embedder = Mock()
        # Return mix of successful and failed embeddings
        mock_embeddings = [
            np.random.rand(384),
            None,  # Failed
            np.random.rand(384)
        ]
        mock_embedder.embed_texts_batch = AsyncMock(return_value=mock_embeddings)
        mock_get_embedder.return_value = mock_embedder
        
        result = batch_embed_pending(batch_size=10)
        
        assert result['success'] is True
        assert result['chunks_processed'] == 2
        assert result['chunks_failed'] == 1


# ========================================
# Test reprocess_failed_chunks
# ========================================

@pytest.mark.asyncio
async def test_reprocess_failed_chunks_success(db_session, test_content_item):
    """Test reprocessing of failed chunks."""
    # Create mock failed chunks
    chunks = []
    for i in range(2):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"Failed chunk {i}",
            chunk_metadata={},
            processing_status=ProcessingStatus.FAILED
        )
        chunk.id = i + 1
        chunks.append(chunk)
    
    with patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder, \
         patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return failed chunks
        mock_execute_result = Mock()
        mock_execute_result.scalars().all.return_value = chunks
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
        # Mock embedder
        mock_embedder = Mock()
        mock_embeddings = [np.random.rand(384) for _ in range(2)]
        mock_embedder.embed_texts_batch = AsyncMock(return_value=mock_embeddings)
        mock_get_embedder.return_value = mock_embedder
        
        result = reprocess_failed_chunks(limit=50)
        
        assert result['success'] is True
        assert result['chunks_reprocessed'] == 2
        assert result['chunks_fixed'] == 2
        assert result['chunks_still_failed'] == 0


@pytest.mark.asyncio
async def test_reprocess_failed_chunks_none_found(db_session):
    """Test reprocessing when no failed chunks exist."""
    with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return empty list
        mock_execute_result = Mock()
        mock_execute_result.scalars().all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
        result = reprocess_failed_chunks(limit=50)
    
    assert result['success'] is True
    assert result['chunks_reprocessed'] == 0
    assert 'no failed chunks' in result['message'].lower()


@pytest.mark.asyncio
async def test_reprocess_failed_chunks_still_failing(db_session, test_content_item):
    """Test reprocessing when some chunks still fail."""
    # Create mock failed chunks
    chunks = []
    for i in range(2):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"Failed chunk {i}",
            chunk_metadata={},
            processing_status=ProcessingStatus.FAILED
        )
        chunk.id = i + 1
        chunks.append(chunk)
    
    with patch('app.tasks.embedding_tasks.get_embedding_service') as mock_get_embedder, \
         patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return failed chunks
        mock_execute_result = Mock()
        mock_execute_result.scalars().all.return_value = chunks
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
        # Mock embedder
        mock_embedder = Mock()
        # One succeeds, one fails again
        mock_embeddings = [np.random.rand(384), None]
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
    # Create mock unprocessed content items
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
        content_item.id = i + 1
        content_items.append(content_item)
    
    with patch('app.tasks.embedding_tasks.process_content_item') as mock_task, \
         patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # First execute call returns content items, second returns scalars with empty list (no chunks)
        mock_content_result = Mock()
        mock_content_result.scalars().all.return_value = content_items
        
        mock_chunks_result = Mock()
        mock_chunks_result.scalars().all.return_value = []  # No existing chunks
        
        # Mock execute to return different results for different queries
        mock_session.execute = AsyncMock(side_effect=[mock_content_result] + [mock_chunks_result] * 3)
        
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
    with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return empty list
        mock_execute_result = Mock()
        mock_execute_result.scalars().all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
        result = process_all_unprocessed_content()
    
    assert result['success'] is True
    assert result['items_queued'] == 0
    assert 'no unprocessed content' in result['message'].lower()


@pytest.mark.asyncio
async def test_process_all_unprocessed_content_skip_insufficient(db_session, test_channel):
    """Test skipping content items with insufficient content."""
    # Create mock content with short body
    content_item = ContentItem(
        channel_id=test_channel.id,
        external_id="short_video",
        title="Short Video",
        content_body="Too short",
        author="Test Author",
        published_at=datetime.now(timezone.utc),
        processing_status=ProcessingStatus.PROCESSED
    )
    content_item.id = 1
    
    with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return content item
        mock_content_result = Mock()
        mock_content_result.scalars().all.return_value = [content_item]
        
        # Mock chunks query to return no chunks
        mock_chunks_result = Mock()
        mock_chunks_result.scalars().all.return_value = []
        
        mock_session.execute = AsyncMock(side_effect=[mock_content_result, mock_chunks_result])
        
        result = process_all_unprocessed_content()
    
    assert result['success'] is True
    assert result['items_queued'] == 0  # Skipped due to short content


@pytest.mark.asyncio
async def test_process_all_unprocessed_content_skip_with_chunks(db_session, test_content_item, test_content_chunk):
    """Test that content items with existing chunks are skipped."""
    with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # The query filters out items with chunks via subquery in WHERE clause
        # So items with existing chunks won't be in the result at all
        mock_content_result = Mock()
        mock_content_result.scalars().all.return_value = []  # Empty - filtered by subquery
        
        mock_session.execute = AsyncMock(return_value=mock_content_result)
        
        result = process_all_unprocessed_content()
    
    assert result['success'] is True
    assert result['items_queued'] == 0  # Already has chunks


# ========================================
# Test cleanup_orphaned_chunks
# ========================================

@pytest.mark.asyncio
async def test_cleanup_orphaned_chunks(db_session, test_content_item):
    """Test cleanup of orphaned chunks."""
    # Create mock orphaned chunk
    chunk = ContentChunk(
        content_item_id=999,  # Non-existent content item ID
        chunk_index=0,
        chunk_text="Test chunk",
        chunk_metadata={},
        processing_status=ProcessingStatus.PROCESSED
    )
    chunk.id = 1
    
    with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return orphaned chunk
        mock_execute_result = Mock()
        mock_execute_result.scalars().all.return_value = [chunk]
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
        result = cleanup_orphaned_chunks()
    
    assert result['success'] is True
    assert result['chunks_deleted'] == 1


@pytest.mark.asyncio
async def test_cleanup_orphaned_chunks_none_found(db_session):
    """Test cleanup when no orphaned chunks exist."""
    with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock query to return empty list
        mock_execute_result = Mock()
        mock_execute_result.scalars().all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_execute_result)
        
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
    with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock scalar queries
        mock_scalar = Mock()
        mock_scalar.scalar.return_value = 1
        
        # Mock the status_counts query which returns rows with .all()
        mock_status_counts = Mock()
        mock_status_counts.all.return_value = [
            (ProcessingStatus.PENDING, 1),
            (ProcessingStatus.PROCESSED, 1),
            (ProcessingStatus.FAILED, 1)
        ]
        
        # Mock the type_counts query
        mock_type_counts = Mock()
        mock_type_counts.all.return_value = []
        
        # Mock execute to return results for all queries in order
        mock_session.execute = AsyncMock(side_effect=[
            mock_scalar,  # total items
            mock_scalar,  # items with chunks  
            mock_status_counts,  # status counts
            mock_type_counts,  # type counts
            mock_scalar,  # total chunks
        ])
        
        result = get_processing_stats()
    
    assert 'content_items' in result
    assert 'chunks' in result
    
    assert result['content_items']['total'] >= 1
    assert result['content_items']['with_chunks'] >= 1
    
    assert result['chunks']['total'] >= 1


@pytest.mark.asyncio
async def test_get_processing_stats_empty_database(db_session):
    """Test stats with empty database."""
    with patch('app.tasks.embedding_tasks.AsyncSessionLocal') as mock_session_local:
        # Mock database session
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session_local.return_value = mock_session
        
        # Mock all count queries to return 0
        mock_count_result = Mock()
        mock_count_result.scalar.return_value = 0
        
        # Mock queries that return rows
        mock_empty_rows = Mock()
        mock_empty_rows.all.return_value = []
        
        mock_session.execute = AsyncMock(side_effect=[
            mock_count_result,  # total items
            mock_count_result,  # items with chunks
            mock_empty_rows,    # status counts
            mock_empty_rows,    # type counts
            mock_count_result,  # total chunks
        ])
        
        result = get_processing_stats()
    
    assert result['content_items']['total'] == 0
    assert result['content_items']['with_chunks'] == 0
    assert result['chunks']['total'] == 0

