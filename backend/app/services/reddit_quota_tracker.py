"""
Reddit Quota Tracker Service

Tracks Reddit API usage to prevent rate limiting and service disruptions.

Reddit API Rate Limits:
- 60 requests per minute (standard OAuth)
- 600 requests per 10 minutes
- PRAW handles basic rate limiting, but we track for monitoring and planning

This service:
- Tracks request counts per minute (sliding window)
- Prevents exceeding safe thresholds (55/minute to leave buffer)
- Stores historical data for analytics
- Provides monitoring endpoints
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.db.redis import get_redis_client

logger = logging.getLogger(__name__)


class RedditQuotaTracker:
    """
    Track and manage Reddit API quota usage.
    
    Uses Redis for high-performance quota tracking with sliding windows.
    """
    
    # Quota limits (leave buffer)
    MAX_REQUESTS_PER_MINUTE = 55  # Actual limit is 60, leave buffer
    MAX_REQUESTS_PER_10_MINUTES = 580  # Actual limit is 600, leave buffer
    
    # Redis key prefixes
    KEY_PREFIX_MINUTE = "reddit:quota:minute"
    KEY_PREFIX_HISTORY = "reddit:quota:history"
    KEY_PREFIX_10MIN = "reddit:quota:10min"
    
    # TTL
    MINUTE_TTL = 120  # 2 minutes
    TEN_MIN_TTL = 900  # 15 minutes
    HISTORY_TTL = 86400 * 30  # 30 days
    
    def __init__(self, redis_client: Optional[Redis] = None):
        """
        Initialize quota tracker.
        
        Args:
            redis_client: Redis client instance. If None, gets default client.
        """
        self.redis = redis_client or get_redis_client()
        if not self.redis:
            raise ValueError("Redis client is required for quota tracking")
    
    def _get_minute_key(self, timestamp: Optional[datetime] = None) -> str:
        """Get Redis key for current minute."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        minute_str = timestamp.strftime('%Y-%m-%d-%H-%M')
        return f"{self.KEY_PREFIX_MINUTE}:{minute_str}"
    
    def _get_10min_key(self, timestamp: Optional[datetime] = None) -> str:
        """Get Redis key for current 10-minute window."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        # Round down to 10-minute window
        minute = (timestamp.minute // 10) * 10
        window_time = timestamp.replace(minute=minute, second=0, microsecond=0)
        window_str = window_time.strftime('%Y-%m-%d-%H-%M')
        return f"{self.KEY_PREFIX_10MIN}:{window_str}"
    
    def _get_history_key(self, date: Optional[datetime] = None) -> str:
        """Get Redis key for daily history."""
        if date is None:
            date = datetime.now(timezone.utc)
        date_str = date.strftime('%Y-%m-%d')
        return f"{self.KEY_PREFIX_HISTORY}:{date_str}"
    
    async def track_request(self, operation_type: str) -> None:
        """
        Track a Reddit API request.
        
        Args:
            operation_type: Type of operation (for analytics):
                - subreddit_fetch: Get subreddit info
                - posts_fetch: List posts
                - post_details: Get single post
                - comments_fetch: Get comments
        """
        try:
            now = datetime.now(timezone.utc)
            
            # Increment minute counter
            minute_key = self._get_minute_key(now)
            self.redis.incr(minute_key)
            self.redis.expire(minute_key, self.MINUTE_TTL)
            
            # Increment 10-minute counter
            ten_min_key = self._get_10min_key(now)
            self.redis.incr(ten_min_key)
            self.redis.expire(ten_min_key, self.TEN_MIN_TTL)
            
            # Update daily history (JSONB-like structure)
            history_key = self._get_history_key(now)
            self.redis.hincrby(history_key, 'total', 1)
            self.redis.hincrby(history_key, operation_type, 1)
            self.redis.expire(history_key, self.HISTORY_TTL)
            
            logger.debug(f"Tracked Reddit API request: {operation_type}")
            
        except RedisError as e:
            logger.error(f"Redis error tracking request: {e}")
            # Don't raise - quota tracking failure shouldn't block API calls
    
    async def can_make_request(self) -> bool:
        """
        Check if we can make a Reddit API request without exceeding limits.
        
        Returns:
            True if under quota limits
        """
        try:
            # Check minute limit
            minute_count = await self.get_current_minute_usage()
            if minute_count >= self.MAX_REQUESTS_PER_MINUTE:
                logger.warning(
                    f"Reddit API quota: Minute limit reached ({minute_count}/{self.MAX_REQUESTS_PER_MINUTE})"
                )
                return False
            
            # Check 10-minute limit
            ten_min_count = await self.get_current_10min_usage()
            if ten_min_count >= self.MAX_REQUESTS_PER_10_MINUTES:
                logger.warning(
                    f"Reddit API quota: 10-minute limit reached ({ten_min_count}/{self.MAX_REQUESTS_PER_10_MINUTES})"
                )
                return False
            
            return True
            
        except RedisError as e:
            logger.error(f"Redis error checking quota: {e}")
            # On Redis error, allow request (fail open)
            return True
    
    async def get_current_minute_usage(self) -> int:
        """Get request count for current minute."""
        try:
            minute_key = self._get_minute_key()
            count = self.redis.get(minute_key)
            return int(count) if count else 0
        except RedisError as e:
            logger.error(f"Redis error getting minute usage: {e}")
            return 0
    
    async def get_current_10min_usage(self) -> int:
        """Get request count for current 10-minute window."""
        try:
            ten_min_key = self._get_10min_key()
            count = self.redis.get(ten_min_key)
            return int(count) if count else 0
        except RedisError as e:
            logger.error(f"Redis error getting 10-minute usage: {e}")
            return 0
    
    async def get_quota_stats(self) -> Dict:
        """
        Get current quota statistics.
        
        Returns:
            Dict with quota usage information
        """
        try:
            minute_usage = await self.get_current_minute_usage()
            ten_min_usage = await self.get_current_10min_usage()
            
            # Get today's history
            history_key = self._get_history_key()
            today_stats = self.redis.hgetall(history_key)
            
            # Decode bytes to strings/ints
            today_stats = {
                k.decode('utf-8'): int(v.decode('utf-8'))
                for k, v in today_stats.items()
            } if today_stats else {}
            
            return {
                'minute_usage': minute_usage,
                'minute_limit': self.MAX_REQUESTS_PER_MINUTE,
                'minute_percentage': round(minute_usage / self.MAX_REQUESTS_PER_MINUTE * 100, 1),
                'ten_min_usage': ten_min_usage,
                'ten_min_limit': self.MAX_REQUESTS_PER_10_MINUTES,
                'ten_min_percentage': round(ten_min_usage / self.MAX_REQUESTS_PER_10_MINUTES * 100, 1),
                'can_make_request': minute_usage < self.MAX_REQUESTS_PER_MINUTE and ten_min_usage < self.MAX_REQUESTS_PER_10_MINUTES,
                'today_total': today_stats.get('total', 0),
                'today_by_operation': {
                    k: v for k, v in today_stats.items() if k != 'total'
                },
            }
            
        except RedisError as e:
            logger.error(f"Redis error getting stats: {e}")
            return {
                'error': str(e),
                'can_make_request': True,  # Fail open
            }
    
    async def get_quota_history(self, days: int = 7) -> List[Dict]:
        """
        Get quota usage history for past N days.
        
        Args:
            days: Number of days to retrieve
            
        Returns:
            List of daily stats
        """
        try:
            history = []
            now = datetime.now(timezone.utc)
            
            for i in range(days):
                date = now - timedelta(days=i)
                history_key = self._get_history_key(date)
                
                day_stats = self.redis.hgetall(history_key)
                if day_stats:
                    day_stats = {
                        k.decode('utf-8'): int(v.decode('utf-8'))
                        for k, v in day_stats.items()
                    }
                    day_stats['date'] = date.strftime('%Y-%m-%d')
                    history.append(day_stats)
            
            # Sort by date descending
            history.sort(key=lambda x: x['date'], reverse=True)
            
            return history
            
        except RedisError as e:
            logger.error(f"Redis error getting history: {e}")
            return []
    
    async def reset_quota(self) -> None:
        """
        Reset all quota counters (admin operation).
        
        WARNING: Use with caution. This clears all tracking data.
        """
        try:
            # Get all quota keys
            minute_keys = self.redis.keys(f"{self.KEY_PREFIX_MINUTE}:*")
            ten_min_keys = self.redis.keys(f"{self.KEY_PREFIX_10MIN}:*")
            
            # Delete all quota keys
            if minute_keys:
                self.redis.delete(*minute_keys)
            if ten_min_keys:
                self.redis.delete(*ten_min_keys)
            
            logger.warning("Reddit API quota counters have been reset")
            
        except RedisError as e:
            logger.error(f"Redis error resetting quota: {e}")
            raise
    
    async def wait_if_needed(self, max_wait_seconds: int = 60) -> bool:
        """
        Wait if quota is exceeded, up to max_wait_seconds.
        
        Args:
            max_wait_seconds: Maximum time to wait
            
        Returns:
            True if quota is available (after waiting if needed)
            False if max wait time exceeded
        """
        import asyncio
        
        waited = 0
        while not await self.can_make_request():
            if waited >= max_wait_seconds:
                logger.warning(
                    f"Reddit API quota: Waited {waited}s, still over limit"
                )
                return False
            
            # Wait 5 seconds and check again
            await asyncio.sleep(5)
            waited += 5
            logger.debug(f"Reddit API quota: Waiting for quota ({waited}s)")
        
        return True


# ========================================
# Singleton Instance
# ========================================

_tracker_instance: Optional[RedditQuotaTracker] = None


def get_reddit_quota_tracker() -> RedditQuotaTracker:
    """
    Get singleton instance of RedditQuotaTracker.
    
    Returns:
        RedditQuotaTracker instance
    """
    global _tracker_instance
    
    if _tracker_instance is None:
        _tracker_instance = RedditQuotaTracker()
    
    return _tracker_instance





