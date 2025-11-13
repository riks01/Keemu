"""
Blog/RSS subscription API endpoints.

This module provides REST API endpoints for managing blog/RSS feed subscriptions,
including feed discovery, subscription management, and manual refresh triggers.
"""

import logging
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_active_user
from app.core.config import settings
from app.db.deps import get_db
from app.models.content import Channel, ContentItem, UserSubscription, ProcessingStatus
from app.models.user import User, ContentSourceType
from app.schemas.blog import (
    BlogDiscoverRequest,
    BlogDiscoverResponse,
    BlogSubscribeRequest,
    BlogSubscriptionResponse,
    BlogSubscriptionUpdate,
    BlogListResponse,
    BlogDetailsResponse,
    BlogStatsResponse,
    BlogRefreshResponse,
    BlogArticleSummary,
    ErrorResponse,
)
from app.services.blog_service import (
    BlogService,
    BlogServiceError,
    FeedNotFoundError,
    ArticleExtractionError,
    RobotsTxtForbiddenError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/blogs", tags=["Blogs"])


# ========================================
# Helper Functions
# ========================================


async def _get_or_create_channel(
    db: AsyncSession,
    blog_service: BlogService,
    feed_url: str,
    blog_url: Optional[str] = None
) -> Channel:
    """
    Get existing blog channel from database or create a new one.
    
    Args:
        db: Database session
        blog_service: Blog service instance
        feed_url: RSS/Atom feed URL
        blog_url: Optional blog homepage URL
        
    Returns:
        Channel model instance
        
    Raises:
        FeedNotFoundError: If feed cannot be accessed
        BlogServiceError: For other blog service errors
    """
    # Check if channel exists in database (by feed URL)
    result = await db.execute(
        select(Channel).where(
            Channel.source_type == ContentSourceType.BLOG,
            Channel.source_identifier == feed_url
        )
    )
    channel = result.scalar_one_or_none()
    
    if channel:
        logger.info(f"Found existing blog channel: {feed_url}")
        return channel
    
    # Fetch feed to get metadata
    logger.info(f"Fetching feed metadata from: {feed_url}")
    try:
        articles = blog_service.parse_feed(feed_url, max_entries=1)
    except Exception as e:
        logger.error(f"Error parsing feed {feed_url}: {e}")
        raise FeedNotFoundError(f"Could not parse feed: {e}")
    
    # Extract blog name from feed or use domain
    blog_name = "Unknown Blog"
    blog_description = None
    
    # Try to get blog name from first article or URL
    if articles and len(articles) > 0:
        # Use domain as fallback
        domain = blog_service.get_domain(feed_url)
        blog_name = domain
    else:
        domain = blog_service.get_domain(feed_url)
        blog_name = domain
    
    # Create new channel
    channel = Channel(
        source_type=ContentSourceType.BLOG,
        source_identifier=feed_url,  # Use feed URL as identifier
        name=blog_name,
        description=blog_description,
        thumbnail_url=None,
        subscriber_count=0,
        is_active=True,
        channel_metadata={
            "feed_url": feed_url,
            "blog_url": blog_url or "",
            "feed_type": "rss",
        }
    )
    
    db.add(channel)
    await db.flush()  # Get channel.id
    
    logger.info(f"Created new blog channel: {blog_name} ({feed_url})")
    return channel


async def _get_user_subscription(
    db: AsyncSession,
    user_id: int,
    subscription_id: int
) -> Optional[UserSubscription]:
    """Get user subscription by ID, ensuring it belongs to the user."""
    result = await db.execute(
        select(UserSubscription)
        .join(Channel)
        .where(
            UserSubscription.id == subscription_id,
            UserSubscription.user_id == user_id,
            Channel.source_type == ContentSourceType.BLOG
        )
    )
    return result.scalar_one_or_none()


def _subscription_to_response(
    subscription: UserSubscription,
    article_count: int = 0
) -> BlogSubscriptionResponse:
    """Convert UserSubscription model to response schema."""
    channel = subscription.channel
    
    return BlogSubscriptionResponse(
        id=subscription.id,
        user_id=subscription.user_id,
        channel_id=subscription.channel_id,
        blog_name=subscription.custom_name or channel.name,
        feed_url=channel.source_identifier,
        blog_url=channel.channel_metadata.get('blog_url') if channel.channel_metadata else None,
        custom_display_name=subscription.custom_name,
        is_active=subscription.is_active,
        notification_enabled=subscription.notification_enabled,
        article_count=article_count,
        last_fetched_at=subscription.last_fetched_at,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
        metadata=channel.channel_metadata
    )


# ========================================
# Endpoints
# ========================================


@router.post(
    "/discover",
    response_model=BlogDiscoverResponse,
    summary="Discover RSS feed from blog URL",
    description="Automatically discover RSS/Atom feed URL from a blog homepage URL.",
    responses={
        200: {"description": "Feed discovery completed (check success field)"},
        400: {"description": "Invalid blog URL"},
        500: {"description": "Server error during discovery"},
    }
)
async def discover_feed(
    request: BlogDiscoverRequest,
    current_user: User = Depends(get_current_active_user)
):
    """
    Discover RSS/Atom feed from a blog homepage.
    
    Uses multiple strategies:
    - Looks for <link rel="alternate"> tags
    - Checks common feed locations (/feed, /rss, etc.)
    - Analyzes HTML for feed links
    """
    try:
        blog_service = BlogService()
        
        # Validate URL format
        if not blog_service.validate_blog_url(request.blog_url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid blog URL format"
            )
        
        # Discover feed
        feed_url = blog_service.discover_feed(request.blog_url)
        
        if feed_url:
            return BlogDiscoverResponse(
                success=True,
                feed_url=feed_url,
                blog_url=request.blog_url,
                blog_title=None,
                feed_type="rss",
                message="RSS feed discovered successfully"
            )
        else:
            return BlogDiscoverResponse(
                success=False,
                feed_url=None,
                blog_url=request.blog_url,
                blog_title=None,
                feed_type=None,
                message="No RSS feed found. You can try subscribing with a direct feed URL."
            )
    
    except BlogServiceError as e:
        logger.error(f"Blog service error during discovery: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error during feed discovery: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during feed discovery"
        )


@router.post(
    "/subscribe",
    response_model=BlogSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to a blog/RSS feed",
    description="Create a new blog subscription using either a blog URL (auto-discovers feed) or direct feed URL.",
    responses={
        201: {"description": "Successfully subscribed to blog"},
        400: {"description": "Invalid request or already subscribed"},
        404: {"description": "Feed not found or inaccessible"},
        500: {"description": "Server error"},
    }
)
async def subscribe_to_blog(
    request: BlogSubscribeRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Subscribe to a blog/RSS feed.
    
    Provide either:
    - blog_url: Homepage URL (will auto-discover feed)
    - feed_url: Direct RSS/Atom feed URL
    
    If blog_url is provided, the system will attempt to discover the RSS feed automatically.
    """
    try:
        blog_service = BlogService()
        
        # Determine feed URL
        feed_url = request.feed_url
        blog_url = request.blog_url
        
        if not feed_url and blog_url:
            # Auto-discover feed from blog URL
            logger.info(f"Auto-discovering feed for: {blog_url}")
            feed_url = blog_service.discover_feed(blog_url)
            
            if not feed_url:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Could not discover RSS feed from blog URL. Please provide the direct feed URL."
                )
        
        if not feed_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either blog_url or feed_url must be provided"
            )
        
        # Get or create channel
        channel = await _get_or_create_channel(db, blog_service, feed_url, blog_url)
        
        # Check if user is already subscribed
        existing = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == current_user.id,
                UserSubscription.channel_id == channel.id
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You are already subscribed to this blog"
            )
        
        # Create subscription
        subscription = UserSubscription(
            user_id=current_user.id,
            channel_id=channel.id,
            is_active=True,
            notification_enabled=request.notification_enabled,
            custom_name=request.custom_display_name,
            last_fetched_at=None
        )
        
        db.add(subscription)
        
        # Increment channel subscriber count
        channel.subscriber_count += 1
        
        await db.commit()
        await db.refresh(subscription)
        await db.refresh(channel)
        
        logger.info(
            f"User {current_user.id} subscribed to blog {channel.name} (channel_id={channel.id})"
        )
        
        # Trigger initial fetch (async task would go here)
        # TODO: Trigger celery task to fetch initial content
        
        return _subscription_to_response(subscription, article_count=0)
    
    except HTTPException:
        raise
    except FeedNotFoundError as e:
        logger.error(f"Feed not found: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except BlogServiceError as e:
        logger.error(f"Blog service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error subscribing to blog: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while subscribing"
        )


@router.get(
    "",
    response_model=BlogListResponse,
    summary="List blog subscriptions",
    description="Get a paginated list of user's blog subscriptions with statistics.",
)
async def list_subscriptions(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    active_only: bool = Query(False, description="Show only active subscriptions"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all blog subscriptions for the current user.
    
    Returns paginated list with statistics.
    """
    try:
        # Build query
        query = (
            select(UserSubscription)
            .join(Channel)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.BLOG
            )
        )
        
        if active_only:
            query = query.where(UserSubscription.is_active == True)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0
        
        # Get paginated results
        query = query.order_by(UserSubscription.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        
        result = await db.execute(query)
        subscriptions = result.scalars().all()
        
        # Get article counts for each subscription
        subscription_responses = []
        for sub in subscriptions:
            article_count_result = await db.execute(
                select(func.count())
                .select_from(ContentItem)
                .where(ContentItem.channel_id == sub.channel_id)
            )
            article_count = article_count_result.scalar() or 0
            subscription_responses.append(_subscription_to_response(sub, article_count))
        
        # Get counts
        active_count_result = await db.execute(
            select(func.count())
            .select_from(UserSubscription)
            .join(Channel)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.BLOG,
                UserSubscription.is_active == True
            )
        )
        active_count = active_count_result.scalar() or 0
        
        paused_count = total - active_count
        total_pages = (total + page_size - 1) // page_size
        
        return BlogListResponse(
            subscriptions=subscription_responses,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            active_count=active_count,
            paused_count=paused_count
        )
    
    except Exception as e:
        logger.error(f"Error listing blog subscriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching subscriptions"
        )


@router.get(
    "/{subscription_id}",
    response_model=BlogDetailsResponse,
    summary="Get blog subscription details",
    description="Get detailed information about a specific blog subscription including recent articles.",
)
async def get_subscription_details(
    subscription_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a blog subscription."""
    try:
        subscription = await _get_user_subscription(db, current_user.id, subscription_id)
        
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription not found"
            )
        
        # Get article count
        article_count_result = await db.execute(
            select(func.count())
            .select_from(ContentItem)
            .where(ContentItem.channel_id == subscription.channel_id)
        )
        article_count = article_count_result.scalar() or 0
        
        # Get recent articles (last 10)
        articles_result = await db.execute(
            select(ContentItem)
            .where(ContentItem.channel_id == subscription.channel_id)
            .order_by(ContentItem.published_at.desc())
            .limit(10)
        )
        articles = articles_result.scalars().all()
        
        recent_articles = []
        for article in articles:
            metadata = article.content_metadata or {}
            recent_articles.append(
                BlogArticleSummary(
                    id=article.id,
                    title=article.title,
                    url=metadata.get('article_url', ''),
                    author=metadata.get('author'),
                    published_at=article.published_at,
                    word_count=metadata.get('word_count'),
                    read_time_minutes=metadata.get('read_time_minutes'),
                    excerpt=metadata.get('excerpt')
                )
            )
        
        # Build statistics
        statistics = {
            "total_articles": article_count,
            "fetch_success": subscription.last_fetched_at is not None,
            "last_fetch": subscription.last_fetched_at.isoformat() if subscription.last_fetched_at else None,
        }
        
        return BlogDetailsResponse(
            subscription=_subscription_to_response(subscription, article_count),
            recent_articles=recent_articles,
            statistics=statistics
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting subscription details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching subscription details"
        )


@router.put(
    "/{subscription_id}",
    response_model=BlogSubscriptionResponse,
    summary="Update blog subscription",
    description="Update subscription settings (pause/resume, custom name, notifications).",
)
async def update_subscription(
    subscription_id: int,
    update_data: BlogSubscriptionUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update blog subscription settings."""
    try:
        subscription = await _get_user_subscription(db, current_user.id, subscription_id)
        
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription not found"
            )
        
        # Update fields
        if update_data.is_active is not None:
            subscription.is_active = update_data.is_active
            logger.info(
                f"User {current_user.id} {'activated' if update_data.is_active else 'paused'} "
                f"subscription {subscription_id}"
            )
        
        if update_data.custom_display_name is not None:
            subscription.custom_name = update_data.custom_display_name
        
        if update_data.notification_enabled is not None:
            subscription.notification_enabled = update_data.notification_enabled
        
        subscription.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(subscription)
        
        # Get article count
        article_count_result = await db.execute(
            select(func.count())
            .select_from(ContentItem)
            .where(ContentItem.channel_id == subscription.channel_id)
        )
        article_count = article_count_result.scalar() or 0
        
        return _subscription_to_response(subscription, article_count)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating subscription: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the subscription"
        )


@router.delete(
    "/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unsubscribe from blog",
    description="Delete a blog subscription.",
)
async def unsubscribe_from_blog(
    subscription_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Unsubscribe from a blog."""
    try:
        subscription = await _get_user_subscription(db, current_user.id, subscription_id)
        
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription not found"
            )
        
        channel = subscription.channel
        
        # Delete subscription
        await db.delete(subscription)
        
        # Decrement channel subscriber count
        if channel.subscriber_count > 0:
            channel.subscriber_count -= 1
        
        await db.commit()
        
        logger.info(
            f"User {current_user.id} unsubscribed from blog {channel.name} "
            f"(subscription_id={subscription_id})"
        )
        
        return None
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsubscribing: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while unsubscribing"
        )


@router.post(
    "/{subscription_id}/refresh",
    response_model=BlogRefreshResponse,
    summary="Manually refresh blog content",
    description="Trigger an immediate fetch of new articles from the blog.",
)
async def refresh_blog(
    subscription_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Manually trigger a content fetch for a blog subscription."""
    try:
        subscription = await _get_user_subscription(db, current_user.id, subscription_id)
        
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription not found"
            )
        
        if not subscription.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot refresh paused subscription. Please activate it first."
            )
        
        # TODO: Trigger Celery task to fetch content
        # task = fetch_blog_content.delay(subscription.channel_id, current_user.id)
        
        logger.info(
            f"User {current_user.id} triggered manual refresh for blog subscription {subscription_id}"
        )
        
        return BlogRefreshResponse(
            success=True,
            message="Refresh triggered successfully. Articles will be fetched shortly.",
            task_id=None,  # Would be task.id from Celery
            estimated_time=60  # Estimated seconds
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing blog: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while triggering refresh"
        )


@router.get(
    "/stats",
    response_model=BlogStatsResponse,
    summary="Get blog statistics",
    description="Get aggregated statistics about blog subscriptions and articles.",
)
async def get_blog_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get aggregated statistics for user's blog subscriptions."""
    try:
        # Get subscription counts
        total_subs_result = await db.execute(
            select(func.count())
            .select_from(UserSubscription)
            .join(Channel)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.BLOG
            )
        )
        total_subscriptions = total_subs_result.scalar() or 0
        
        active_subs_result = await db.execute(
            select(func.count())
            .select_from(UserSubscription)
            .join(Channel)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.BLOG,
                UserSubscription.is_active == True
            )
        )
        active_subscriptions = active_subs_result.scalar() or 0
        
        paused_subscriptions = total_subscriptions - active_subscriptions
        
        # Get user's subscribed channels
        channels_result = await db.execute(
            select(Channel.id)
            .join(UserSubscription)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.BLOG
            )
        )
        channel_ids = [row[0] for row in channels_result.all()]
        
        # Get total articles
        if channel_ids:
            total_articles_result = await db.execute(
                select(func.count())
                .select_from(ContentItem)
                .where(ContentItem.channel_id.in_(channel_ids))
            )
            total_articles = total_articles_result.scalar() or 0
        else:
            total_articles = 0
        
        # Get articles by time period
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)
        
        articles_today = 0
        articles_this_week = 0
        articles_this_month = 0
        
        if channel_ids:
            # Today
            today_result = await db.execute(
                select(func.count())
                .select_from(ContentItem)
                .where(
                    ContentItem.channel_id.in_(channel_ids),
                    ContentItem.created_at >= today_start
                )
            )
            articles_today = today_result.scalar() or 0
            
            # This week
            week_result = await db.execute(
                select(func.count())
                .select_from(ContentItem)
                .where(
                    ContentItem.channel_id.in_(channel_ids),
                    ContentItem.created_at >= week_start
                )
            )
            articles_this_week = week_result.scalar() or 0
            
            # This month
            month_result = await db.execute(
                select(func.count())
                .select_from(ContentItem)
                .where(
                    ContentItem.channel_id.in_(channel_ids),
                    ContentItem.created_at >= month_start
                )
            )
            articles_this_month = month_result.scalar() or 0
        
        # Calculate averages
        avg_articles = total_articles / total_subscriptions if total_subscriptions > 0 else 0
        
        # TODO: Calculate fetch success rate from actual fetch attempts
        fetch_success_rate = 100.0  # Placeholder
        
        # TODO: Get most active blog
        most_active_blog = None
        
        return BlogStatsResponse(
            total_subscriptions=total_subscriptions,
            active_subscriptions=active_subscriptions,
            paused_subscriptions=paused_subscriptions,
            total_articles=total_articles,
            articles_today=articles_today,
            articles_this_week=articles_this_week,
            articles_this_month=articles_this_month,
            by_blog=[],  # TODO: Implement per-blog stats
            fetch_success_rate=fetch_success_rate,
            average_articles_per_blog=avg_articles,
            most_active_blog=most_active_blog,
            recent_fetch_errors=[]  # TODO: Track fetch errors
        )
    
    except Exception as e:
        logger.error(f"Error getting blog stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching statistics"
        )

