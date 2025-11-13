"""
Reddit Quota Helpers for Celery Tasks

Helper functions and decorators for Reddit API quota management in Celery tasks.
"""

import logging
from functools import wraps
from typing import Callable, Any

from celery.exceptions import Retry

from app.services.reddit_quota_tracker import get_reddit_quota_tracker

logger = logging.getLogger(__name__)


async def check_reddit_quota_before_task(operation_type: str = 'general') -> bool:
    """
    Check if Reddit API quota allows making a request.
    
    Args:
        operation_type: Type of operation for tracking
        
    Returns:
        True if quota is available
        
    Raises:
        Retry: If quota is exceeded (for Celery task retry)
    """
    tracker = get_reddit_quota_tracker()
    
    if not await tracker.can_make_request():
        logger.warning(
            f"Reddit API quota exceeded before {operation_type} operation, "
            "task will retry in 60 seconds"
        )
        # Let task retry after delay
        return False
    
    # Track the request
    await tracker.track_request(operation_type)
    return True


async def wait_for_reddit_quota(
    operation_type: str = 'general',
    max_wait_seconds: int = 60
) -> bool:
    """
    Wait until Reddit API quota is available.
    
    Args:
        operation_type: Type of operation for tracking
        max_wait_seconds: Maximum time to wait
        
    Returns:
        True if quota became available, False if timeout
    """
    tracker = get_reddit_quota_tracker()
    
    # Wait if needed
    if not await tracker.wait_if_needed(max_wait_seconds):
        logger.error(
            f"Reddit API quota: Could not get quota after waiting {max_wait_seconds}s"
        )
        return False
    
    # Track the request
    await tracker.track_request(operation_type)
    return True


def with_reddit_quota(operation_type: str = 'general'):
    """
    Decorator for Celery tasks that use Reddit API.
    
    Checks quota before executing task, automatically retries if quota exceeded.
    
    Usage:
        @celery_app.task
        @with_reddit_quota('subreddit_fetch')
        def my_reddit_task(arg1, arg2):
            # Task implementation
            pass
    
    Args:
        operation_type: Type of operation for tracking
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracker = get_reddit_quota_tracker()
            
            # Check quota
            if not await tracker.can_make_request():
                logger.warning(
                    f"Reddit API quota exceeded for {operation_type}, "
                    "retrying in 60 seconds"
                )
                # If this is a Celery task, raise Retry
                if hasattr(func, 'retry'):
                    raise Retry(countdown=60)
                else:
                    # Not a Celery task, wait
                    await tracker.wait_if_needed(60)
            
            # Track request
            await tracker.track_request(operation_type)
            
            # Execute function
            return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            import asyncio
            return asyncio.run(async_wrapper(*args, **kwargs))
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class RedditQuotaContext:
    """
    Context manager for Reddit API quota tracking.
    
    Usage:
        async with RedditQuotaContext('posts_fetch'):
            # Make Reddit API call
            posts = reddit.get_subreddit_posts(...)
    """
    
    def __init__(self, operation_type: str = 'general'):
        self.operation_type = operation_type
        self.tracker = get_reddit_quota_tracker()
    
    async def __aenter__(self):
        """Check and wait for quota before entering context."""
        await self.tracker.wait_if_needed(max_wait_seconds=60)
        await self.tracker.track_request(self.operation_type)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Nothing to do on exit."""
        pass





