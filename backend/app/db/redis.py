"""
Redis connection management.

Provides async Redis connection for:
- Celery broker/backend
- Rate limiting
- Quota tracking
- Caching
"""

import logging
from typing import Optional

from redis.asyncio import Redis, ConnectionPool
from redis import Redis as SyncRedis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global connection pool
_redis_pool: Optional[ConnectionPool] = None
_redis_client: Optional[Redis] = None
_sync_redis_client: Optional[SyncRedis] = None


async def init_redis() -> Redis:
    """
    Initialize Redis connection pool.
    
    Called during application startup.
    """
    global _redis_pool, _redis_client
    
    if _redis_pool is None:
        logger.info("Initializing Redis connection pool")
        
        # Parse Redis URL
        # Format: redis://localhost:6379/0
        redis_url = settings.CELERY_BROKER_URL
        
        _redis_pool = ConnectionPool.from_url(
            redis_url,
            decode_responses=True,  # Auto-decode bytes to strings
            max_connections=20,
            socket_connect_timeout=5,
            socket_keepalive=True
        )
        
        _redis_client = Redis(connection_pool=_redis_pool)
        
        # Test connection
        try:
            await _redis_client.ping()
            logger.info("Redis connection successful")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            raise
    
    return _redis_client


async def get_redis() -> Redis:
    """
    Get Redis client instance.
    
    Use this as a dependency in FastAPI endpoints or services.
    """
    if _redis_client is None:
        return await init_redis()
    return _redis_client


async def close_redis():
    """
    Close Redis connection pool.
    
    Called during application shutdown.
    """
    global _redis_pool, _redis_client, _sync_redis_client
    
    if _redis_client:
        logger.info("Closing Redis connection")
        await _redis_client.close()
        _redis_client = None
    
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None
    
    if _sync_redis_client:
        _sync_redis_client.close()
        _sync_redis_client = None


def get_redis_client() -> SyncRedis:
    """
    Get synchronous Redis client for quota tracking and other sync operations.
    
    Returns:
        Synchronous Redis client instance
    """
    global _sync_redis_client
    
    if _sync_redis_client is None:
        logger.info("Initializing sync Redis client")
        redis_url = settings.CELERY_BROKER_URL
        _sync_redis_client = SyncRedis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True
        )
        
        # Test connection
        try:
            _sync_redis_client.ping()
            logger.info("Sync Redis connection successful")
        except Exception as e:
            logger.error(f"Sync Redis connection failed: {e}")
            raise
    
    return _sync_redis_client


# ========================================
# Rate Limiting Helper
# ========================================

class RedisRateLimiter:
    """
    Simple rate limiter using Redis.
    
    Uses sliding window algorithm for accurate rate limiting.
    """
    
    def __init__(self, redis: Redis):
        self.redis = redis
    
    async def is_allowed(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, int]:
        """
        Check if request is allowed under rate limit.
        
        Args:
            key: Unique identifier (e.g., user_id, ip_address)
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
            
        Returns:
            (is_allowed, current_count)
        """
        import time
        
        now = time.time()
        window_start = now - window_seconds
        
        # Use sorted set for sliding window
        rate_key = f"rate_limit:{key}"
        
        # Remove old entries
        await self.redis.zremrangebyscore(rate_key, 0, window_start)
        
        # Count current requests
        current_count = await self.redis.zcard(rate_key)
        
        if current_count < max_requests:
            # Add this request
            await self.redis.zadd(rate_key, {str(now): now})
            await self.redis.expire(rate_key, window_seconds)
            return (True, current_count + 1)
        else:
            return (False, current_count)
    
    async def get_remaining(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> int:
        """Get remaining requests in current window."""
        import time
        
        now = time.time()
        window_start = now - window_seconds
        
        rate_key = f"rate_limit:{key}"
        
        # Remove old entries
        await self.redis.zremrangebyscore(rate_key, 0, window_start)
        
        # Count current requests
        current_count = await self.redis.zcard(rate_key)
        
        return max(0, max_requests - current_count)
    
    async def reset(self, key: str):
        """Reset rate limit for a key."""
        rate_key = f"rate_limit:{key}"
        await self.redis.delete(rate_key)


# ========================================
# Health Check
# ========================================

async def check_redis_health() -> bool:
    """
    Check if Redis is healthy and responsive.
    
    Returns:
        bool: True if Redis is healthy, False otherwise
    """
    try:
        redis = await get_redis()
        # Try to ping Redis
        response = await redis.ping()
        return response is True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False

