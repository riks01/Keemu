"""
API route modules.

Import all route modules here for easy access.
"""

from app.api.routes import auth, youtube, reddit, blogs, chat

__all__ = ["auth", "youtube", "reddit", "blogs", "chat"]
