"""
Tests for YouTube Celery tasks.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Channel, ContentItem, ProcessingStatus
from app.models.user import ContentSourceType
from app.tasks.youtube_tasks import (
    fetch_youtube_channel_content,
    process_youtube_video,
    fetch_all_active_channels,
    refresh_channel_metadata,
)


# ========================================
# Fixtures
# ========================================

@pytest.fixture
async def youtube_channel(db: AsyncSession, test_user):
    """Create a test YouTube channel."""
    channel = Channel(
        name="Test Channel",
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="UCtest123456789012345",
        description="Test description",
        thumbnail_url="https://example.com/thumb.jpg",
        is_active=True,
        last_fetched_at=None
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@pytest.fixture
async def content_item(db: AsyncSession, youtube_channel):
    """Create a test content item."""
    item = ContentItem(
        channel_id=youtube_channel.id,
        external_id="test_video_123",
        title="Test Video",
        content_body="",
        author=youtube_channel.name,
        published_at=datetime.now(timezone.utc),
        processing_status=ProcessingStatus.PENDING,
        content_metadata={"video_id": "test_video_123"}
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


# ========================================
# Test fetch_youtube_channel_content
# ========================================

@pytest.mark.asyncio
async def test_fetch_youtube_channel_content_success(db: AsyncSession, youtube_channel):
    """Test successful channel content fetch."""
    
    # Mock YouTube service
    mock_videos = [
        {
            'video_id': 'video_1',
            'title': 'Test Video 1',
            'published_at': '2024-01-15T10:00:00Z',
            'thumbnail_url': 'https://example.com/thumb1.jpg',
            'description': 'Test description 1'
        },
        {
            'video_id': 'video_2',
            'title': 'Test Video 2',
            'published_at': '2024-01-16T10:00:00Z',
            'thumbnail_url': 'https://example.com/thumb2.jpg',
            'description': 'Test description 2'
        }
    ]
    
    with patch('app.tasks.youtube_tasks.YouTubeService') as MockYouTube, \
         patch('app.tasks.youtube_tasks.process_youtube_video.apply_async') as mock_task:
        
        # Setup mocks
        mock_service = MockYouTube.return_value
        mock_service.get_channel_videos = AsyncMock(return_value=mock_videos)
        mock_task.return_value = MagicMock(id='task_123')
        
        # Run task
        result = fetch_youtube_channel_content(youtube_channel.id)
        
        # Assertions
        assert result['success'] is True
        assert result['channel_id'] == youtube_channel.id
        assert result['videos_found'] == 2
        assert result['new_videos'] == 2
        assert len(result['processing_tasks']) == 2
        
        # Verify content items were created
        items_result = await db.execute(
            select(ContentItem).where(ContentItem.channel_id == youtube_channel.id)
        )
        items = items_result.scalars().all()
        assert len(items) == 2
        assert items[0].processing_status == ProcessingStatus.PENDING
        
        # Verify channel.last_fetched_at was updated
        await db.refresh(youtube_channel)
        assert youtube_channel.last_fetched_at is not None


@pytest.mark.asyncio
async def test_fetch_youtube_channel_content_filters_existing(db: AsyncSession, youtube_channel):
    """Test that existing videos are not re-added."""
    
    # Create existing content item
    existing_item = ContentItem(
        channel_id=youtube_channel.id,
        external_id='video_1',
        title='Existing Video',
        content_body='',
        author=youtube_channel.name,
        published_at=datetime.now(timezone.utc),
        processing_status=ProcessingStatus.PROCESSED,
        content_metadata={}
    )
    db.add(existing_item)
    await db.commit()
    
    mock_videos = [
        {
            'video_id': 'video_1',  # Already exists
            'title': 'Test Video 1',
            'published_at': '2024-01-15T10:00:00Z'
        },
        {
            'video_id': 'video_2',  # New video
            'title': 'Test Video 2',
            'published_at': '2024-01-16T10:00:00Z'
        }
    ]
    
    with patch('app.tasks.youtube_tasks.YouTubeService') as MockYouTube, \
         patch('app.tasks.youtube_tasks.process_youtube_video.apply_async') as mock_task:
        
        mock_service = MockYouTube.return_value
        mock_service.get_channel_videos = AsyncMock(return_value=mock_videos)
        mock_task.return_value = MagicMock(id='task_123')
        
        result = fetch_youtube_channel_content(youtube_channel.id)
        
        # Only 1 new video should be processed
        assert result['videos_found'] == 2
        assert result['new_videos'] == 1
        assert len(result['processing_tasks']) == 1


@pytest.mark.asyncio
async def test_fetch_youtube_channel_content_channel_not_found(db: AsyncSession):
    """Test error handling when channel doesn't exist."""
    
    result = fetch_youtube_channel_content(99999)
    
    assert result['success'] is False
    assert 'not found' in result['error']


# ========================================
# Test process_youtube_video
# ========================================

@pytest.mark.asyncio
async def test_process_youtube_video_success(db: AsyncSession, content_item):
    """Test successful video processing."""
    
    mock_video_details = {
        'video_id': 'test_video_123',
        'duration_seconds': 600,
        'duration_formatted': '10:00',
        'view_count': 1000,
        'like_count': 50,
        'comment_count': 10,
        'thumbnail_url': 'https://example.com/thumb.jpg',
        'tags': ['test', 'video'],
        'definition': 'hd',
        'has_captions': True
    }
    
    mock_transcript = (
        "This is the transcript text.",
        {
            'language': 'en',
            'type': 'auto',
            'is_translatable': True
        }
    )
    
    with patch('app.tasks.youtube_tasks.YouTubeService') as MockYouTube, \
         patch('app.tasks.youtube_tasks.TranscriptService') as MockTranscript:
        
        # Setup mocks
        mock_yt = MockYouTube.return_value
        mock_yt.get_video_details = AsyncMock(return_value=mock_video_details)
        
        mock_ts = MockTranscript.return_value
        mock_ts.get_transcript = AsyncMock(return_value=mock_transcript)
        mock_ts.calculate_transcript_quality_score = MagicMock(return_value=0.95)
        
        # Run task
        result = process_youtube_video(content_item.id)
        
        # Assertions
        assert result['success'] is True
        assert result['content_item_id'] == content_item.id
        assert result['video_id'] == 'test_video_123'
        assert result['transcript_length'] == len(mock_transcript[0])
        
        # Verify content item was updated
        await db.refresh(content_item)
        assert content_item.processing_status == ProcessingStatus.PROCESSED
        assert content_item.content_body == mock_transcript[0]
        assert content_item.content_metadata['duration_seconds'] == 600
        assert content_item.content_metadata['transcript_language'] == 'en'
        assert content_item.error_message is None


@pytest.mark.asyncio
async def test_process_youtube_video_no_transcript(db: AsyncSession, content_item):
    """Test handling when transcript is not available."""
    
    mock_video_details = {
        'video_id': 'test_video_123',
        'duration_seconds': 600,
        'duration_formatted': '10:00',
        'view_count': 1000,
        'like_count': 50,
        'comment_count': 10,
        'thumbnail_url': 'https://example.com/thumb.jpg',
        'definition': 'hd',
        'has_captions': False
    }
    
    with patch('app.tasks.youtube_tasks.YouTubeService') as MockYouTube, \
         patch('app.tasks.youtube_tasks.TranscriptService') as MockTranscript:
        
        mock_yt = MockYouTube.return_value
        mock_yt.get_video_details = AsyncMock(return_value=mock_video_details)
        
        mock_ts = MockTranscript.return_value
        from app.services.transcript_service import NoTranscriptAvailable
        mock_ts.get_transcript = AsyncMock(
            side_effect=NoTranscriptAvailable("No transcript")
        )
        
        result = process_youtube_video(content_item.id)
        
        # Should mark as failed
        assert result['success'] is False
        assert 'transcript' in result['error'].lower()
        
        await db.refresh(content_item)
        assert content_item.processing_status == ProcessingStatus.FAILED
        assert 'transcript' in content_item.error_message.lower()


# ========================================
# Test fetch_all_active_channels
# ========================================

@pytest.mark.asyncio
async def test_fetch_all_active_channels(db: AsyncSession, youtube_channel):
    """Test periodic fetch of all active channels."""
    
    # Create another channel that was fetched recently (should be skipped)
    recent_channel = Channel(
        name="Recent Channel",
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="UCrecent123456789012",
        is_active=True,
        last_fetched_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )
    db.add(recent_channel)
    await db.commit()
    
    with patch('app.tasks.youtube_tasks.fetch_youtube_channel_content.apply_async') as mock_task:
        mock_task.return_value = MagicMock(id='task_123')
        
        result = fetch_all_active_channels()
        
        # Should find 2 channels, but only queue 1 (youtube_channel hasn't been fetched)
        assert result['success'] is True
        assert result['total_channels'] == 2
        assert result['channels_queued'] == 1
        assert len(result['task_ids']) == 1


# ========================================
# Test refresh_channel_metadata
# ========================================

@pytest.mark.asyncio
async def test_refresh_channel_metadata(db: AsyncSession, youtube_channel):
    """Test refreshing channel metadata from YouTube."""
    
    mock_channel_info = {
        'title': 'Updated Channel Name',
        'description': 'Updated description',
        'thumbnail_url': 'https://example.com/new_thumb.jpg',
        'subscriber_count': 10000
    }
    
    with patch('app.tasks.youtube_tasks.YouTubeService') as MockYouTube:
        mock_service = MockYouTube.return_value
        mock_service.get_channel_by_id = AsyncMock(return_value=mock_channel_info)
        
        result = refresh_channel_metadata(youtube_channel.id)
        
        assert result['success'] is True
        assert result['channel_id'] == youtube_channel.id
        
        # Verify channel was updated
        await db.refresh(youtube_channel)
        assert youtube_channel.name == 'Updated Channel Name'
        assert youtube_channel.description == 'Updated description'
        assert youtube_channel.thumbnail_url == 'https://example.com/new_thumb.jpg'


# ========================================
# Integration Test (requires running Celery)
# ========================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_celery_task_execution(pytestconfig, db: AsyncSession, youtube_channel):
    """
    Test actual Celery task execution.
    
    This test requires:
    - Running Celery worker
    - Valid YouTube API key
    
    Run with: pytest -m integration --run-integration
    """
    if not pytestconfig.getoption("--run-integration", default=False):
        pytest.skip("Integration tests disabled by default")
    
    # This would test real Celery task execution
    # For now, it's a placeholder
    pass

