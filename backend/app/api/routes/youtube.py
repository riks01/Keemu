"""
YouTube subscription API endpoints.

This module provides REST API endpoints for managing YouTube channel subscriptions,
including channel search, subscription management, and manual refresh triggers.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_active_user
from app.core.config import settings
from app.db.deps import get_db
from app.models.content import Channel, ContentItem, UserSubscription, ProcessingStatus
from app.models.user import User, ContentSourceType
from app.schemas.youtube import (
    YouTubeChannelInfo,
    YouTubeChannelSearchRequest,
    YouTubeChannelSearchResponse,
    YouTubeRefreshResponse,
    YouTubeSubscriptionCreate,
    YouTubeSubscriptionList,
    YouTubeSubscriptionResponse,
    YouTubeSubscriptionStats,
    YouTubeSubscriptionUpdate,
    MessageResponse,
)
from app.services.youtube import (
    YouTubeService,
    YouTubeAPIError,
    YouTubeChannelNotFoundError,
    YouTubeQuotaExceededError,
)
from app.services.quota_tracker import get_quota_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/youtube", tags=["YouTube"])


# ========================================
# Helper Functions
# ========================================

def _channel_to_info(channel: Channel) -> YouTubeChannelInfo:
    """Convert Channel model to YouTubeChannelInfo schema."""
    return YouTubeChannelInfo(
        channel_id=channel.source_identifier,
        name=channel.name,
        description=channel.description,
        thumbnail_url=channel.thumbnail_url,
        subscriber_count=channel.subscriber_count,
        video_count=0,  # Will be populated from YouTube API
        view_count=0,    # Will be populated from YouTube API
        custom_url=None, # Will be populated from YouTube API
        published_at=str(channel.created_at)
    )


async def _get_or_create_channel(
    db: AsyncSession,
    youtube: YouTubeService,
    channel_id: str
) -> Channel:
    """
    Get existing channel from database or create a new one.
    
    Args:
        db: Database session
        youtube: YouTube service instance
        channel_id: YouTube channel ID
        
    Returns:
        Channel model instance
        
    Raises:
        YouTubeChannelNotFoundError: If channel doesn't exist on YouTube
        YouTubeAPIError: For other YouTube API errors
    """
    # Check if channel exists in database
    result = await db.execute(
        select(Channel).where(
            Channel.source_type == ContentSourceType.YOUTUBE,
            Channel.source_identifier == channel_id
        )
    )
    channel = result.scalar_one_or_none()
    
    if channel:
        logger.info(f"Found existing channel in database: {channel_id}")
        return channel
    
    # Fetch from YouTube
    logger.info(f"Fetching channel from YouTube: {channel_id}")
    channel_info = await youtube.get_channel_by_id(channel_id)
    
    # Create new channel
    channel = Channel(
        source_type=ContentSourceType.YOUTUBE,
        source_identifier=channel_info['id'],
        name=channel_info['title'],
        description=channel_info.get('description'),
        thumbnail_url=channel_info.get('thumbnail_url'),
        subscriber_count=0,  # Will be incremented when users subscribe
        is_active=True
    )
    
    db.add(channel)
    await db.flush()  # Get channel.id
    
    logger.info(f"Created new channel in database: {channel.name} ({channel_id})")
    return channel


# ========================================
# Endpoints
# ========================================

@router.post(
    "/search",
    response_model=YouTubeChannelSearchResponse,
    summary="Search for a YouTube channel",
    description=(
        "Search for a YouTube channel by URL, channel ID, username, or handle. "
        "Returns channel information and whether user is already subscribed."
    ),
    responses={
        200: {"description": "Channel found successfully"},
        404: {"description": "Channel not found"},
        403: {"description": "YouTube API quota exceeded"},
        500: {"description": "YouTube API error"},
    }
)
async def search_channel(
    request: YouTubeChannelSearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Search for a YouTube channel and check if user is already subscribed.
    
    Supports multiple input formats:
    - YouTube URLs (channel, user, custom)
    - Channel IDs (UCxxx...)
    - Usernames
    - Handles (@username)
    """
    try:
        youtube = YouTubeService()
        
        # Determine search method based on query format
        query = request.query.strip()
        
        if query.startswith('http'):
            # URL format
            channel_info = await youtube.get_channel_by_url(query)
        elif query.startswith('UC'):
            # Channel ID
            channel_info = await youtube.get_channel_by_id(query)
        elif query.startswith('@'):
            # Handle
            channel_info = await youtube.get_channel_by_custom_url(query)
        else:
            # Username or handle without @
            try:
                channel_info = await youtube.get_channel_by_username(query)
            except YouTubeChannelNotFoundError:
                # Try as handle
                channel_info = await youtube.get_channel_by_custom_url(query)
        
        # Check if user is already subscribed
        result = await db.execute(
            select(UserSubscription).join(Channel).where(
                UserSubscription.user_id == current_user.id,
                Channel.source_type == ContentSourceType.YOUTUBE,
                Channel.source_identifier == channel_info['id']
            )
        )
        subscription = result.scalar_one_or_none()
        
        return YouTubeChannelSearchResponse(
            found=True,
            channel=YouTubeChannelInfo(
                channel_id=channel_info['id'],
                name=channel_info['title'],
                description=channel_info.get('description'),
                thumbnail_url=channel_info.get('thumbnail_url'),
                subscriber_count=channel_info.get('subscriber_count', 0),
                video_count=channel_info.get('video_count', 0),
                view_count=channel_info.get('view_count', 0),
                custom_url=channel_info.get('custom_url'),
                published_at=channel_info.get('published_at')
            ),
            already_subscribed=subscription is not None,
            subscription_id=subscription.id if subscription else None
        )
    
    except YouTubeChannelNotFoundError as e:
        return YouTubeChannelSearchResponse(
            found=False,
            channel=None,
            already_subscribed=False
        )
    
    except YouTubeQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="YouTube API quota exceeded. Please try again later."
        )
    
    except YouTubeAPIError as e:
        logger.error(f"YouTube API error during search: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"YouTube API error: {str(e)}"
        )


@router.post(
    "/subscribe",
    response_model=YouTubeSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to a YouTube channel",
    description="Create a new subscription to a YouTube channel",
    responses={
        201: {"description": "Successfully subscribed"},
        400: {"description": "Already subscribed or invalid channel"},
        403: {"description": "YouTube API quota exceeded"},
        404: {"description": "Channel not found on YouTube"},
    }
)
async def subscribe_to_channel(
    subscription_data: YouTubeSubscriptionCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Subscribe to a YouTube channel.
    
    This will:
    1. Validate the channel exists on YouTube
    2. Create Channel record if it doesn't exist in database
    3. Create UserSubscription record
    4. Increment channel subscriber count
    5. (Future) Trigger immediate content fetch
    """
    try:
        youtube = YouTubeService()
        
        # Get or create channel
        channel = await _get_or_create_channel(
            db, youtube, subscription_data.channel_id
        )
        
        # Check if already subscribed
        result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == current_user.id,
                UserSubscription.channel_id == channel.id
            )
        )
        existing_sub = result.scalar_one_or_none()
        
        if existing_sub:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Already subscribed to {channel.name}"
            )
        
        # Create subscription
        subscription = UserSubscription(
            user_id=current_user.id,
            channel_id=channel.id,
            is_active=True,
            custom_display_name=subscription_data.custom_display_name,
            notification_enabled=subscription_data.notification_enabled
        )
        
        db.add(subscription)
        
        # Increment subscriber count
        channel.subscriber_count += 1
        
        await db.commit()
        await db.refresh(subscription)
        await db.refresh(channel)
        
        logger.info(
            f"User {current_user.id} subscribed to channel {channel.name} "
            f"({channel.source_identifier})"
        )
        
        # Trigger immediate content fetch
        from app.tasks.youtube_tasks import fetch_youtube_channel_content
        fetch_task = fetch_youtube_channel_content.apply_async(
            args=[channel.id],
            countdown=10  # Wait 10 seconds to allow response to return
        )
        logger.info(f"Queued content fetch for {channel.name} (task: {fetch_task.id})")
        
        # Get channel info from YouTube for response
        channel_info = await youtube.get_channel_by_id(channel.source_identifier)
        
        return YouTubeSubscriptionResponse(
            id=subscription.id,
            user_id=subscription.user_id,
            channel=YouTubeChannelInfo(
                channel_id=channel.source_identifier,
                name=channel.name,
                description=channel.description,
                thumbnail_url=channel.thumbnail_url,
                subscriber_count=channel_info.get('subscriber_count', 0),
                video_count=channel_info.get('video_count', 0),
                view_count=channel_info.get('view_count', 0),
                custom_url=channel_info.get('custom_url'),
                published_at=channel_info.get('published_at')
            ),
            is_active=subscription.is_active,
            custom_display_name=subscription.custom_display_name,
            notification_enabled=subscription.notification_enabled,
            last_shown_at=subscription.last_shown_at,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at
        )
    
    except YouTubeChannelNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"YouTube channel not found: {subscription_data.channel_id}"
        )
    
    except YouTubeQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="YouTube API quota exceeded. Please try again later."
        )
    
    except YouTubeAPIError as e:
        logger.error(f"YouTube API error during subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"YouTube API error: {str(e)}"
        )


@router.get(
    "/subscriptions",
    response_model=YouTubeSubscriptionList,
    summary="List user's YouTube subscriptions",
    description="Get all YouTube channels the user is subscribed to",
    responses={
        200: {"description": "Subscriptions retrieved successfully"},
    }
)
async def list_subscriptions(
    active_only: bool = Query(
        False,
        description="If true, only return active (not paused) subscriptions"
    ),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all YouTube subscriptions for the current user.
    
    Optionally filter to show only active subscriptions.
    """
    # Build query
    query = (
        select(UserSubscription)
        .join(Channel)
        .where(
            UserSubscription.user_id == current_user.id,
            Channel.source_type == ContentSourceType.YOUTUBE
        )
        .order_by(UserSubscription.created_at.desc())
    )
    
    if active_only:
        query = query.where(UserSubscription.is_active == True)
    
    result = await db.execute(query)
    subscriptions = result.scalars().all()
    
    # Get YouTube service for fetching latest channel info
    youtube = YouTubeService()
    
    # Build response
    subscription_responses = []
    for sub in subscriptions:
        # Get channel
        channel_result = await db.execute(
            select(Channel).where(Channel.id == sub.channel_id)
        )
        channel = channel_result.scalar_one()
        
        # Get latest info from YouTube (cached in channel model)
        try:
            channel_info = await youtube.get_channel_by_id(channel.source_identifier)
        except Exception as e:
            logger.warning(f"Failed to get YouTube info for {channel.name}: {e}")
            channel_info = {
                'subscriber_count': 0,
                'video_count': 0,
                'view_count': 0
            }
        
        subscription_responses.append(
            YouTubeSubscriptionResponse(
                id=sub.id,
                user_id=sub.user_id,
                channel=YouTubeChannelInfo(
                    channel_id=channel.source_identifier,
                    name=channel.name,
                    description=channel.description,
                    thumbnail_url=channel.thumbnail_url,
                    subscriber_count=channel_info.get('subscriber_count', 0),
                    video_count=channel_info.get('video_count', 0),
                    view_count=channel_info.get('view_count', 0),
                    custom_url=channel_info.get('custom_url'),
                    published_at=str(channel.created_at)
                ),
                is_active=sub.is_active,
                custom_display_name=sub.custom_display_name,
                notification_enabled=sub.notification_enabled,
                last_shown_at=sub.last_shown_at,
                created_at=sub.created_at,
                updated_at=sub.updated_at
            )
        )
    
    # Calculate counts
    total = len(subscriptions)
    active_count = sum(1 for sub in subscriptions if sub.is_active)
    paused_count = total - active_count
    
    return YouTubeSubscriptionList(
        subscriptions=subscription_responses,
        total=total,
        active_count=active_count,
        paused_count=paused_count
    )


@router.get(
    "/subscriptions/{subscription_id}",
    response_model=YouTubeSubscriptionResponse,
    summary="Get a specific subscription",
    description="Get details of a specific YouTube subscription",
    responses={
        200: {"description": "Subscription retrieved successfully"},
        404: {"description": "Subscription not found"},
    }
)
async def get_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific subscription."""
    result = await db.execute(
        select(UserSubscription).where(
            UserSubscription.id == subscription_id,
            UserSubscription.user_id == current_user.id
        )
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Get channel
    channel_result = await db.execute(
        select(Channel).where(Channel.id == subscription.channel_id)
    )
    channel = channel_result.scalar_one()
    
    # Get latest YouTube info
    youtube = YouTubeService()
    try:
        channel_info = await youtube.get_channel_by_id(channel.source_identifier)
    except Exception as e:
        logger.warning(f"Failed to get YouTube info for {channel.name}: {e}")
        channel_info = {
            'subscriber_count': 0,
            'video_count': 0,
            'view_count': 0
        }
    
    return YouTubeSubscriptionResponse(
        id=subscription.id,
        user_id=subscription.user_id,
        channel=YouTubeChannelInfo(
            channel_id=channel.source_identifier,
            name=channel.name,
            description=channel.description,
            thumbnail_url=channel.thumbnail_url,
            subscriber_count=channel_info.get('subscriber_count', 0),
            video_count=channel_info.get('video_count', 0),
            view_count=channel_info.get('view_count', 0),
            custom_url=channel_info.get('custom_url'),
            published_at=str(channel.created_at)
        ),
        is_active=subscription.is_active,
        custom_display_name=subscription.custom_display_name,
        notification_enabled=subscription.notification_enabled,
        last_shown_at=subscription.last_shown_at,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at
    )


@router.patch(
    "/subscriptions/{subscription_id}",
    response_model=YouTubeSubscriptionResponse,
    summary="Update a subscription",
    description="Update settings for a YouTube subscription",
    responses={
        200: {"description": "Subscription updated successfully"},
        404: {"description": "Subscription not found"},
    }
)
async def update_subscription(
    subscription_id: int,
    update_data: YouTubeSubscriptionUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update subscription settings.
    
    Can update:
    - is_active (pause/resume subscription)
    - custom_display_name (rename channel)
    - notification_enabled (toggle notifications)
    """
    result = await db.execute(
        select(UserSubscription).where(
            UserSubscription.id == subscription_id,
            UserSubscription.user_id == current_user.id
        )
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(subscription, field, value)
    
    await db.commit()
    await db.refresh(subscription)
    
    logger.info(f"Updated subscription {subscription_id}: {update_dict}")
    
    # Return updated subscription
    return await get_subscription(subscription_id, current_user, db)


@router.delete(
    "/subscriptions/{subscription_id}",
    response_model=MessageResponse,
    summary="Unsubscribe from a channel",
    description="Delete a YouTube subscription (soft delete)",
    responses={
        200: {"description": "Successfully unsubscribed"},
        404: {"description": "Subscription not found"},
    }
)
async def unsubscribe(
    subscription_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Unsubscribe from a YouTube channel.
    
    This performs a soft delete (sets is_active=False) to preserve history.
    To hard delete, use the query parameter ?hard_delete=true
    """
    result = await db.execute(
        select(UserSubscription).where(
            UserSubscription.id == subscription_id,
            UserSubscription.user_id == current_user.id
        )
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Get channel to decrement subscriber count
    channel_result = await db.execute(
        select(Channel).where(Channel.id == subscription.channel_id)
    )
    channel = channel_result.scalar_one()
    
    # Soft delete (deactivate)
    subscription.is_active = False
    channel.subscriber_count = max(0, channel.subscriber_count - 1)
    
    await db.commit()
    
    logger.info(
        f"User {current_user.id} unsubscribed from {channel.name} "
        f"(subscription {subscription_id})"
    )
    
    return MessageResponse(
        message=f"Successfully unsubscribed from {channel.name}",
        success=True
    )


@router.post(
    "/subscriptions/{subscription_id}/refresh",
    response_model=YouTubeRefreshResponse,
    summary="Manually trigger content refresh",
    description="Trigger an immediate fetch of new content for this channel",
    responses={
        200: {"description": "Refresh triggered successfully"},
        404: {"description": "Subscription not found"},
    }
)
async def refresh_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger a content refresh for a subscription.
    
    This will queue a Celery task to fetch latest videos from the channel.
    """
    result = await db.execute(
        select(UserSubscription).where(
            UserSubscription.id == subscription_id,
            UserSubscription.user_id == current_user.id
        )
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Get channel
    channel_result = await db.execute(
        select(Channel).where(Channel.id == subscription.channel_id)
    )
    channel = channel_result.scalar_one()
    
    # Trigger Celery task
    from app.tasks.youtube_tasks import fetch_youtube_channel_content
    task = fetch_youtube_channel_content.apply_async(
        args=[subscription.channel_id],
        countdown=5  # Start in 5 seconds
    )
    
    logger.info(
        f"Manual refresh triggered for subscription {subscription_id}, "
        f"channel: {channel.name} (task: {task.id})"
    )
    
    return YouTubeRefreshResponse(
        success=True,
        message=f"Refresh task queued for {channel.name}",
        task_id=task.id,
        estimated_videos=settings.YOUTUBE_MAX_VIDEOS_PER_FETCH
    )


@router.get(
    "/stats",
    response_model=YouTubeSubscriptionStats,
    summary="Get YouTube subscription statistics",
    description="Get statistics about user's YouTube subscriptions and content",
    responses={
        200: {"description": "Statistics retrieved successfully"},
    }
)
async def get_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get statistics about user's YouTube subscriptions."""
    # Count subscriptions
    total_result = await db.execute(
        select(func.count(UserSubscription.id))
        .join(Channel)
        .where(
            UserSubscription.user_id == current_user.id,
            Channel.source_type == ContentSourceType.YOUTUBE
        )
    )
    total_subscriptions = total_result.scalar_one()
    
    # Count active subscriptions
    active_result = await db.execute(
        select(func.count(UserSubscription.id))
        .join(Channel)
        .where(
            UserSubscription.user_id == current_user.id,
            Channel.source_type == ContentSourceType.YOUTUBE,
            UserSubscription.is_active == True
        )
    )
    active_subscriptions = active_result.scalar_one()
    
    # Total channels in system
    channels_result = await db.execute(
        select(func.count(Channel.id)).where(
            Channel.source_type == ContentSourceType.YOUTUBE
        )
    )
    total_channels_in_system = channels_result.scalar_one()
    
    # Get user's subscribed channel IDs
    channel_ids_result = await db.execute(
        select(UserSubscription.channel_id)
        .join(Channel)
        .where(
            UserSubscription.user_id == current_user.id,
            Channel.source_type == ContentSourceType.YOUTUBE
        )
    )
    user_channel_ids = [row[0] for row in channel_ids_result.all()]
    
    # Total videos fetched from user's subscriptions
    if user_channel_ids:
        videos_result = await db.execute(
            select(func.count(ContentItem.id))
            .where(
                ContentItem.channel_id.in_(user_channel_ids),
                ContentItem.processing_status == ProcessingStatus.PROCESSED
            )
        )
        total_videos_fetched = videos_result.scalar_one()
        
        # Videos in last 7 days
        from datetime import datetime, timedelta, timezone
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
        recent_videos_result = await db.execute(
            select(func.count(ContentItem.id))
            .where(
                ContentItem.channel_id.in_(user_channel_ids),
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date
            )
        )
        videos_in_last_7_days = recent_videos_result.scalar_one()
        
        # Get most recent refresh time
        last_refresh_result = await db.execute(
            select(func.max(Channel.last_fetched_at))
            .where(Channel.id.in_(user_channel_ids))
        )
        last_refresh = last_refresh_result.scalar_one()
    else:
        total_videos_fetched = 0
        videos_in_last_7_days = 0
        last_refresh = None
    
    return YouTubeSubscriptionStats(
        total_subscriptions=total_subscriptions,
        active_subscriptions=active_subscriptions,
        paused_subscriptions=total_subscriptions - active_subscriptions,
        total_channels_in_system=total_channels_in_system,
        total_videos_fetched=total_videos_fetched,
        videos_in_last_7_days=videos_in_last_7_days,
        last_refresh=last_refresh
    )


@router.get(
    "/quota",
    summary="Get YouTube API quota usage",
    description="Get current YouTube API quota usage and statistics",
    responses={
        200: {"description": "Quota information retrieved successfully"},
    }
)
async def get_quota_status(
    current_user: User = Depends(get_current_active_user)
):
    """
    Get YouTube API quota usage statistics.
    
    Shows:
    - Daily quota limit
    - Current usage
    - Remaining quota
    - Operation breakdown
    - Time until reset
    - Health status
    """
    try:
        quota_tracker = await get_quota_tracker()
        
        # Get comprehensive stats
        stats = await quota_tracker.get_usage_stats()
        health = await quota_tracker.get_quota_health_status()
        
        return {
            **stats,
            'health': health,
            'can_fetch': {
                '1_channel': await quota_tracker.can_afford_operation(1, 50),
                '10_channels': await quota_tracker.can_afford_operation(10, 50),
                '50_channels': await quota_tracker.can_afford_operation(50, 50)
            }
        }
    
    except Exception as e:
        logger.error(f"Error getting quota status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve quota status: {str(e)}"
        )


@router.get(
    "/quota/history",
    summary="Get historical quota usage",
    description="Get quota usage for the past N days",
    responses={
        200: {"description": "Quota history retrieved successfully"},
    }
)
async def get_quota_history(
    days: int = Query(7, ge=1, le=30, description="Number of days of history"),
    current_user: User = Depends(get_current_active_user)
):
    """Get historical quota usage."""
    try:
        quota_tracker = await get_quota_tracker()
        history = await quota_tracker.get_historical_usage(days)
        
        return {
            'days': days,
            'history': history,
            'daily_limit': settings.YOUTUBE_QUOTA_LIMIT_PER_DAY
        }
    
    except Exception as e:
        logger.error(f"Error getting quota history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve quota history: {str(e)}"
        )

