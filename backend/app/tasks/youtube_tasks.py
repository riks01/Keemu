"""
Celery tasks for YouTube content fetching and processing.

This module contains background tasks for:
- Fetching videos from YouTube channels
- Processing video transcripts
- Scheduled periodic fetching
- Channel metadata updates
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import nest_asyncio
from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.content import Channel, ContentItem, ProcessingStatus
from app.models.user import ContentSourceType
from app.services.youtube import (
    YouTubeService,
    YouTubeAPIError,
    YouTubeQuotaExceededError,
)
from app.services.transcript_service import (
    TranscriptService,
    NoTranscriptAvailable,
    TranscriptError,
)
from app.workers.celery_app import celery_app

# Apply nest_asyncio to allow nested event loops in Celery workers
nest_asyncio.apply()

logger = logging.getLogger(__name__)


# ========================================
# Helper Functions
# ========================================

def run_async(coro):
    """
    Run async coroutine in Celery task context.
    
    Uses asyncio.run() with nest_asyncio applied at module level
    to handle potential nested event loop scenarios.
    """
    return asyncio.run(coro)


async def get_channel_by_id(db: AsyncSession, channel_id: int) -> Optional[Channel]:
    """Get channel by database ID."""
    result = await db.execute(
        select(Channel).where(Channel.id == channel_id)
    )
    return result.scalar_one_or_none()


async def content_item_exists(
    db: AsyncSession,
    channel_id: int,
    external_id: str
) -> bool:
    """Check if content item already exists."""
    result = await db.execute(
        select(ContentItem).where(
            ContentItem.channel_id == channel_id,
            ContentItem.external_id == external_id
        )
    )
    return result.scalar_one_or_none() is not None


# ========================================
# Base Task Class
# ========================================

class YouTubeTask(Task):
    """Base task class with retry logic and error handling."""
    
    autoretry_for = (YouTubeAPIError,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes
    retry_jitter = True


# ========================================
# Main Tasks
# ========================================

@celery_app.task(
    base=YouTubeTask,
    name='youtube.fetch_channel_content',
    bind=True,
    max_retries=3
)
def fetch_youtube_channel_content(self, channel_id: int) -> dict:
    """
    Fetch latest videos from a YouTube channel.
    
    This task:
    1. Gets the channel from database
    2. Fetches latest videos from YouTube
    3. Filters out videos we already have
    4. Creates ContentItem records with status=PENDING
    5. Queues process_youtube_video tasks for each new video
    6. Updates channel.last_fetched_at
    
    Args:
        channel_id: Database ID of the channel
        
    Returns:
        Dictionary with task results:
        {
            'channel_id': int,
            'channel_name': str,
            'videos_found': int,
            'new_videos': int,
            'processing_tasks': List[str]  # Task IDs
        }
    """
    import asyncio
    
    async def _fetch_content():
        async with AsyncSessionLocal() as db:
            try:
                # Get channel
                channel = await get_channel_by_id(db, channel_id)
                if not channel:
                    logger.error(f"Channel {channel_id} not found")
                    return {
                        'error': f'Channel {channel_id} not found',
                        'success': False
                    }
                
                if channel.source_type != ContentSourceType.YOUTUBE:
                    logger.error(f"Channel {channel_id} is not a YouTube channel")
                    return {
                        'error': 'Not a YouTube channel',
                        'success': False
                    }
                
                logger.info(f"Fetching content for channel: {channel.name} ({channel.source_identifier})")
                
                # Initialize YouTube service
                youtube = YouTubeService()
                
                # Determine cutoff date for fetching videos
                # Only fetch videos published after last fetch or last 30 days
                if channel.last_fetched_at:
                    published_after = channel.last_fetched_at
                else:
                    # First fetch: get last 30 days
                    published_after = datetime.now(timezone.utc) - timedelta(days=30)
                
                # Fetch videos
                try:
                    videos = await youtube.get_channel_videos(
                        channel_id=channel.source_identifier,
                        max_results=settings.YOUTUBE_MAX_VIDEOS_PER_FETCH,
                        published_after=published_after
                    )
                except YouTubeQuotaExceededError:
                    logger.error("YouTube API quota exceeded")
                    raise  # Will trigger retry
                except YouTubeAPIError as e:
                    logger.error(f"YouTube API error: {e}")
                    raise  # Will trigger retry
                
                logger.info(f"Found {len(videos)} videos from {channel.name}")
                
                # Filter out videos we already have
                new_videos = []
                for video in videos:
                    video_id = video['video_id']
                    
                    # Check if already exists
                    if await content_item_exists(db, channel.id, video_id):
                        logger.debug(f"Video {video_id} already exists, skipping")
                        continue
                    
                    new_videos.append(video)
                
                logger.info(f"Found {len(new_videos)} new videos to process")
                
                # Create ContentItem records for new videos
                processing_task_ids = []
                for video in new_videos:
                    # Create ContentItem with PENDING status
                    content_item = ContentItem(
                        channel_id=channel.id,
                        external_id=video['video_id'],
                        title=video['title'],
                        content_body="",  # Will be filled by process_youtube_video
                        author=channel.name,
                        published_at=datetime.fromisoformat(
                            video['published_at'].replace('Z', '+00:00')
                        ),
                        processing_status=ProcessingStatus.PENDING,
                        content_metadata={
                            'video_id': video['video_id'],
                            'thumbnail_url': video.get('thumbnail_url'),
                            'description': video.get('description', '')[:500],  # First 500 chars
                        }
                    )
                    
                    db.add(content_item)
                    await db.flush()  # Get content_item.id
                    
                    # Queue processing task
                    task = process_youtube_video.apply_async(
                        args=[content_item.id],
                        countdown=5  # Wait 5 seconds before processing
                    )
                    processing_task_ids.append(task.id)
                    
                    logger.info(f"Queued processing for video: {video['title']} (task: {task.id})")
                
                # Update channel's last_fetched_at
                channel.last_fetched_at = datetime.now(timezone.utc)
                
                await db.commit()
                
                result = {
                    'success': True,
                    'channel_id': channel.id,
                    'channel_name': channel.name,
                    'videos_found': len(videos),
                    'new_videos': len(new_videos),
                    'processing_tasks': processing_task_ids,
                    'last_fetched_at': channel.last_fetched_at.isoformat()
                }
                
                logger.info(
                    f"Successfully fetched content for {channel.name}: "
                    f"{len(new_videos)} new videos queued for processing"
                )
                
                return result
                
            except Exception as e:
                logger.error(f"Error fetching channel content: {e}", exc_info=True)
                await db.rollback()
                raise
    
    # Run async function
    return run_async(_fetch_content())


@celery_app.task(
    base=YouTubeTask,
    name='youtube.process_video',
    bind=True,
    max_retries=3
)
def process_youtube_video(self, content_item_id: int) -> dict:
    """
    Process a YouTube video: fetch details and transcript.
    
    This task:
    1. Gets ContentItem from database
    2. Fetches video details from YouTube
    3. Extracts transcript
    4. Cleans transcript text
    5. Updates ContentItem with full data
    6. Sets status to PROCESSED or FAILED
    
    Args:
        content_item_id: Database ID of the ContentItem
        
    Returns:
        Dictionary with processing results
    """
    import asyncio
    
    async def _process_video():
        async with AsyncSessionLocal() as db:
            try:
                # Get content item
                result = await db.execute(
                    select(ContentItem).where(ContentItem.id == content_item_id)
                )
                content_item = result.scalar_one_or_none()
                
                if not content_item:
                    logger.error(f"ContentItem {content_item_id} not found")
                    return {
                        'error': f'ContentItem {content_item_id} not found',
                        'success': False
                    }
                
                # Update status to PROCESSING
                content_item.processing_status = ProcessingStatus.PROCESSING
                await db.commit()
                
                logger.info(f"Processing video: {content_item.title} ({content_item.external_id})")
                
                # Initialize services
                youtube = YouTubeService()
                transcript_service = TranscriptService()
                
                # Fetch video details
                try:
                    video_details = await youtube.get_video_details(content_item.external_id)
                except YouTubeAPIError as e:
                    logger.error(f"Failed to get video details: {e}")
                    content_item.processing_status = ProcessingStatus.FAILED
                    content_item.error_message = f"YouTube API error: {str(e)}"
                    await db.commit()
                    raise
                
                # Extract transcript
                transcript_text = ""
                transcript_metadata = {}
                
                try:
                    transcript_text, transcript_metadata = await transcript_service.get_transcript(
                        content_item.external_id
                    )
                    logger.info(
                        f"Got transcript for {content_item.external_id}: "
                        f"{len(transcript_text)} chars in {transcript_metadata['language']}"
                    )
                except NoTranscriptAvailable as e:
                    logger.warning(f"No transcript available for {content_item.external_id}: {e}")
                    content_item.processing_status = ProcessingStatus.FAILED
                    content_item.error_message = "No transcript available"
                    await db.commit()
                    return {
                        'success': False,
                        'content_item_id': content_item_id,
                        'error': 'No transcript available'
                    }
                except TranscriptError as e:
                    logger.error(f"Transcript error for {content_item.external_id}: {e}")
                    content_item.processing_status = ProcessingStatus.FAILED
                    content_item.error_message = f"Transcript error: {str(e)}"
                    await db.commit()
                    raise
                
                # Update content item with full data
                content_item.content_body = transcript_text
                content_item.content_metadata = {
                    **content_item.content_metadata,  # Keep existing metadata
                    'video_id': video_details['video_id'],
                    'duration_seconds': video_details['duration_seconds'],
                    'duration_formatted': video_details['duration_formatted'],
                    'view_count': video_details['view_count'],
                    'like_count': video_details['like_count'],
                    'comment_count': video_details['comment_count'],
                    'thumbnail_url': video_details['thumbnail_url'],
                    'tags': video_details.get('tags', []),
                    'category_id': video_details.get('category_id'),
                    'definition': video_details['definition'],
                    'has_captions': video_details['has_captions'],
                    'transcript_language': transcript_metadata['language'],
                    'transcript_type': transcript_metadata['type'],
                    'transcript_quality': transcript_service.calculate_transcript_quality_score(
                        transcript_metadata
                    ),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                # Mark as processed
                content_item.processing_status = ProcessingStatus.PROCESSED
                content_item.error_message = None
                
                await db.commit()
                
                logger.info(f"Successfully processed video: {content_item.title}")
                
                return {
                    'success': True,
                    'content_item_id': content_item_id,
                    'video_id': content_item.external_id,
                    'title': content_item.title,
                    'transcript_length': len(transcript_text),
                    'transcript_language': transcript_metadata['language'],
                    'transcript_type': transcript_metadata['type'],
                }
                
            except Exception as e:
                logger.error(f"Error processing video: {e}", exc_info=True)
                
                # Mark as failed
                try:
                    content_item.processing_status = ProcessingStatus.FAILED
                    content_item.error_message = str(e)[:500]  # Truncate error message
                    await db.commit()
                except:
                    await db.rollback()
                
                raise
    
    # Run async function
    return run_async(_process_video())


@celery_app.task(
    name='youtube.fetch_all_active_channels',
    bind=True
)
def fetch_all_active_channels(self) -> dict:
    """
    Periodic task to fetch content from all active YouTube channels.
    
    This task:
    1. Queries all active YouTube channels
    2. Filters channels that need updating (last_fetched_at > 6 hours ago)
    3. Queues fetch_youtube_channel_content task for each channel
    
    Scheduled to run every hour via Celery Beat.
    
    Returns:
        Dictionary with task results
    """
    import asyncio
    
    async def _fetch_all():
        async with AsyncSessionLocal() as db:
            try:
                # Get all active YouTube channels
                result = await db.execute(
                    select(Channel).where(
                        Channel.source_type == ContentSourceType.YOUTUBE,
                        Channel.is_active == True
                    )
                )
                channels = result.scalars().all()
                
                logger.info(f"Found {len(channels)} active YouTube channels")
                
                # Filter channels that need updating
                cutoff_time = datetime.now(timezone.utc) - timedelta(
                    hours=settings.YOUTUBE_CHECK_INTERVAL_HOURS
                )
                
                channels_to_fetch = []
                for channel in channels:
                    if channel.last_fetched_at is None or channel.last_fetched_at < cutoff_time:
                        channels_to_fetch.append(channel)
                
                logger.info(
                    f"{len(channels_to_fetch)} channels need updating "
                    f"(last fetched > {settings.YOUTUBE_CHECK_INTERVAL_HOURS} hours ago)"
                )
                
                # Queue fetch tasks
                task_ids = []
                for channel in channels_to_fetch:
                    task = fetch_youtube_channel_content.apply_async(
                        args=[channel.id],
                        countdown=5  # Stagger tasks
                    )
                    task_ids.append(task.id)
                    logger.info(f"Queued fetch for {channel.name} (task: {task.id})")
                
                return {
                    'success': True,
                    'total_channels': len(channels),
                    'channels_queued': len(channels_to_fetch),
                    'task_ids': task_ids,
                    'cutoff_time': cutoff_time.isoformat()
                }
                
            except Exception as e:
                logger.error(f"Error in fetch_all_active_channels: {e}", exc_info=True)
                raise
    
    return run_async(_fetch_all())


@celery_app.task(
    name='youtube.refresh_channel_metadata',
    bind=True
)
def refresh_channel_metadata(self, channel_id: int) -> dict:
    """
    Refresh channel metadata from YouTube.
    
    Updates:
    - Channel name
    - Description
    - Thumbnail URL
    - Subscriber count (from YouTube, not our internal count)
    
    Args:
        channel_id: Database ID of the channel
        
    Returns:
        Dictionary with update results
    """
    import asyncio
    
    async def _refresh_metadata():
        async with AsyncSessionLocal() as db:
            try:
                # Get channel
                channel = await get_channel_by_id(db, channel_id)
                if not channel:
                    return {
                        'error': f'Channel {channel_id} not found',
                        'success': False
                    }
                
                logger.info(f"Refreshing metadata for: {channel.name}")
                
                # Fetch from YouTube
                youtube = YouTubeService()
                channel_info = await youtube.get_channel_by_id(channel.source_identifier)
                
                # Update channel
                channel.name = channel_info['title']
                channel.description = channel_info.get('description')
                channel.thumbnail_url = channel_info.get('thumbnail_url')
                # Note: We don't update subscriber_count from YouTube as we track our own subscribers
                
                await db.commit()
                
                logger.info(f"Successfully refreshed metadata for {channel.name}")
                
                return {
                    'success': True,
                    'channel_id': channel_id,
                    'channel_name': channel.name,
                    'youtube_subscriber_count': channel_info.get('subscriber_count', 0)
                }
                
            except Exception as e:
                logger.error(f"Error refreshing channel metadata: {e}", exc_info=True)
                await db.rollback()
                raise
    
    return run_async(_refresh_metadata())


# ========================================
# Task Monitoring
# ========================================

@celery_app.task(name='youtube.get_processing_stats')
def get_processing_stats() -> dict:
    """
    Get statistics about YouTube content processing.
    
    Returns counts of content items by status.
    """
    import asyncio
    from sqlalchemy import func
    
    async def _get_stats():
        async with AsyncSessionLocal() as db:
            # Count by status
            result = await db.execute(
                select(
                    ContentItem.processing_status,
                    func.count(ContentItem.id)
                )
                .join(Channel)
                .where(Channel.source_type == ContentSourceType.YOUTUBE)
                .group_by(ContentItem.processing_status)
            )
            
            status_counts = {row[0].value: row[1] for row in result.all()}
            
            return {
                'pending': status_counts.get('pending', 0),
                'processing': status_counts.get('processing', 0),
                'processed': status_counts.get('processed', 0),
                'failed': status_counts.get('failed', 0),
                'total': sum(status_counts.values())
            }
    
    return run_async(_get_stats())

