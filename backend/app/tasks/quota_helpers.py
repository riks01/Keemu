"""
Quota management helpers for Celery tasks.

Provides utilities for checking and managing YouTube API quota
before executing tasks that make API calls.
"""

import logging
import asyncio
from typing import Optional

from app.services.quota_tracker import (
    YouTubeQuotaTracker,
    YouTubeAPIOperation,
    QuotaExceededError,
    get_quota_tracker
)

logger = logging.getLogger(__name__)


async def check_quota_before_fetch(
    num_channels: int = 1,
    videos_per_channel: int = 50
) -> tuple[bool, str]:
    """
    Check if we have enough quota for a fetch operation.
    
    Args:
        num_channels: Number of channels to fetch
        videos_per_channel: Videos per channel
        
    Returns:
        (can_proceed, message)
    """
    try:
        quota_tracker = await get_quota_tracker()
        
        # Check health status first
        health = await quota_tracker.get_quota_health_status()
        
        if health['status'] == 'critical':
            logger.warning(f"Quota critical: {health['message']}")
            # Still check if we can afford this specific operation
        
        # Check if we can afford the operation
        can_afford, cost, remaining = await quota_tracker.can_afford_operation(
            num_channels, videos_per_channel
        )
        
        if not can_afford:
            message = (
                f"Insufficient quota: need {cost} units, "
                f"have {remaining} remaining. "
                f"Operation will be retried after quota reset."
            )
            logger.warning(message)
            return (False, message)
        
        # Log quota usage intention
        percentage = (cost / quota_tracker.daily_limit) * 100
        logger.info(
            f"Quota check passed: {cost} units ({percentage:.1f}%) "
            f"for {num_channels} channels. Remaining: {remaining}"
        )
        
        return (True, f"Quota available: {remaining} units remaining")
    
    except Exception as e:
        logger.error(f"Error checking quota: {e}")
        # Allow operation if quota check fails (fail open)
        return (True, f"Quota check failed, proceeding anyway: {e}")


async def reserve_quota_for_fetch(
    num_channels: int = 1,
    videos_per_channel: int = 50,
    force: bool = False
) -> tuple[bool, Optional[str]]:
    """
    Reserve quota for a fetch operation.
    
    Args:
        num_channels: Number of channels
        videos_per_channel: Videos per channel
        force: Force reservation even if quota exceeded
        
    Returns:
        (success, error_message)
    """
    try:
        quota_tracker = await get_quota_tracker()
        
        # Calculate total cost
        cost = quota_tracker.estimate_fetch_cost(num_channels, videos_per_channel)
        
        # Reserve quota for channel listing
        await quota_tracker.reserve_quota(
            YouTubeAPIOperation.CHANNELS_LIST,
            count=num_channels,
            force=force
        )
        
        # Reserve quota for video listing
        await quota_tracker.reserve_quota(
            YouTubeAPIOperation.PLAYLIST_ITEMS_LIST,
            count=num_channels,
            force=force
        )
        
        # Reserve quota for video details (batched)
        total_videos = num_channels * videos_per_channel
        video_batches = (total_videos + 49) // 50
        await quota_tracker.reserve_quota(
            YouTubeAPIOperation.VIDEOS_LIST,
            count=video_batches,
            force=force
        )
        
        logger.info(f"Successfully reserved {cost} quota units")
        return (True, None)
    
    except QuotaExceededError as e:
        logger.error(f"Quota exceeded: {e}")
        return (False, str(e))
    
    except Exception as e:
        logger.error(f"Error reserving quota: {e}")
        return (False, str(e))


def sync_check_quota_before_fetch(
    num_channels: int = 1,
    videos_per_channel: int = 50
) -> tuple[bool, str]:
    """
    Synchronous wrapper for check_quota_before_fetch.
    
    Use this in Celery tasks.
    """
    return asyncio.run(check_quota_before_fetch(num_channels, videos_per_channel))


def sync_reserve_quota_for_fetch(
    num_channels: int = 1,
    videos_per_channel: int = 50,
    force: bool = False
) -> tuple[bool, Optional[str]]:
    """
    Synchronous wrapper for reserve_quota_for_fetch.
    
    Use this in Celery tasks.
    """
    return asyncio.run(reserve_quota_for_fetch(num_channels, videos_per_channel, force))


# ========================================
# Quota-Aware Task Decorator
# ========================================

def quota_aware_task(operation: YouTubeAPIOperation, cost_multiplier: int = 1):
    """
    Decorator for tasks that consume YouTube API quota.
    
    Automatically checks and reserves quota before task execution.
    
    Example:
        @celery_app.task
        @quota_aware_task(YouTubeAPIOperation.CHANNELS_LIST, cost_multiplier=1)
        def my_task(channel_id):
            # Task implementation
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                # Check quota
                can_proceed, message = sync_check_quota_before_fetch(1, 1)
                
                if not can_proceed:
                    logger.warning(f"Task {func.__name__} skipped due to quota: {message}")
                    return {
                        'success': False,
                        'error': 'quota_exceeded',
                        'message': message
                    }
                
                # Execute task
                return func(*args, **kwargs)
            
            except Exception as e:
                logger.error(f"Error in quota-aware task {func.__name__}: {e}")
                raise
        
        return wrapper
    return decorator

