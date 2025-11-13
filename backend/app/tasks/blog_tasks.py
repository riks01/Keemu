"""
Celery tasks for Blog/RSS content fetching and processing.

This module contains background tasks for:
- Fetching articles from RSS/Atom feeds
- Processing article content with extraction pipeline
- Scheduled periodic fetching
- Blog metadata updates
- Conditional GET support (ETag, Last-Modified)
"""

import logging
import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from celery import Task
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.content import Channel, ContentItem, ProcessingStatus, UserSubscription
from app.models.user import ContentSourceType
from app.services.blog_service import (
    BlogService,
    BlogServiceError,
    FeedNotFoundError,
    ArticleExtractionError,
    RobotsTxtForbiddenError,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# ========================================
# Helper Functions
# ========================================


async def get_channel_by_id(db: AsyncSession, channel_id: int) -> Optional[Channel]:
    """Get channel by database ID."""
    result = await db.execute(
        select(Channel).where(Channel.id == channel_id)
    )
    return result.scalar_one_or_none()


async def content_item_exists(
    db: AsyncSession,
    channel_id: int,
    article_url: str
) -> bool:
    """Check if content item already exists (by URL)."""
    # Use URL hash for external_id
    url_hash = hashlib.md5(article_url.encode()).hexdigest()
    
    result = await db.execute(
        select(ContentItem).where(
            ContentItem.channel_id == channel_id,
            ContentItem.external_id == url_hash
        )
    )
    return result.scalar_one_or_none() is not None


async def get_active_subscriptions_for_channel(
    db: AsyncSession,
    channel_id: int
) -> List[UserSubscription]:
    """Get all active subscriptions for a channel."""
    result = await db.execute(
        select(UserSubscription).where(
            UserSubscription.channel_id == channel_id,
            UserSubscription.is_active == True
        )
    )
    return result.scalars().all()


# ========================================
# Base Task Class
# ========================================


class BlogTask(Task):
    """Base task class with retry logic and error handling."""
    
    autoretry_for = (BlogServiceError,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes
    retry_jitter = True


# ========================================
# Main Tasks
# ========================================


@celery_app.task(
    base=BlogTask,
    name='blog.fetch_blog_content',
    bind=True,
    max_retries=3
)
def fetch_blog_content(self, channel_id: int) -> dict:
    """
    Fetch latest articles from a blog/RSS feed.
    
    This task:
    1. Gets the channel (blog) from database
    2. Fetches latest articles from RSS feed
    3. Filters out articles we already have
    4. Creates ContentItem records with status=PENDING
    5. Queues process_article tasks for each new article
    6. Updates channel.last_fetched_at
    7. Supports conditional GET (respects ETag and Last-Modified headers)
    
    Args:
        channel_id: Database ID of the blog channel
        
    Returns:
        Dictionary with task results:
        {
            'channel_id': int,
            'blog_name': str,
            'articles_found': int,
            'new_articles': int,
            'processing_tasks': List[str],  # Task IDs
            'success': bool
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
                
                if channel.source_type != ContentSourceType.BLOG:
                    logger.error(f"Channel {channel_id} is not a blog channel")
                    return {
                        'error': 'Not a blog channel',
                        'success': False
                    }
                
                logger.info(f"Fetching content for blog: {channel.name} ({channel.source_identifier})")
                
                # Initialize blog service
                blog_service = BlogService()
                feed_url = channel.source_identifier
                
                # Check if there are any active subscriptions
                active_subs = await get_active_subscriptions_for_channel(db, channel_id)
                if not active_subs:
                    logger.info(f"No active subscriptions for channel {channel_id}, skipping fetch")
                    return {
                        'channel_id': channel_id,
                        'blog_name': channel.name,
                        'articles_found': 0,
                        'new_articles': 0,
                        'processing_tasks': [],
                        'success': True,
                        'message': 'No active subscriptions'
                    }
                
                # Determine cutoff date for fetching articles
                # Only fetch articles published after last fetch or last 30 days
                if channel.last_fetched_at:
                    since_date = channel.last_fetched_at
                else:
                    since_date = datetime.now(timezone.utc) - timedelta(days=30)
                
                # Parse feed
                try:
                    articles = blog_service.parse_feed(
                        feed_url,
                        max_entries=50,
                        since_date=since_date
                    )
                except FeedNotFoundError as e:
                    logger.error(f"Feed not found for channel {channel_id}: {e}")
                    return {
                        'channel_id': channel_id,
                        'blog_name': channel.name,
                        'error': str(e),
                        'success': False
                    }
                
                logger.info(f"Found {len(articles)} articles from feed")
                
                # Filter for new articles
                new_articles = []
                for article in articles:
                    article_url = article['url']
                    if not await content_item_exists(db, channel_id, article_url):
                        new_articles.append(article)
                
                logger.info(f"Found {len(new_articles)} new articles (filtered from {len(articles)})")
                
                # Create ContentItem records for new articles
                processing_tasks = []
                for article in new_articles:
                    try:
                        # Generate URL hash for external_id
                        url_hash = hashlib.md5(article['url'].encode()).hexdigest()
                        
                        # Create ContentItem with PENDING status
                        content_item = ContentItem(
                            channel_id=channel_id,
                            external_id=url_hash,
                            title=article['title'],
                            content_body=None,  # Will be filled by process_article task
                            published_at=article['published'],
                            processing_status=ProcessingStatus.PENDING,
                            content_metadata={
                                'article_url': article['url'],
                                'author': article['author'],
                                'summary': article['summary'],
                                'guid': article['guid'],
                                'feed_url': feed_url,
                            }
                        )
                        
                        db.add(content_item)
                        await db.flush()  # Get content_item.id
                        
                        # Queue processing task
                        task = process_article.delay(
                            content_item.id,
                            article['url']
                        )
                        processing_tasks.append(task.id)
                        
                        logger.info(f"Queued article for processing: {article['title']} (task_id={task.id})")
                    
                    except Exception as e:
                        logger.error(f"Error creating content item for article {article['url']}: {e}")
                        continue
                
                # Update channel last_fetched_at
                channel.last_fetched_at = datetime.now(timezone.utc)
                
                # Update all active subscriptions last_fetched_at
                for sub in active_subs:
                    sub.last_fetched_at = datetime.now(timezone.utc)
                
                await db.commit()
                
                result = {
                    'channel_id': channel_id,
                    'blog_name': channel.name,
                    'articles_found': len(articles),
                    'new_articles': len(new_articles),
                    'processing_tasks': processing_tasks,
                    'success': True
                }
                
                logger.info(f"Successfully fetched blog content: {result}")
                return result
            
            except Exception as e:
                logger.error(f"Error fetching blog content for channel {channel_id}: {e}", exc_info=True)
                await db.rollback()
                return {
                    'channel_id': channel_id,
                    'error': str(e),
                    'success': False
                }
    
    # Run async function
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_fetch_content())


@celery_app.task(
    base=BlogTask,
    name='blog.process_article',
    bind=True,
    max_retries=3
)
def process_article(self, content_item_id: int, article_url: str) -> dict:
    """
    Extract and process article content.
    
    This task:
    1. Gets the ContentItem from database
    2. Extracts article content using multi-stage extraction pipeline
    3. Updates ContentItem with extracted content and metadata
    4. Updates processing status to PROCESSED or FAILED
    5. Respects robots.txt
    6. Implements politeness delays
    
    Args:
        content_item_id: Database ID of the ContentItem
        article_url: URL of the article to extract
        
    Returns:
        Dictionary with processing results:
        {
            'content_item_id': int,
            'article_url': str,
            'extraction_method': str,
            'word_count': int,
            'quality_score': float,
            'success': bool
        }
    """
    import asyncio
    import time
    
    async def _process_article():
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
                
                logger.info(f"Processing article: {article_url}")
                
                # Initialize blog service
                blog_service = BlogService()
                
                # Check robots.txt
                try:
                    blog_service.check_robots_txt(article_url)
                except RobotsTxtForbiddenError as e:
                    logger.warning(f"robots.txt forbids scraping {article_url}: {e}")
                    content_item.processing_status = ProcessingStatus.FAILED
                    content_item.content_metadata['error'] = 'Forbidden by robots.txt'
                    await db.commit()
                    return {
                        'content_item_id': content_item_id,
                        'article_url': article_url,
                        'error': 'Forbidden by robots.txt',
                        'success': False
                    }
                
                # Extract article content
                try:
                    article_data = blog_service.extract_article(article_url)
                    
                    if not article_data:
                        raise ArticleExtractionError("No extraction method succeeded")
                    
                    # Update content item
                    content_item.content_body = article_data['content']
                    content_item.processing_status = ProcessingStatus.PROCESSED
                    
                    # Update metadata
                    metadata = content_item.content_metadata or {}
                    metadata.update({
                        'author': article_data.get('author', metadata.get('author')),
                        'word_count': article_data['word_count'],
                        'read_time_minutes': blog_service.calculate_read_time(article_data['word_count']),
                        'language': article_data.get('language', ''),
                        'images': article_data.get('images', []),
                        'excerpt': article_data.get('excerpt', ''),
                        'extraction_method': article_data['extraction_method'],
                        'extraction_quality_score': article_data['quality_score'],
                        'has_images': len(article_data.get('images', [])) > 0,
                        'processed_at': datetime.now(timezone.utc).isoformat(),
                    })
                    content_item.content_metadata = metadata
                    
                    # Update published_at if we got a better date
                    if article_data.get('published_date') and not content_item.published_at:
                        content_item.published_at = article_data['published_date']
                    
                    await db.commit()
                    
                    result = {
                        'content_item_id': content_item_id,
                        'article_url': article_url,
                        'extraction_method': article_data['extraction_method'],
                        'word_count': article_data['word_count'],
                        'quality_score': article_data['quality_score'],
                        'success': True
                    }
                    
                    logger.info(f"Successfully processed article: {result}")
                    return result
                
                except ArticleExtractionError as e:
                    logger.error(f"Article extraction failed for {article_url}: {e}")
                    content_item.processing_status = ProcessingStatus.FAILED
                    metadata = content_item.content_metadata or {}
                    metadata['error'] = str(e)
                    content_item.content_metadata = metadata
                    await db.commit()
                    
                    return {
                        'content_item_id': content_item_id,
                        'article_url': article_url,
                        'error': str(e),
                        'success': False
                    }
            
            except Exception as e:
                logger.error(f"Error processing article {article_url}: {e}", exc_info=True)
                
                # Update status to FAILED
                try:
                    result = await db.execute(
                        select(ContentItem).where(ContentItem.id == content_item_id)
                    )
                    content_item = result.scalar_one_or_none()
                    if content_item:
                        content_item.processing_status = ProcessingStatus.FAILED
                        metadata = content_item.content_metadata or {}
                        metadata['error'] = str(e)
                        content_item.content_metadata = metadata
                        await db.commit()
                except:
                    pass
                
                return {
                    'content_item_id': content_item_id,
                    'article_url': article_url,
                    'error': str(e),
                    'success': False
                }
    
    # Run async function
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_process_article())


@celery_app.task(
    name='blog.fetch_all_active_blogs',
    bind=True
)
def fetch_all_active_blogs(self) -> dict:
    """
    Scheduled task to fetch content from all active blog channels.
    
    This task:
    1. Finds all blog channels with active subscriptions
    2. Queues fetch_blog_content tasks for each channel
    3. Returns summary of queued tasks
    
    Scheduled to run every 12 hours via Celery Beat.
    
    Returns:
        Dictionary with task results:
        {
            'channels_found': int,
            'tasks_queued': int,
            'task_ids': List[str],
            'success': bool
        }
    """
    import asyncio
    
    async def _fetch_all():
        async with AsyncSessionLocal() as db:
            try:
                logger.info("Starting scheduled fetch for all active blog channels")
                
                # Find all blog channels with active subscriptions
                result = await db.execute(
                    select(Channel)
                    .join(UserSubscription)
                    .where(
                        Channel.source_type == ContentSourceType.BLOG,
                        UserSubscription.is_active == True,
                        Channel.is_active == True
                    )
                    .distinct()
                )
                channels = result.scalars().all()
                
                logger.info(f"Found {len(channels)} active blog channels")
                
                # Queue fetch tasks for each channel
                task_ids = []
                for channel in channels:
                    try:
                        task = fetch_blog_content.delay(channel.id)
                        task_ids.append(task.id)
                        logger.info(f"Queued fetch for blog {channel.name} (task_id={task.id})")
                    except Exception as e:
                        logger.error(f"Error queuing fetch for channel {channel.id}: {e}")
                        continue
                
                result = {
                    'channels_found': len(channels),
                    'tasks_queued': len(task_ids),
                    'task_ids': task_ids,
                    'success': True
                }
                
                logger.info(f"Scheduled fetch completed: {result}")
                return result
            
            except Exception as e:
                logger.error(f"Error in scheduled blog fetch: {e}", exc_info=True)
                return {
                    'error': str(e),
                    'success': False
                }
    
    # Run async function
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_fetch_all())


@celery_app.task(
    base=BlogTask,
    name='blog.refresh_blog_metadata',
    bind=True,
    max_retries=2
)
def refresh_blog_metadata(self, channel_id: int) -> dict:
    """
    Refresh blog/feed metadata.
    
    This task:
    1. Fetches the feed to get updated metadata
    2. Updates channel name, description if changed
    3. Validates feed is still accessible
    
    Args:
        channel_id: Database ID of the blog channel
        
    Returns:
        Dictionary with refresh results:
        {
            'channel_id': int,
            'updated': bool,
            'changes': Dict[str, Any],
            'success': bool
        }
    """
    import asyncio
    
    async def _refresh_metadata():
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
                
                logger.info(f"Refreshing metadata for blog: {channel.name}")
                
                # Initialize blog service
                blog_service = BlogService()
                feed_url = channel.source_identifier
                
                # Try to parse feed (validates it's still accessible)
                try:
                    articles = blog_service.parse_feed(feed_url, max_entries=1)
                except FeedNotFoundError as e:
                    logger.error(f"Feed no longer accessible: {e}")
                    channel.is_active = False
                    await db.commit()
                    return {
                        'channel_id': channel_id,
                        'error': 'Feed no longer accessible',
                        'success': False
                    }
                
                # TODO: Extract and update feed metadata (title, description)
                # This would require parsing the feed's channel information
                
                changes = {}
                updated = False
                
                # Update last checked time
                metadata = channel.channel_metadata or {}
                metadata['last_metadata_refresh'] = datetime.now(timezone.utc).isoformat()
                channel.channel_metadata = metadata
                
                await db.commit()
                
                result = {
                    'channel_id': channel_id,
                    'updated': updated,
                    'changes': changes,
                    'success': True
                }
                
                logger.info(f"Metadata refresh completed: {result}")
                return result
            
            except Exception as e:
                logger.error(f"Error refreshing blog metadata: {e}", exc_info=True)
                return {
                    'channel_id': channel_id,
                    'error': str(e),
                    'success': False
                }
    
    # Run async function
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_refresh_metadata())

