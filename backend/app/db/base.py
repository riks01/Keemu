"""
Database Base Classes and Common Utilities

This module provides the foundation for all database models in the application.

Key Concepts:
--------------
1. DeclarativeBase: SQLAlchemy's base class that enables ORM functionality
2. CommonTableAttributes: Shared columns/methods used across all models
3. orm_registry: Central registry that tracks all models and their metadata

Learning Resources:
- SQLAlchemy Declarative Base: https://docs.sqlalchemy.org/en/20/orm/declarative_config.html
- Table Naming Conventions: Helps with database migrations and readability
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, registry


# ================================
# Naming Convention for Constraints
# ================================
# This ensures consistent naming for database constraints (indexes, foreign keys, etc.)
# Benefits:
# - Alembic can track changes more reliably
# - Database administrators can identify constraints easily
# - Prevents naming conflicts across databases (PostgreSQL, MySQL, etc.)
#
# Format examples:
# - ix_users_email: Index on 'users' table, 'email' column
# - fk_posts_user_id_users: Foreign key from 'posts.user_id' to 'users'
# - pk_users: Primary key on 'users' table
convention = {
    "ix": "ix_%(column_0_label)s",  # Index
    "uq": "uq_%(table_name)s_%(column_0_name)s",  # Unique constraint
    "ck": "ck_%(table_name)s_%(constraint_name)s",  # Check constraint
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",  # Foreign key
    "pk": "pk_%(table_name)s",  # Primary key
}

# Create metadata with naming conventions
metadata = MetaData(naming_convention=convention)

# Create ORM registry - this tracks all our models
orm_registry = registry(metadata=metadata)


# ================================
# Base DeclarativeBase Class
# ================================
class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    
    Every model in our application will inherit from this class.
    SQLAlchemy uses this to:
    - Track model definitions
    - Generate SQL statements
    - Handle ORM mappings
    
    Usage:
        class User(Base):
            __tablename__ = "users"
            id: Mapped[int] = mapped_column(primary_key=True)
    """
    
    # Connect this base to our registry
    registry = orm_registry
    
    # Use our metadata with naming conventions
    metadata = metadata
    
    # Type checking: Tell mypy that all models have these attributes
    __tablename__: str


# ================================
# Common Table Attributes Mixin
# ================================
class CommonTableAttributes:
    """
    Mixin that provides common fields and methods to all models.
    
    What's a Mixin?
    ---------------
    A mixin is a class that provides methods/attributes to other classes through
    multiple inheritance, but isn't meant to stand on its own.
    
    Think of it like a "feature pack" that you can add to your models.
    
    Common Fields Added:
    --------------------
    - id: Primary key (auto-incrementing integer)
    - created_at: When the record was created (set once, never changes)
    - updated_at: When the record was last modified (updates automatically)
    
    Why these fields?
    -----------------
    - id: Every database table needs a unique identifier
    - created_at: Useful for sorting, auditing, analytics
    - updated_at: Track changes, debugging, data integrity
    
    Advanced Feature:
    -----------------
    Uses timezone-aware UTC timestamps to avoid timezone confusion.
    Always store in UTC, convert to user's timezone in the application layer!
    """
    
    # Primary Key
    # -----------
    # Mapped[int]: This is SQLAlchemy 2.0 type annotation style
    # - Mapped tells SQLAlchemy this is a database column
    # - [int] specifies the Python type
    # 
    # primary_key=True: Makes this the unique identifier for each row
    # autoincrement=True: Database automatically generates sequential IDs (1, 2, 3, ...)
    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
        comment="Auto-incrementing primary key"
    )
    
    # Created At Timestamp
    # --------------------
    # DateTime(timezone=True): Store as TIMESTAMP WITH TIME ZONE in PostgreSQL
    # - Preserves timezone information in the database
    # - Avoids "naive vs aware datetime" errors
    # - Best practice for distributed systems
    #
    # default=lambda: datetime.now(timezone.utc):
    # - This function runs ONCE when the record is created
    # - timezone.utc ensures we store in UTC (best practice)
    # - Never changes after initial creation
    #
    # nullable=False: This field MUST have a value (database will reject NULL)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="Timestamp when record was created (UTC)"
    )
    
    # Updated At Timestamp
    # --------------------
    # DateTime(timezone=True): Store as TIMESTAMP WITH TIME ZONE in PostgreSQL
    # 
    # default=lambda: datetime.now(timezone.utc): Set on creation
    # onupdate=lambda: datetime.now(timezone.utc): Update on EVERY modification
    # 
    # How it works:
    # 1. Record created: both created_at and updated_at set to current time
    # 2. Record updated: only updated_at changes to new time
    # 3. Result: You can always see when something was created vs. last modified
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="Timestamp when record was last updated (UTC)"
    )
    
    def __repr__(self) -> str:
        """
        String representation of the model for debugging.
        
        Example output:
            User(id=1)
            Post(id=42)
        
        Why __repr__?
        -------------
        When you print a model instance in debugging, you see this instead of
        <User object at 0x7f8b4c5d3a90>
        """
        return f"{self.__class__.__name__}(id={self.id})"
    
    def dict(self) -> dict[str, Any]:
        """
        Convert model instance to dictionary.
        
        Useful for:
        -----------
        - Serializing to JSON for API responses
        - Debugging and logging
        - Testing
        
        Example:
            user = User(name="Alice", email="alice@example.com")
            user_dict = user.dict()
            # {'id': 1, 'name': 'Alice', 'email': 'alice@example.com', ...}
        
        Note: This is a simple implementation. For production, you might use
        Pydantic schemas for more control over serialization.
        """
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }


# ================================
# Convenient Base Model
# ================================
class BaseModel(Base, CommonTableAttributes):
    """
    Ready-to-use base class for all application models.
    
    Combines:
    - Base: SQLAlchemy ORM functionality
    - CommonTableAttributes: id, created_at, updated_at fields
    
    Usage:
    ------
    Instead of:
        class User(Base, CommonTableAttributes):
            __tablename__ = "users"
            ...
    
    Just do:
        class User(BaseModel):
            __tablename__ = "users"
            ...
    
    Every model automatically gets:
    - Primary key (id)
    - Creation timestamp (created_at)
    - Update timestamp (updated_at)
    - Useful methods (dict(), __repr__())
    """
    
    # This is an abstract base class - it won't create its own table
    # Only models that inherit from it will create tables
    __abstract__ = True


# ================================
# String Length Constraints
# ================================
# Type aliases for commonly used string lengths
# This promotes consistency and makes it easy to change lengths globally

# Short strings: names, titles, slugs
String50 = String(50)  # Example: username, first_name
String100 = String(100)  # Example: titles, short descriptions
String255 = String(255)  # Example: email, URLs (common varchar max)

# Medium strings: descriptions, summaries
String500 = String(500)  # Example: bio, short content
String1000 = String(1000)  # Example: summaries

# Usage example:
# email: Mapped[str] = mapped_column(String255, unique=True)
# This is clearer than: email: Mapped[str] = mapped_column(String(255), unique=True)
