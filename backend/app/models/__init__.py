"""
Database Models

This module contains all SQLAlchemy ORM models for the application.

Model Organization:
-------------------
Each model represents a database table and defines:
- Column structure (fields and their types)
- Relationships to other models
- Constraints (unique, nullable, etc.)
- Indexes for query performance

Import Structure:
-----------------
Import models from this module to ensure they're registered with SQLAlchemy:

    from app.models import User, Channel, ContentItem, UserSubscription

This ensures that:
1. Alembic can detect all models for migrations
2. Relationships work correctly
3. All models are available throughout the app
"""

from app.models.content import (
    Channel,
    ContentItem,
    ContentSourceType,
    ProcessingStatus,
    UserSubscription,
)
from app.models.user import (
    SummaryLength,
    UpdateFrequency,
    User,
    UserPreferences,
)

# Export all models and enums
__all__ = [
    # User models
    "User",
    "UserPreferences",
    # Content models
    "Channel",
    "UserSubscription",
    "ContentItem",
    # Enums
    "ContentSourceType",
    "ProcessingStatus",
    "SummaryLength",
    "UpdateFrequency",
]
