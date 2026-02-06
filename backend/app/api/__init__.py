"""
API routes initialization.

This module aggregates all API routers and provides a single router
to include in the main application.
"""

from fastapi import APIRouter

from app.api.routes import auth, youtube, reddit, blogs, chat

# Create main API router
api_router = APIRouter()

# Include authentication routes
api_router.include_router(auth.router)

# Include YouTube routes
api_router.include_router(youtube.router)

# Include Reddit routes
api_router.include_router(reddit.router)

# Include Blog/RSS routes
api_router.include_router(blogs.router)

# Include Chat routes
api_router.include_router(chat.router)

# Future routers will be added here:
# api_router.include_router(users.router)
# api_router.include_router(content.router)
# api_router.include_router(summaries.router)
