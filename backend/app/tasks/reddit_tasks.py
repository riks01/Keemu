"""
Celery tasks for Reddit content fetching and processing.

This module contains background tasks for:
- Fetching posts from Reddit subreddits (smart strategy)
- Processing posts with comments (delayed fetching)
- Scheduled periodic fetching
- Subreddit metadata updates
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict

from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.content import Channel, ContentItem, ProcessingStatus, UserSubscription
from app.models.user import ContentSourceType
from app.services.reddit import (
    RedditService,
    RedditAPIError,
    SubredditNotFoundError,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# ========================================
# Helper Functions
# ========================================


async def get_db() -> AsyncSession:
    """Get database session for async tasks."""
    async with AsyncSessionLocal() as session:
        return session


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


async def get_content_item_by_id(
    db: AsyncSession,
    content_item_id: int
) -> Optional[ContentItem]:
    """Get content item by ID."""
    result = await db.execute(
        select(ContentItem).where(ContentItem.id == content_item_id)
    )
    return result.scalar_one_or_none()


def passes_engagement_threshold(post: Dict, settings_dict: Dict) -> bool:
    """
    Check if post passes minimum engagement thresholds.
    
    Args:
        post: Post dictionary from RedditService
        settings_dict: Subscription settings with min_score and min_comments
        
    Returns:
        True if post meets thresholds
    """
    min_score = settings_dict.get('min_score', 10)
    min_comments = settings_dict.get('min_comments', 3)
    
    score = post.get('score', 0)
    num_comments = post.get('num_comments', 0)
    
    return score >= min_score and num_comments >= min_comments


def calculate_post_age_hours(post: Dict) -> float:
    """
    Calculate post age in hours.
    
    Args:
        post: Post dictionary with created_utc
        
    Returns:
        Age in hours
    """
    created_utc = post.get('created_utc')
    if not created_utc:
        return 0.0
    
    now = datetime.now(timezone.utc)
    age = now - created_utc
    return age.total_seconds() / 3600


def get_optimal_time_filter(subreddit_activity: str = 'medium') -> str:
    """
    Get optimal time filter based on subreddit activity level.
    
    Args:
        subreddit_activity: Activity level ('low', 'medium', 'high')
        
    Returns:
        Time filter string for Reddit API
    """
    filters = {
        'low': 'week',     # Low activity: look back further
        'medium': 'day',   # Medium: default
        'high': 'day',     # High: recent content is fine
    }
    return filters.get(subreddit_activity, 'day')


async def get_subscription_settings(
    db: AsyncSession,
    channel_id: int
) -> Dict:
    """
    Get subscription settings for a channel.
    
    Returns aggregated settings from all active subscriptions.
    For now, uses first active subscription's settings.
    """
    result = await db.execute(
        select(UserSubscription).where(
            UserSubscription.channel_id == channel_id,
            UserSubscription.is_active == True
        ).limit(1)
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        # Default settings
        return {
            'comment_limit': 20,
            'min_score': 10,
            'min_comments': 3,
        }
    
    extra = subscription.extra_settings or {}
    return {
        'comment_limit': extra.get('comment_limit', 20),
        'min_score': extra.get('min_score', 10),
        'min_comments': extra.get('min_comments', 3),
    }


# ========================================
# Base Task Class
# ========================================


class RedditTask(Task):
    """Base task class with retry logic and error handling."""
    
    autoretry_for = (RedditAPIError,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes
    retry_jitter = True


# ========================================
# Main Tasks
# ========================================


@celery_app.task(
    base=RedditTask,
    name='reddit.fetch_subreddit_content',
    bind=True,
    max_retries=3
)
def fetch_reddit_subreddit_content(
    self,
    channel_id: int,
    time_filter: str = 'day'
) -> dict:
    """
    Stage 1: Discovery fetch for Reddit posts.
    
    This task:
    1. Fetches posts from subreddit (hot + top)
    2. Applies engagement filters (min_score, min_comments, min_age)
    3. Creates ContentItem with PENDING status
    4. Schedules process_reddit_post for later (6-12 hours)
    
    Args:
        channel_id: Database ID of Channel (subreddit)
        time_filter: Time filter for 'top' posts
        
    Returns:
        Dict with stats about discovered posts
    """
    logger.info(f"Starting Reddit content fetch for channel {channel_id}")
    
    async def _fetch():
        db = await get_db()
        
        try:
            # Get channel
            channel = await get_channel_by_id(db, channel_id)
            if not channel or channel.source_type != ContentSourceType.REDDIT:
                logger.error(f"Channel {channel_id} not found or not a Reddit channel")
                return {'success': False, 'error': 'Invalid channel'}
            
            subreddit_name = channel.source_identifier
            logger.info(f"Fetching posts from r/{subreddit_name}")
            
            # Get subscription settings for engagement thresholds
            settings_dict = await get_subscription_settings(db, channel_id)
            
            # Initialize Reddit service
            reddit = RedditService()
            
            # Fetch posts - combine hot and top
            posts_hot = reddit.get_subreddit_posts(
                subreddit_name,
                limit=100,
                sort='hot'
            )
            
            posts_top = reddit.get_subreddit_posts(
                subreddit_name,
                limit=50,
                time_filter=time_filter,
                sort='top'
            )
            
            # Combine and deduplicate
            all_posts = {post['post_id']: post for post in posts_hot + posts_top}
            
            # Filter posts by engagement and age
            discovered = 0
            skipped_existing = 0
            skipped_threshold = 0
            skipped_age = 0
            
            for post_id, post in all_posts.items():
                # Check if already exists
                if await content_item_exists(db, channel_id, post_id):
                    skipped_existing += 1
                    continue
                
                # Check post age (must be at least 2 hours old)
                age_hours = calculate_post_age_hours(post)
                if age_hours < 2:
                    skipped_age += 1
                    logger.debug(
                        f"Skipping post {post_id} - too new ({age_hours:.1f}h old)"
                    )
                    continue
                
                # Check engagement threshold
                if not passes_engagement_threshold(post, settings_dict):
                    skipped_threshold += 1
                    logger.debug(
                        f"Skipping post {post_id} - below threshold "
                        f"(score={post['score']}, comments={post['num_comments']})"
                    )
                    continue
                
                # Create ContentItem with PENDING status
                content_item = ContentItem(
                    channel_id=channel_id,
                    external_id=post_id,
                    title=post['title'],
                    author=post['author'],
                    published_at=post['created_utc'],
                    url=post['url'],
                    processing_status=ProcessingStatus.PENDING,
                    content_metadata={
                        'post_id': post_id,
                        'subreddit': subreddit_name,
                        'score': post['score'],
                        'num_comments': post['num_comments'],
                        'upvote_ratio': post['upvote_ratio'],
                        'is_self': post['is_self'],
                        'permalink': post['permalink'],
                        'discovered_at': datetime.now(timezone.utc).isoformat(),
                    }
                )
                
                db.add(content_item)
                await db.commit()
                await db.refresh(content_item)
                
                # Schedule comment fetch with delay (6-12 hours)
                # Use random delay to spread load
                import random
                delay_hours = random.uniform(6, 12)
                delay_seconds = int(delay_hours * 3600)
                
                process_reddit_post.apply_async(
                    args=[content_item.id],
                    countdown=delay_seconds
                )
                
                discovered += 1
                logger.info(
                    f"Discovered post {post_id} from r/{subreddit_name}, "
                    f"scheduled for processing in {delay_hours:.1f}h"
                )
            
            # Update channel last_checked_at
            channel.last_checked_at = datetime.now(timezone.utc)
            await db.commit()
            
            logger.info(
                f"Reddit fetch complete for r/{subreddit_name}: "
                f"discovered={discovered}, skipped_existing={skipped_existing}, "
                f"skipped_threshold={skipped_threshold}, skipped_age={skipped_age}"
            )
            
            return {
                'success': True,
                'channel_id': channel_id,
                'subreddit': subreddit_name,
                'discovered': discovered,
                'skipped_existing': skipped_existing,
                'skipped_threshold': skipped_threshold,
                'skipped_age': skipped_age,
            }
            
        except SubredditNotFoundError as e:
            logger.error(f"Subreddit not found for channel {channel_id}: {e}")
            return {'success': False, 'error': str(e)}
        except RedditAPIError as e:
            logger.error(f"Reddit API error for channel {channel_id}: {e}")
            raise  # Trigger retry
        except Exception as e:
            logger.error(
                f"Unexpected error fetching Reddit content for channel {channel_id}: {e}",
                exc_info=True
            )
            return {'success': False, 'error': str(e)}
        finally:
            await db.close()
    
    # Run async function
    return asyncio.run(_fetch())


@celery_app.task(
    base=RedditTask,
    name='reddit.process_post',
    bind=True,
    max_retries=3
)
def process_reddit_post(self, content_item_id: int) -> dict:
    """
    Stage 2: Process Reddit post with mature comments.
    
    This task (runs 6-12 hours after discovery):
    1. Re-fetches post to get updated metadata
    2. Re-checks engagement thresholds
    3. Fetches comments (now mature discussion)
    4. Formats post + comments into structured text
    5. Updates ContentItem with full content
    
    Args:
        content_item_id: Database ID of ContentItem to process
        
    Returns:
        Dict with processing results
    """
    logger.info(f"Processing Reddit post {content_item_id}")
    
    async def _process():
        db = await get_db()
        
        try:
            # Get content item
            content_item = await get_content_item_by_id(db, content_item_id)
            if not content_item:
                logger.error(f"ContentItem {content_item_id} not found")
                return {'success': False, 'error': 'Content item not found'}
            
            post_id = content_item.external_id
            channel_id = content_item.channel_id
            
            # Get channel
            channel = await get_channel_by_id(db, channel_id)
            if not channel:
                logger.error(f"Channel {channel_id} not found")
                return {'success': False, 'error': 'Channel not found'}
            
            subreddit_name = channel.source_identifier
            
            # Get subscription settings
            settings_dict = await get_subscription_settings(db, channel_id)
            comment_limit = settings_dict['comment_limit']
            
            # Update status to PROCESSING
            content_item.processing_status = ProcessingStatus.PROCESSING
            await db.commit()
            
            # Initialize Reddit service
            reddit = RedditService()
            
            # Re-fetch post details (get updated score/comments)
            try:
                post = reddit.get_post_details(post_id)
            except Exception as e:
                logger.warning(
                    f"Could not re-fetch post {post_id} (may be deleted): {e}"
                )
                content_item.processing_status = ProcessingStatus.FAILED
                content_item.content_metadata = content_item.content_metadata or {}
                content_item.content_metadata['error'] = 'Post deleted or unavailable'
                await db.commit()
                return {'success': False, 'error': 'Post not available'}
            
            # Re-check engagement threshold
            if not passes_engagement_threshold(post, settings_dict):
                logger.info(
                    f"Post {post_id} no longer meets threshold after maturation, "
                    "marking as failed"
                )
                content_item.processing_status = ProcessingStatus.FAILED
                content_item.content_metadata = content_item.content_metadata or {}
                content_item.content_metadata['error'] = 'Below engagement threshold'
                await db.commit()
                return {'success': False, 'error': 'Below threshold'}
            
            # Fetch comments
            try:
                comments = reddit.get_post_comments(
                    post_id,
                    comment_limit=comment_limit,
                    sort='top'
                )
            except Exception as e:
                logger.error(f"Error fetching comments for post {post_id}: {e}")
                comments = []
            
            # Format content
            post_content = reddit.format_post_content(post)
            comments_content = reddit.format_comments_for_storage(comments)
            
            full_content = f"{post_content}\n\n--- Top Comments ---\n\n{comments_content}"
            
            # Calculate engagement score
            engagement_score = reddit.calculate_engagement_score(post)
            
            # Update content item
            content_item.content_body = full_content
            content_item.processing_status = ProcessingStatus.PROCESSED
            content_item.content_metadata = {
                'post_id': post_id,
                'subreddit': subreddit_name,
                'author': post['author'],
                'score': post['score'],
                'upvote_ratio': post['upvote_ratio'],
                'num_comments': post['num_comments'],
                'awards': post['total_awards_received'],
                'gilded': post['gilded'],
                'post_type': 'self' if post['is_self'] else 'link',
                'post_url': post['url'],
                'is_self': post['is_self'],
                'over_18': post['over_18'],
                'spoiler': post['spoiler'],
                'stickied': post['stickied'],
                'permalink': post['permalink'],
                'comments_fetched': len(comments),
                'comment_limit_used': comment_limit,
                'engagement_score': engagement_score,
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'top_comments': [
                    {
                        'comment_id': c['comment_id'],
                        'author': c['author'],
                        'score': c['score'],
                        'body_preview': c['body'][:200],
                        'is_submitter': c['is_submitter'],
                        'depth': c['depth'],
                    }
                    for c in comments[:5]  # Store preview of top 5
                ]
            }
            
            await db.commit()
            
            logger.info(
                f"Successfully processed post {post_id} from r/{subreddit_name} "
                f"with {len(comments)} comments (engagement={engagement_score:.1f})"
            )
            
            return {
                'success': True,
                'content_item_id': content_item_id,
                'post_id': post_id,
                'subreddit': subreddit_name,
                'comments_fetched': len(comments),
                'engagement_score': engagement_score,
            }
            
        except Exception as e:
            logger.error(
                f"Error processing post {content_item_id}: {e}",
                exc_info=True
            )
            # Mark as failed
            if content_item:
                content_item.processing_status = ProcessingStatus.FAILED
                content_item.content_metadata = content_item.content_metadata or {}
                content_item.content_metadata['error'] = str(e)
                await db.commit()
            return {'success': False, 'error': str(e)}
        finally:
            await db.close()
    
    return asyncio.run(_process())


@celery_app.task(name='reddit.fetch_all_active_channels')
def fetch_all_active_reddit_channels() -> dict:
    """
    Periodic task: Fetch content from all active Reddit channels.
    
    Scheduled to run every 3 hours (not hourly as originally planned).
    
    Returns:
        Dict with stats about queued fetches
    """
    logger.info("Starting periodic Reddit fetch for all active channels")
    
    async def _fetch_all():
        db = await get_db()
        
        try:
            # Get all active Reddit channels with active subscriptions
            result = await db.execute(
                select(Channel.id.distinct())
                .join(UserSubscription, Channel.id == UserSubscription.channel_id)
                .where(
                    Channel.source_type == ContentSourceType.REDDIT,
                    Channel.is_active == True,
                    UserSubscription.is_active == True
                )
            )
            
            channel_ids = [row[0] for row in result.all()]
            
            logger.info(f"Found {len(channel_ids)} active Reddit channels")
            
            # Queue fetch tasks
            for channel_id in channel_ids:
                fetch_reddit_subreddit_content.delay(channel_id)
            
            return {
                'success': True,
                'channels_queued': len(channel_ids),
            }
            
        except Exception as e:
            logger.error(f"Error queuing Reddit fetches: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
        finally:
            await db.close()
    
    return asyncio.run(_fetch_all())


@celery_app.task(name='reddit.refresh_metadata')
def refresh_reddit_metadata(channel_id: int) -> dict:
    """
    Refresh subreddit metadata (subscribers, description, etc).
    
    Args:
        channel_id: Database ID of Channel
        
    Returns:
        Dict with refresh results
    """
    logger.info(f"Refreshing metadata for Reddit channel {channel_id}")
    
    async def _refresh():
        db = await get_db()
        
        try:
            channel = await get_channel_by_id(db, channel_id)
            if not channel or channel.source_type != ContentSourceType.REDDIT:
                return {'success': False, 'error': 'Invalid channel'}
            
            subreddit_name = channel.source_identifier
            
            reddit = RedditService()
            subreddit_info = reddit.get_subreddit_by_name(subreddit_name)
            
            # Update channel
            channel.name = subreddit_info['title']
            channel.description = subreddit_info['description']
            channel.thumbnail_url = subreddit_info['icon_img']
            channel.subscriber_count = subreddit_info['subscribers']
            channel.metadata = {
                'over18': subreddit_info['over18'],
                'public': subreddit_info['public'],
                'banner_img': subreddit_info['banner_img'],
                'url': subreddit_info['url'],
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }
            
            await db.commit()
            
            logger.info(f"Refreshed metadata for r/{subreddit_name}")
            
            return {
                'success': True,
                'channel_id': channel_id,
                'subreddit': subreddit_name,
                'subscribers': subreddit_info['subscribers'],
            }
            
        except Exception as e:
            logger.error(f"Error refreshing metadata for channel {channel_id}: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            await db.close()
    
    return asyncio.run(_refresh())


@celery_app.task(name='reddit.get_stats')
def get_reddit_stats() -> dict:
    """
    Calculate Reddit statistics.
    
    Returns:
        Dict with aggregated statistics
    """
    async def _get_stats():
        db = await get_db()
        
        try:
            # Total posts
            total_result = await db.execute(
                select(func.count(ContentItem.id))
                .join(Channel, ContentItem.channel_id == Channel.id)
                .where(Channel.source_type == ContentSourceType.REDDIT)
            )
            total_posts = total_result.scalar() or 0
            
            # Posts in last 7 days
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            recent_result = await db.execute(
                select(func.count(ContentItem.id))
                .join(Channel, ContentItem.channel_id == Channel.id)
                .where(
                    Channel.source_type == ContentSourceType.REDDIT,
                    ContentItem.created_at >= seven_days_ago
                )
            )
            recent_posts = recent_result.scalar() or 0
            
            # Processing success rate
            processed_result = await db.execute(
                select(func.count(ContentItem.id))
                .join(Channel, ContentItem.channel_id == Channel.id)
                .where(
                    Channel.source_type == ContentSourceType.REDDIT,
                    ContentItem.processing_status == ProcessingStatus.PROCESSED
                )
            )
            processed = processed_result.scalar() or 0
            
            success_rate = (processed / total_posts * 100) if total_posts > 0 else 0
            
            return {
                'total_posts': total_posts,
                'posts_last_7_days': recent_posts,
                'processed_posts': processed,
                'success_rate': round(success_rate, 2),
            }
            
        except Exception as e:
            logger.error(f"Error calculating Reddit stats: {e}")
            return {'error': str(e)}
        finally:
            await db.close()
    
    # Import func here to avoid circular import
    from sqlalchemy import func
    return asyncio.run(_get_stats())





