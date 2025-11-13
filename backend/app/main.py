"""
Main FastAPI application entry point.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

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
    
    # TODO: Initialize Redis connection
    # TODO: Load ML models (embedding model)
    # TODO: Verify external service connections

    yield

    # Shutdown
    logger.info("shutting_down_application")
    
    # Close database connections

    await close_db()
    
    # TODO: Close Redis connections
    # TODO: Cleanup resources


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
    Health check endpoint for monitoring.
    Includes database connectivity check.
    """

    db_healthy = await check_db_health()
    
    return JSONResponse(
        status_code=200 if db_healthy else 503,
        content={
            "status": "healthy" if db_healthy else "unhealthy",
            "app_name": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "version": "0.1.0",
            "database": "connected" if db_healthy else "disconnected",
        }
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
