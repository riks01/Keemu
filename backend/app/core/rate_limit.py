"""
Rate Limiting Middleware

Provides rate limiting for API endpoints using Redis.
Protects API from abuse and ensures fair usage across users.
"""

import logging
from typing import Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.db.redis import get_redis, RedisRateLimiter
from app.core.config import settings

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware for FastAPI.
    
    Uses Redis sliding window algorithm for accurate rate limiting.
    Different limits for authenticated vs unauthenticated users.
    """
    
    def __init__(self, app, **kwargs):
        super().__init__(app)
        self.redis = None
        self.rate_limiter = None
        
        # Rate limits (requests per minute)
        self.anonymous_limit = getattr(settings, 'RATE_LIMIT_ANONYMOUS', 20)
        self.authenticated_limit = getattr(settings, 'RATE_LIMIT_AUTHENTICATED', 100)
        self.window_seconds = 60  # 1 minute window
    
    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting."""
        
        # Initialize Redis connection if needed
        if self.redis is None:
            try:
                self.redis = await get_redis()
                self.rate_limiter = RedisRateLimiter(self.redis)
            except Exception as e:
                logger.error(f"Failed to initialize Redis for rate limiting: {e}")
                # Continue without rate limiting if Redis is unavailable
                return await call_next(request)
        
        # Skip rate limiting for health checks and docs
        if request.url.path in ['/health', '/docs', '/redoc', '/openapi.json']:
            return await call_next(request)
        
        # Determine rate limit based on authentication
        user_id = self._get_user_id(request)
        
        if user_id:
            # Authenticated user
            rate_key = f"user:{user_id}"
            max_requests = self.authenticated_limit
        else:
            # Anonymous user (use IP address)
            client_ip = self._get_client_ip(request)
            rate_key = f"ip:{client_ip}"
            max_requests = self.anonymous_limit
        
        # Check rate limit
        try:
            is_allowed, current_count = await self.rate_limiter.is_allowed(
                rate_key,
                max_requests,
                self.window_seconds
            )
            
            if not is_allowed:
                logger.warning(
                    f"Rate limit exceeded for {rate_key}: "
                    f"{current_count}/{max_requests} requests in {self.window_seconds}s"
                )
                
                remaining = await self.rate_limiter.get_remaining(
                    rate_key, max_requests, self.window_seconds
                )
                
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Rate limit exceeded. Please try again later.",
                        "limit": max_requests,
                        "window_seconds": self.window_seconds,
                        "remaining": remaining
                    },
                    headers={
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": str(remaining),
                        "X-RateLimit-Reset": str(self.window_seconds),
                        "Retry-After": str(self.window_seconds)
                    }
                )
            
            # Add rate limit headers to response
            response = await call_next(request)
            
            remaining = await self.rate_limiter.get_remaining(
                rate_key, max_requests, self.window_seconds
            )
            
            response.headers["X-RateLimit-Limit"] = str(max_requests)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(self.window_seconds)
            
            return response
            
        except Exception as e:
            logger.error(f"Error in rate limiting: {e}")
            # Continue without rate limiting if error occurs
            return await call_next(request)
    
    def _get_user_id(self, request: Request) -> Optional[str]:
        """Extract user ID from request if authenticated."""
        # Check if user is authenticated (set by auth middleware)
        if hasattr(request.state, 'user'):
            return str(request.state.user.id)
        return None
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address, handling proxies."""
        # Check X-Forwarded-For header (for proxies/load balancers)
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            # Take first IP in chain
            return forwarded_for.split(',')[0].strip()
        
        # Check X-Real-IP header
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip
        
        # Fall back to direct client IP
        if request.client:
            return request.client.host
        
        return 'unknown'


# ========================================
# Endpoint-Specific Rate Limiting
# ========================================

async def check_rate_limit(
    request: Request,
    max_requests: int = 10,
    window_seconds: int = 60,
    key_prefix: str = "endpoint"
) -> None:
    """
    Check rate limit for specific endpoint.
    
    Use this as a dependency in endpoints that need custom rate limits.
    
    Example:
        @router.post("/expensive-operation")
        async def expensive_op(
            _: None = Depends(lambda req: check_rate_limit(req, max_requests=5))
        ):
            ...
    
    Args:
        request: FastAPI request object
        max_requests: Maximum requests allowed
        window_seconds: Time window in seconds
        key_prefix: Prefix for rate limit key
        
    Raises:
        HTTPException: If rate limit exceeded
    """
    try:
        redis = await get_redis()
        rate_limiter = RedisRateLimiter(redis)
        
        # Build rate key
        if hasattr(request.state, 'user'):
            user_id = request.state.user.id
            rate_key = f"{key_prefix}:user:{user_id}"
        else:
            client_ip = request.client.host if request.client else 'unknown'
            rate_key = f"{key_prefix}:ip:{client_ip}"
        
        # Check limit
        is_allowed, current_count = await rate_limiter.is_allowed(
            rate_key,
            max_requests,
            window_seconds
        )
        
        if not is_allowed:
            remaining = await rate_limiter.get_remaining(
                rate_key, max_requests, window_seconds
            )
            
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Rate limit exceeded for this endpoint",
                    "limit": max_requests,
                    "window_seconds": window_seconds,
                    "remaining": remaining
                },
                headers={
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": str(remaining),
                    "Retry-After": str(window_seconds)
                }
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking rate limit: {e}")
        # Allow request if rate limiting fails
        pass

