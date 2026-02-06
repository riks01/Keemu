"""
Main FastAPI application entry point.
"""

import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.celery import CeleryIntegration

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import init_db, close_db, check_db_health

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Validate environment variables before starting
from app.core.env_validation import validate_or_exit
validate_or_exit()

# Initialize Sentry for error tracking and monitoring
# Skip Sentry during tests to avoid shutdown logging errors
is_testing = "pytest" in sys.modules

if settings.SENTRY_DSN and not is_testing:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        release=f"{settings.APP_NAME}@0.1.0",
        # Performance monitoring
        traces_sample_rate=1.0 if settings.is_development else 0.1,  # 100% in dev, 10% in prod
        profiles_sample_rate=1.0 if settings.is_development else 0.1,
        # Integrations
        integrations=[
            FastApiIntegration(transaction_style="url"),
            SqlalchemyIntegration(),
            RedisIntegration(),
            CeleryIntegration(monitor_beat_tasks=True),
        ],
        # Additional options
        send_default_pii=False,  # Don't send personally identifiable information
        attach_stacktrace=True,
        debug=settings.is_development,
        # Custom tags
        before_send=lambda event, hint: _before_send_sentry(event, hint),
    )
    logger.info(
        "sentry_initialized",
        environment=settings.APP_ENV,
        traces_sample_rate=1.0 if settings.is_development else 0.1,
    )
else:
    logger.warning("sentry_not_configured", message="SENTRY_DSN not set, error tracking disabled")


def _before_send_sentry(event, hint):
    """
    Process Sentry events before sending.
    Add custom tags and filter sensitive data.
    """
    # Add custom tags
    event.setdefault("tags", {})
    event["tags"]["app_name"] = settings.APP_NAME
    event["tags"]["environment"] = settings.APP_ENV
    
    # Filter out health check errors (too noisy)
    if event.get("request", {}).get("url", "").endswith("/health"):
        return None
    
    return event


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan events.
    Handles startup and shutdown tasks.
    """
    # Startup
    logger.info(
        "starting_application",
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        version="0.1.0",
    )

    # Initialize database connection pool
    await init_db()
    
    # Initialize Redis connection
    from app.db.redis import init_redis
    try:
        await init_redis()
        logger.info("redis_initialized")
    except Exception as e:
        logger.error("redis_initialization_failed", error=str(e))
        # Continue startup even if Redis fails (graceful degradation)
    
    # Set global tags for Sentry
    if settings.SENTRY_DSN:
        sentry_sdk.set_tag("app_name", settings.APP_NAME)
        sentry_sdk.set_tag("environment", settings.APP_ENV)

    yield

    # Shutdown
    logger.info("shutting_down_application")
    
    # Close database connections
    await close_db()
    
    # Close Redis connections
    from app.db.redis import close_redis
    try:
        await close_redis()
        logger.info("redis_closed")
    except Exception as e:
        logger.error("redis_closure_failed", error=str(e))


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Content Intelligence Assistant - Backend API",
    version="0.1.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check() -> JSONResponse:
    """
    Basic health check endpoint for load balancers.
    Fast and lightweight - only checks if app is running.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "app_name": settings.APP_NAME,
            "version": "0.1.0",
        }
    )


@app.get("/health/detailed", tags=["health"])
async def detailed_health_check() -> JSONResponse:
    """
    Detailed health check endpoint for monitoring systems.
    Includes checks for all critical services.
    """
    import time
    from app.db.redis import check_redis_health
    
    start_time = time.time()
    health_status = {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "version": "0.1.0",
        "timestamp": time.time(),
        "checks": {}
    }
    
    # Check database
    db_start = time.time()
    db_healthy = await check_db_health()
    db_duration = (time.time() - db_start) * 1000  # Convert to ms
    
    health_status["checks"]["database"] = {
        "status": "connected" if db_healthy else "disconnected",
        "response_time_ms": round(db_duration, 2)
    }
    
    # Check Redis
    redis_start = time.time()
    redis_healthy = await check_redis_health()
    redis_duration = (time.time() - redis_start) * 1000
    
    health_status["checks"]["redis"] = {
        "status": "connected" if redis_healthy else "disconnected",
        "response_time_ms": round(redis_duration, 2)
    }
    
    # Check Sentry
    health_status["checks"]["sentry"] = {
        "status": "enabled" if settings.SENTRY_DSN else "disabled"
    }
    
    # Overall status
    all_healthy = db_healthy and redis_healthy
    health_status["status"] = "healthy" if all_healthy else "degraded"
    health_status["total_duration_ms"] = round((time.time() - start_time) * 1000, 2)
    
    status_code = 200 if all_healthy else 503
    
    return JSONResponse(
        status_code=status_code,
        content=health_status
    )


@app.get("/", tags=["root"])
async def root() -> JSONResponse:
    """
    Root endpoint.
    """
    return JSONResponse(
        content={
            "message": f"Welcome to {settings.APP_NAME} API",
            "version": "0.1.0",
            "docs": "/docs" if settings.DEBUG else "Documentation disabled in production",
        }
    )


@app.get("/metrics", tags=["monitoring"])
async def get_metrics() -> JSONResponse:
    """
    Application metrics endpoint for monitoring.
    Returns key operational metrics.
    """
    from sqlalchemy import text
    from app.db.session import engine
    
    metrics = {
        "app": {
            "name": settings.APP_NAME,
            "version": "0.1.0",
            "environment": settings.APP_ENV,
        },
        "database": {
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
        },
        "features": {
            "sentry_enabled": bool(settings.SENTRY_DSN),
            "email_notifications": settings.ENABLE_EMAIL_NOTIFICATIONS,
            "cost_tracking": settings.ENABLE_COST_TRACKING,
            "analytics": settings.ENABLE_ANALYTICS,
        }
    }
    
    # Get database statistics
    try:
        async with engine.connect() as conn:
            # Count total users
            result = await conn.execute(text("SELECT COUNT(*) FROM users"))
            metrics["database"]["total_users"] = result.scalar() or 0
            
            # Count total content items
            result = await conn.execute(text("SELECT COUNT(*) FROM content_items"))
            metrics["database"]["total_content_items"] = result.scalar() or 0
            
            # Count total chunks
            result = await conn.execute(text("SELECT COUNT(*) FROM content_chunks"))
            metrics["database"]["total_chunks"] = result.scalar() or 0
            
            # Count total conversations
            result = await conn.execute(text("SELECT COUNT(*) FROM conversations"))
            metrics["database"]["total_conversations"] = result.scalar() or 0
    except Exception as e:
        logger.error("metrics_database_query_failed", error=str(e))
        metrics["database"]["error"] = "Could not fetch database metrics"
    
    return JSONResponse(content=metrics)


# Include API routers
from app.api import api_router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    """
    Global exception handler for unhandled errors.
    """
    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
        method=request.method,
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_server_error",
                "message": "An unexpected error occurred. Please try again later.",
            }
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
