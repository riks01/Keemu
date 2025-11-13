"""Database utilities and session management."""

from app.db.base import Base, BaseModel, String50, String100, String255, String500, String1000
from app.db.deps import DBSession, DBTransaction, get_db, get_db_override
from app.db.session import (
    AsyncSessionLocal,
    check_db_health,
    close_db,
    engine,
    get_session,
    init_db,
)

__all__ = [
    # Base classes
    "Base",
    "BaseModel",
    # String types
    "String50",
    "String100",
    "String255",
    "String500",
    "String1000",
    # Session management
    "engine",
    "AsyncSessionLocal",
    "get_session",
    "init_db",
    "close_db",
    "check_db_health",
    # Dependencies
    "get_db",
    "DBSession",
    "DBTransaction",
    "get_db_override",
]
