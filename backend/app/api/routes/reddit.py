"""
Reddit subscription API endpoints.

This module provides REST API endpoints for managing Reddit subreddit subscriptions,
including subreddit search, subscription management, and manual refresh triggers.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_active_user
from app.core.config import settings
from app.db.deps import get_db
from app.models.content import Channel, ContentItem, UserSubscription, ProcessingStatus
from app.models.user import User, ContentSourceType
from app.schemas.reddit import (
    RedditSubredditInfo,
    RedditSubredditSearchRequest,
    RedditSubredditSearchResponse,
    RedditRefreshResponse,
    RedditSubscriptionCreate,
    RedditSubscriptionList,
    RedditSubscriptionResponse,
    RedditSubscriptionStats,
    RedditSubscriptionUpdate,
    MessageResponse,
)
from app.services.reddit import (
    RedditService,
    RedditAPIError,
    SubredditNotFoundError,
)
from app.services.reddit_quota_tracker import get_reddit_quota_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reddit", tags=["Reddit"])


# ========================================
# Helper Functions
# ========================================


def _channel_to_subreddit_info(channel: Channel) -> RedditSubredditInfo:
    """Convert Channel model to RedditSubredditInfo schema."""
    return RedditSubredditInfo(
        name=channel.source_identifier,
        title=channel.name,
        description=channel.description or '',
        icon_url=channel.thumbnail_url or '',
        banner_url='',  # Can be populated from metadata if needed
        subscribers=channel.subscriber_count or 0,
        over18=False,  # Can be added to metadata if needed
        public=True,   # Private subreddits won't be in system
        url=f"https://reddit.com/r/{channel.source_identifier}",
        created_at=str(channel.created_at) if channel.created_at else None,
    )


async def _get_or_create_channel(
    db: AsyncSession,
    reddit: RedditService,
    subreddit_name: str
) -> Channel:
    """
    Get existing channel from database or create a new one.
    
    Args:
        db: Database session
        reddit: Reddit service instance
        subreddit_name: Subreddit name (without r/)
        
    Returns:
        Channel model instance
        
    Raises:
        SubredditNotFoundError: If subreddit doesn't exist on Reddit
        RedditAPIError: For other Reddit API errors
    """
    # Check if channel exists in database
    result = await db.execute(
        select(Channel).where(
            Channel.source_type == ContentSourceType.REDDIT,
            Channel.source_identifier == subreddit_name.lower()
        )
    )
    channel = result.scalar_one_or_none()
    
    if channel:
        logger.info(f"Found existing subreddit in database: r/{subreddit_name}")
        return channel
    
    # Fetch from Reddit
    logger.info(f"Fetching subreddit from Reddit: r/{subreddit_name}")
    subreddit_info = reddit.get_subreddit_by_name(subreddit_name)
    
    # Create new channel
    channel = Channel(
        source_type=ContentSourceType.REDDIT,
        source_identifier=subreddit_info['name'].lower(),
        name=subreddit_info['title'],
        description=subreddit_info['description'],
        thumbnail_url=subreddit_info['icon_img'],
        subscriber_count=subreddit_info['subscribers'],
        is_active=True,
        metadata={
            'over18': subreddit_info['over18'],
            'public': subreddit_info['public'],
            'banner_img': subreddit_info['banner_img'],
            'url': subreddit_info['url'],
        }
    )
    
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    
    logger.info(f"Created new channel for r/{subreddit_name} (ID: {channel.id})")
    return channel


def _get_subscription_settings(subscription: UserSubscription) -> dict:
    """Extract subscription settings from extra_settings JSONB."""
    extra = subscription.extra_settings or {}
    return {
        'comment_limit': extra.get('comment_limit', 20),
        'min_score': extra.get('min_score', 10),
        'min_comments': extra.get('min_comments', 3),
    }


# ========================================
# API Endpoints
# ========================================


@router.post(
    "/search",
    response_model=RedditSubredditSearchResponse,
    summary="Search/validate a subreddit",
    description="Search for a subreddit by name or URL and check if already subscribed"
)
async def search_subreddit(
    request: RedditSubredditSearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RedditSubredditSearchResponse:
    """
    Search for a subreddit and validate it exists.
    
    This endpoint:
    1. Validates the subreddit query format
    2. Fetches subreddit info from Reddit
    3. Checks if user is already subscribed
    
    Returns subreddit information if found.
    """
    try:
        reddit = RedditService()
        
        # Extract subreddit name from query
        subreddit_name = reddit.extract_subreddit_name(request.query)
        
        # Fetch subreddit info
        subreddit_info = reddit.get_subreddit_by_name(subreddit_name)
        
        # Check if already subscribed
        result = await db.execute(
            select(Channel, UserSubscription)
            .join(UserSubscription, Channel.id == UserSubscription.channel_id)
            .where(
                Channel.source_type == ContentSourceType.REDDIT,
                Channel.source_identifier == subreddit_name.lower(),
                UserSubscription.user_id == current_user.id
            )
        )
        row = result.first()
        
        already_subscribed = row is not None
        subscription_id = row[1].id if row else None
        
        return RedditSubredditSearchResponse(
            found=True,
            subreddit=RedditSubredditInfo(
                name=subreddit_info['name'],
                title=subreddit_info['title'],
                description=subreddit_info['description'],
                icon_url=subreddit_info['icon_img'],
                banner_url=subreddit_info['banner_img'],
                subscribers=subreddit_info['subscribers'],
                over18=subreddit_info['over18'],
                public=subreddit_info['public'],
                url=subreddit_info['url'],
                created_at=str(subreddit_info['created_utc']),
            ),
            already_subscribed=already_subscribed,
            subscription_id=subscription_id,
        )
        
    except SubredditNotFoundError as e:
        return RedditSubredditSearchResponse(
            found=False,
            subreddit=None,
            already_subscribed=False,
            subscription_id=None,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RedditAPIError as e:
        logger.error(f"Reddit API error during search: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reddit API is currently unavailable"
        )
    except Exception as e:
        logger.error(f"Unexpected error during subreddit search: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.post(
    "/subscribe",
    response_model=RedditSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to a subreddit",
    description="Create a new subscription to a Reddit subreddit"
)
async def subscribe_to_subreddit(
    request: RedditSubscriptionCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RedditSubscriptionResponse:
    """
    Subscribe to a subreddit.
    
    This endpoint:
    1. Validates the subreddit exists
    2. Creates or finds the Channel record
    3. Creates a UserSubscription
    4. Triggers initial content fetch (async)
    """
    try:
        reddit = RedditService()
        
        # Get or create channel
        channel = await _get_or_create_channel(db, reddit, request.subreddit_name)
        
        # Check if already subscribed
        result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == current_user.id,
                UserSubscription.channel_id == channel.id
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Already subscribed to r/{request.subreddit_name}"
            )
        
        # Create subscription
        subscription = UserSubscription(
            user_id=current_user.id,
            channel_id=channel.id,
            is_active=True,
            custom_display_name=request.custom_display_name,
            notification_enabled=request.notification_enabled,
            extra_settings={
                'comment_limit': request.comment_limit,
                'min_score': request.min_score,
                'min_comments': request.min_comments,
            }
        )
        
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
        
        logger.info(
            f"User {current_user.id} subscribed to r/{request.subreddit_name} "
            f"(subscription ID: {subscription.id})"
        )
        
        # Trigger initial fetch
        from app.tasks.reddit_tasks import fetch_reddit_subreddit_content
        fetch_reddit_subreddit_content.delay(channel.id)
        
        # Build response
        settings_dict = _get_subscription_settings(subscription)
        
        return RedditSubscriptionResponse(
            id=subscription.id,
            user_id=subscription.user_id,
            subreddit=_channel_to_subreddit_info(channel),
            is_active=subscription.is_active,
            custom_display_name=subscription.custom_display_name,
            notification_enabled=subscription.notification_enabled,
            comment_limit=settings_dict['comment_limit'],
            min_score=settings_dict['min_score'],
            min_comments=settings_dict['min_comments'],
            last_shown_at=subscription.last_shown_at,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )
        
    except SubredditNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except RedditAPIError as e:
        logger.error(f"Reddit API error during subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reddit API is currently unavailable"
        )
    except Exception as e:
        logger.error(f"Unexpected error during subscription: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.get(
    "/subscriptions",
    response_model=RedditSubscriptionList,
    summary="List user's Reddit subscriptions",
    description="Get all Reddit subreddit subscriptions for the current user"
)
async def list_subscriptions(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RedditSubscriptionList:
    """
    List all Reddit subscriptions for the current user.
    
    Optionally filter by active status.
    """
    try:
        # Build query
        query = (
            select(UserSubscription, Channel)
            .join(Channel, UserSubscription.channel_id == Channel.id)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.REDDIT
            )
        )
        
        if is_active is not None:
            query = query.where(UserSubscription.is_active == is_active)
        
        # Execute query
        result = await db.execute(query)
        rows = result.all()
        
        # Build response
        subscriptions = []
        for subscription, channel in rows:
            settings_dict = _get_subscription_settings(subscription)
            subscriptions.append(
                RedditSubscriptionResponse(
                    id=subscription.id,
                    user_id=subscription.user_id,
                    subreddit=_channel_to_subreddit_info(channel),
                    is_active=subscription.is_active,
                    custom_display_name=subscription.custom_display_name,
                    notification_enabled=subscription.notification_enabled,
                    comment_limit=settings_dict['comment_limit'],
                    min_score=settings_dict['min_score'],
                    min_comments=settings_dict['min_comments'],
                    last_shown_at=subscription.last_shown_at,
                    created_at=subscription.created_at,
                    updated_at=subscription.updated_at,
                )
            )
        
        # Calculate stats
        total = len(subscriptions)
        active_count = sum(1 for s in subscriptions if s.is_active)
        paused_count = total - active_count
        
        return RedditSubscriptionList(
            subscriptions=subscriptions,
            total=total,
            active_count=active_count,
            paused_count=paused_count,
        )
        
    except Exception as e:
        logger.error(f"Error listing subscriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.get(
    "/subscriptions/{subscription_id}",
    response_model=RedditSubscriptionResponse,
    summary="Get single Reddit subscription",
    description="Get details of a specific Reddit subscription"
)
async def get_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RedditSubscriptionResponse:
    """Get details of a specific subscription."""
    try:
        result = await db.execute(
            select(UserSubscription, Channel)
            .join(Channel, UserSubscription.channel_id == Channel.id)
            .where(
                UserSubscription.id == subscription_id,
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.REDDIT
            )
        )
        row = result.first()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subscription {subscription_id} not found"
            )
        
        subscription, channel = row
        settings_dict = _get_subscription_settings(subscription)
        
        return RedditSubscriptionResponse(
            id=subscription.id,
            user_id=subscription.user_id,
            subreddit=_channel_to_subreddit_info(channel),
            is_active=subscription.is_active,
            custom_display_name=subscription.custom_display_name,
            notification_enabled=subscription.notification_enabled,
            comment_limit=settings_dict['comment_limit'],
            min_score=settings_dict['min_score'],
            min_comments=settings_dict['min_comments'],
            last_shown_at=subscription.last_shown_at,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting subscription {subscription_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.patch(
    "/subscriptions/{subscription_id}",
    response_model=RedditSubscriptionResponse,
    summary="Update Reddit subscription",
    description="Update settings for a Reddit subscription"
)
async def update_subscription(
    subscription_id: int,
    request: RedditSubscriptionUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RedditSubscriptionResponse:
    """Update subscription settings."""
    try:
        # Get subscription
        result = await db.execute(
            select(UserSubscription, Channel)
            .join(Channel, UserSubscription.channel_id == Channel.id)
            .where(
                UserSubscription.id == subscription_id,
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.REDDIT
            )
        )
        row = result.first()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subscription {subscription_id} not found"
            )
        
        subscription, channel = row
        
        # Update fields
        if request.is_active is not None:
            subscription.is_active = request.is_active
        if request.custom_display_name is not None:
            subscription.custom_display_name = request.custom_display_name
        if request.notification_enabled is not None:
            subscription.notification_enabled = request.notification_enabled
        
        # Update extra_settings
        extra = subscription.extra_settings or {}
        if request.comment_limit is not None:
            extra['comment_limit'] = request.comment_limit
        if request.min_score is not None:
            extra['min_score'] = request.min_score
        if request.min_comments is not None:
            extra['min_comments'] = request.min_comments
        subscription.extra_settings = extra
        
        subscription.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(subscription)
        
        logger.info(f"Updated subscription {subscription_id}")
        
        settings_dict = _get_subscription_settings(subscription)
        
        return RedditSubscriptionResponse(
            id=subscription.id,
            user_id=subscription.user_id,
            subreddit=_channel_to_subreddit_info(channel),
            is_active=subscription.is_active,
            custom_display_name=subscription.custom_display_name,
            notification_enabled=subscription.notification_enabled,
            comment_limit=settings_dict['comment_limit'],
            min_score=settings_dict['min_score'],
            min_comments=settings_dict['min_comments'],
            last_shown_at=subscription.last_shown_at,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating subscription {subscription_id}: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.delete(
    "/subscriptions/{subscription_id}",
    response_model=MessageResponse,
    summary="Unsubscribe from subreddit",
    description="Delete a Reddit subscription"
)
async def unsubscribe(
    subscription_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Delete a subscription."""
    try:
        result = await db.execute(
            select(UserSubscription)
            .where(
                UserSubscription.id == subscription_id,
                UserSubscription.user_id == current_user.id
            )
        )
        subscription = result.scalar_one_or_none()
        
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subscription {subscription_id} not found"
            )
        
        await db.delete(subscription)
        await db.commit()
        
        logger.info(f"Deleted subscription {subscription_id}")
        
        return MessageResponse(
            message=f"Successfully unsubscribed from subreddit",
            success=True
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting subscription {subscription_id}: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.post(
    "/subscriptions/{subscription_id}/refresh",
    response_model=RedditRefreshResponse,
    summary="Manually refresh subreddit content",
    description="Trigger immediate content fetch for a subreddit"
)
async def refresh_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RedditRefreshResponse:
    """Manually trigger content refresh for a subscription."""
    try:
        # Get subscription
        result = await db.execute(
            select(UserSubscription, Channel)
            .join(Channel, UserSubscription.channel_id == Channel.id)
            .where(
                UserSubscription.id == subscription_id,
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.REDDIT
            )
        )
        row = result.first()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subscription {subscription_id} not found"
            )
        
        subscription, channel = row
        
        # Trigger fetch task
        from app.tasks.reddit_tasks import fetch_reddit_subreddit_content
        task = fetch_reddit_subreddit_content.delay(channel.id)
        task_id = task.id
        
        logger.info(
            f"Triggered manual refresh for r/{channel.source_identifier} "
            f"(subscription {subscription_id})"
        )
        
        return RedditRefreshResponse(
            success=True,
            message=f"Refresh triggered for r/{channel.source_identifier}",
            task_id=task_id,
            estimated_posts=100,  # Configurable
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing subscription {subscription_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.get(
    "/stats",
    response_model=RedditSubscriptionStats,
    summary="Get Reddit subscription statistics",
    description="Get aggregated statistics about user's Reddit subscriptions"
)
async def get_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RedditSubscriptionStats:
    """Get statistics about user's Reddit subscriptions and content."""
    try:
        # Count subscriptions
        subscriptions_result = await db.execute(
            select(func.count(UserSubscription.id), UserSubscription.is_active)
            .join(Channel, UserSubscription.channel_id == Channel.id)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.REDDIT
            )
            .group_by(UserSubscription.is_active)
        )
        
        subscription_counts = {}
        for count, is_active in subscriptions_result:
            subscription_counts[is_active] = count
        
        total_subscriptions = sum(subscription_counts.values())
        active_subscriptions = subscription_counts.get(True, 0)
        paused_subscriptions = subscription_counts.get(False, 0)
        
        # Count total subreddits in system
        total_subreddits_result = await db.execute(
            select(func.count(Channel.id.distinct()))
            .where(Channel.source_type == ContentSourceType.REDDIT)
        )
        total_subreddits = total_subreddits_result.scalar() or 0
        
        # Count posts fetched
        posts_result = await db.execute(
            select(func.count(ContentItem.id))
            .join(Channel, ContentItem.channel_id == Channel.id)
            .join(UserSubscription, Channel.id == UserSubscription.channel_id)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.REDDIT
            )
        )
        total_posts = posts_result.scalar() or 0
        
        # Count posts in last 7 days
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent_posts_result = await db.execute(
            select(func.count(ContentItem.id))
            .join(Channel, ContentItem.channel_id == Channel.id)
            .join(UserSubscription, Channel.id == UserSubscription.channel_id)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.REDDIT,
                ContentItem.published_at >= seven_days_ago
            )
        )
        recent_posts = recent_posts_result.scalar() or 0
        
        # Get last refresh time
        last_refresh_result = await db.execute(
            select(func.max(ContentItem.created_at))
            .join(Channel, ContentItem.channel_id == Channel.id)
            .join(UserSubscription, Channel.id == UserSubscription.channel_id)
            .where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.REDDIT
            )
        )
        last_refresh = last_refresh_result.scalar()
        
        # Calculate average engagement score (from metadata)
        # This will be more accurate once we implement engagement scoring
        
        return RedditSubscriptionStats(
            total_subscriptions=total_subscriptions,
            active_subscriptions=active_subscriptions,
            paused_subscriptions=paused_subscriptions,
            total_subreddits_in_system=total_subreddits,
            total_posts_fetched=total_posts,
            posts_in_last_7_days=recent_posts,
            average_engagement_score=None,  # TODO: Calculate from metadata
            last_refresh=last_refresh,
        )
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


# ========================================
# Quota Monitoring Endpoints (Admin/Monitoring)
# ========================================


@router.get(
    "/quota",
    summary="Get Reddit API quota usage",
    description="Get current Reddit API quota statistics (monitoring endpoint)"
)
async def get_quota_stats(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Get current Reddit API quota usage statistics.
    
    Shows:
    - Current minute usage
    - Current 10-minute usage
    - Today's total requests
    - Breakdown by operation type
    """
    try:
        tracker = get_reddit_quota_tracker()
        stats = await tracker.get_quota_stats()
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting quota stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.get(
    "/quota/history",
    summary="Get Reddit API quota history",
    description="Get historical Reddit API quota usage (monitoring endpoint)"
)
async def get_quota_history(
    days: int = Query(7, ge=1, le=30, description="Number of days to retrieve"),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Get historical Reddit API quota usage for past N days.
    
    Useful for:
    - Capacity planning
    - Usage trend analysis
    - Identifying quota issues
    """
    try:
        tracker = get_reddit_quota_tracker()
        history = await tracker.get_quota_history(days=days)
        
        return {
            'days': days,
            'history': history,
        }
        
    except Exception as e:
        logger.error(f"Error getting quota history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )

