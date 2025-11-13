"""
YouTube API Quota Tracker

Manages YouTube Data API quota usage to prevent exceeding daily limits.
Uses Redis for distributed quota tracking across multiple workers.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
from enum import Enum

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class YouTubeAPIOperation(str, Enum):
    """YouTube API operations and their quota costs."""
    
    # Search operations
    SEARCH_LIST = "search.list"  # 100 units
    
    # Video operations
    VIDEOS_LIST = "videos.list"  # 1 unit
    
    # Channel operations
    CHANNELS_LIST = "channels.list"  # 1 unit
    
    # Playlist operations
    PLAYLIST_ITEMS_LIST = "playlistItems.list"  # 1 unit
    
    # Comment operations
    COMMENTS_LIST = "comments.list"  # 1 unit
    COMMENT_THREADS_LIST = "commentThreads.list"  # 1 unit


# Quota costs for each operation
QUOTA_COSTS = {
    YouTubeAPIOperation.SEARCH_LIST: 100,
    YouTubeAPIOperation.VIDEOS_LIST: 1,
    YouTubeAPIOperation.CHANNELS_LIST: 1,
    YouTubeAPIOperation.PLAYLIST_ITEMS_LIST: 1,
    YouTubeAPIOperation.COMMENTS_LIST: 1,
    YouTubeAPIOperation.COMMENT_THREADS_LIST: 1,
}


class QuotaExceededError(Exception):
    """Raised when quota limit would be exceeded."""
    pass


class YouTubeQuotaTracker:
    """
    Tracks YouTube API quota usage using Redis.
    
    Features:
    - Daily quota tracking
    - Distributed tracking across workers
    - Quota reservation before API calls
    - Usage statistics and alerts
    - Automatic daily reset
    """
    
    def __init__(self, redis: Redis):
        self.redis = redis
        self.daily_limit = settings.YOUTUBE_QUOTA_LIMIT_PER_DAY
        
    # ========================================
    # Redis Key Helpers
    # ========================================
    
    def _get_quota_key(self, date: Optional[datetime] = None) -> str:
        """Get Redis key for quota tracking."""
        if date is None:
            date = datetime.now(timezone.utc)
        date_str = date.strftime("%Y-%m-%d")
        return f"youtube:quota:{date_str}"
    
    def _get_operation_key(self, operation: YouTubeAPIOperation, date: Optional[datetime] = None) -> str:
        """Get Redis key for operation count."""
        if date is None:
            date = datetime.now(timezone.utc)
        date_str = date.strftime("%Y-%m-%d")
        return f"youtube:quota:{date_str}:op:{operation.value}"
    
    def _get_ttl_seconds(self) -> int:
        """Calculate seconds until midnight Pacific Time (YouTube quota reset)."""
        now = datetime.now(timezone.utc)
        # YouTube quota resets at midnight Pacific Time (UTC-8 or UTC-7 depending on DST)
        # For simplicity, using UTC midnight + 8 hours
        tomorrow = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        seconds = int((tomorrow - now).total_seconds())
        return max(seconds, 3600)  # At least 1 hour
    
    # ========================================
    # Core Quota Management
    # ========================================
    
    async def get_current_usage(self) -> int:
        """Get current quota usage for today."""
        key = self._get_quota_key()
        usage = await self.redis.get(key)
        return int(usage) if usage else 0
    
    async def get_remaining_quota(self) -> int:
        """Get remaining quota for today."""
        usage = await self.get_current_usage()
        return max(0, self.daily_limit - usage)
    
    async def check_quota_available(self, operation: YouTubeAPIOperation, count: int = 1) -> bool:
        """
        Check if enough quota is available for operation.
        
        Args:
            operation: YouTube API operation
            count: Number of operations (e.g., batch of 50 videos)
            
        Returns:
            True if quota is available, False otherwise
        """
        cost = QUOTA_COSTS.get(operation, 1) * count
        remaining = await self.get_remaining_quota()
        return remaining >= cost
    
    async def reserve_quota(
        self,
        operation: YouTubeAPIOperation,
        count: int = 1,
        force: bool = False
    ) -> bool:
        """
        Reserve quota for an operation before making API call.
        
        Args:
            operation: YouTube API operation
            count: Number of operations
            force: If True, allow exceeding quota (emergency use only)
            
        Returns:
            True if quota reserved successfully
            
        Raises:
            QuotaExceededError: If quota would be exceeded and force=False
        """
        cost = QUOTA_COSTS.get(operation, 1) * count
        
        # Check if quota available
        if not force:
            remaining = await self.get_remaining_quota()
            if remaining < cost:
                logger.warning(
                    f"Insufficient quota for {operation.value}: "
                    f"need {cost}, have {remaining}"
                )
                raise QuotaExceededError(
                    f"Insufficient YouTube API quota. Need {cost} units, "
                    f"have {remaining} remaining today."
                )
        
        # Increment quota usage
        quota_key = self._get_quota_key()
        op_key = self._get_operation_key(operation)
        
        # Use Redis pipeline for atomic operation
        pipe = self.redis.pipeline()
        pipe.incrby(quota_key, cost)
        pipe.expire(quota_key, self._get_ttl_seconds())
        pipe.incr(op_key)
        pipe.expire(op_key, self._get_ttl_seconds())
        await pipe.execute()
        
        new_usage = await self.get_current_usage()
        logger.info(
            f"Reserved {cost} quota units for {operation.value} x{count}. "
            f"Total usage: {new_usage}/{self.daily_limit}"
        )
        
        return True
    
    async def refund_quota(self, operation: YouTubeAPIOperation, count: int = 1):
        """
        Refund quota if operation failed before API call.
        
        Use this if you reserved quota but the operation failed
        before making the actual API call.
        """
        cost = QUOTA_COSTS.get(operation, 1) * count
        quota_key = self._get_quota_key()
        
        await self.redis.decrby(quota_key, cost)
        
        logger.info(f"Refunded {cost} quota units for {operation.value}")
    
    # ========================================
    # Statistics & Monitoring
    # ========================================
    
    async def get_usage_stats(self) -> Dict:
        """Get detailed quota usage statistics."""
        usage = await self.get_current_usage()
        remaining = self.daily_limit - usage
        percentage = (usage / self.daily_limit) * 100 if self.daily_limit > 0 else 0
        
        # Get operation breakdown
        operations = {}
        for op in YouTubeAPIOperation:
            op_key = self._get_operation_key(op)
            count = await self.redis.get(op_key)
            if count:
                count = int(count)
                cost = QUOTA_COSTS.get(op, 1) * count
                operations[op.value] = {
                    'count': count,
                    'total_cost': cost
                }
        
        # Calculate time until reset
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        hours_until_reset = (tomorrow - now).total_seconds() / 3600
        
        return {
            'daily_limit': self.daily_limit,
            'used': usage,
            'remaining': remaining,
            'percentage_used': round(percentage, 2),
            'operations': operations,
            'hours_until_reset': round(hours_until_reset, 2),
            'reset_at': tomorrow.isoformat()
        }
    
    async def get_historical_usage(self, days: int = 7) -> Dict:
        """Get historical quota usage for past N days."""
        history = {}
        now = datetime.now(timezone.utc)
        
        for i in range(days):
            date = now - timedelta(days=i)
            key = self._get_quota_key(date)
            usage = await self.redis.get(key)
            
            date_str = date.strftime("%Y-%m-%d")
            history[date_str] = int(usage) if usage else 0
        
        return history
    
    async def is_quota_critical(self, threshold: float = 0.9) -> bool:
        """
        Check if quota usage is critical (above threshold).
        
        Args:
            threshold: Percentage threshold (0.0-1.0)
            
        Returns:
            True if usage >= threshold * daily_limit
        """
        usage = await self.get_current_usage()
        critical_level = self.daily_limit * threshold
        return usage >= critical_level
    
    async def get_quota_health_status(self) -> Dict:
        """
        Get quota health status with color-coded levels.
        
        Returns:
            {
                'status': 'healthy' | 'warning' | 'critical',
                'usage': int,
                'remaining': int,
                'message': str
            }
        """
        usage = await self.get_current_usage()
        remaining = self.daily_limit - usage
        percentage = (usage / self.daily_limit) * 100
        
        if percentage < 70:
            status = 'healthy'
            message = 'Quota usage is normal'
        elif percentage < 90:
            status = 'warning'
            message = f'Quota usage is high ({percentage:.1f}%)'
        else:
            status = 'critical'
            message = f'Quota usage is critical ({percentage:.1f}%)! Limit non-essential operations.'
        
        return {
            'status': status,
            'usage': usage,
            'remaining': remaining,
            'percentage': round(percentage, 2),
            'message': message
        }
    
    # ========================================
    # Quota Estimation
    # ========================================
    
    def estimate_fetch_cost(
        self,
        num_channels: int = 1,
        videos_per_channel: int = 50
    ) -> int:
        """
        Estimate quota cost for fetching content.
        
        Args:
            num_channels: Number of channels to fetch
            videos_per_channel: Videos per channel
            
        Returns:
            Estimated quota cost
        """
        cost = 0
        
        # Channel details: 1 unit per channel
        cost += num_channels * QUOTA_COSTS[YouTubeAPIOperation.CHANNELS_LIST]
        
        # Video list: 1 unit per channel (gets up to 50 videos)
        cost += num_channels * QUOTA_COSTS[YouTubeAPIOperation.PLAYLIST_ITEMS_LIST]
        
        # Video details: 1 unit per 50 videos (batch request)
        total_videos = num_channels * videos_per_channel
        video_batches = (total_videos + 49) // 50  # Round up
        cost += video_batches * QUOTA_COSTS[YouTubeAPIOperation.VIDEOS_LIST]
        
        return cost
    
    async def can_afford_operation(
        self,
        num_channels: int = 1,
        videos_per_channel: int = 50
    ) -> tuple[bool, int, int]:
        """
        Check if we can afford a fetch operation.
        
        Returns:
            (can_afford, estimated_cost, remaining_quota)
        """
        cost = self.estimate_fetch_cost(num_channels, videos_per_channel)
        remaining = await self.get_remaining_quota()
        return (remaining >= cost, cost, remaining)


# ========================================
# Dependency Injection
# ========================================

async def get_quota_tracker() -> YouTubeQuotaTracker:
    """Get YouTube quota tracker instance."""
    from app.db.redis import get_redis
    redis = await get_redis()
    return YouTubeQuotaTracker(redis)

