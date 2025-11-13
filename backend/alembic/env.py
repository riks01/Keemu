"""
Alembic Migration Environment

This file configures the Alembic migration environment.

What happens here:
------------------
1. Load application settings (database URL, etc.)
2. Import all models so Alembic can detect them
3. Configure connection to database
4. Run migrations (upgrade/downgrade)

Key Functions:
--------------
- run_migrations_offline(): Generate SQL without connecting to DB
- run_migrations_online(): Connect to DB and apply migrations

Learning Note:
--------------
This file is called by Alembic when you run migration commands.
You usually don't need to modify this file unless you're changing
how migrations work at a fundamental level.
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add parent directory to Python path so we can import app module
# This allows: from app.core.config import settings
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import application config
from app.core.config import settings

# Import Base metadata from our models
# This is CRITICAL: Alembic needs to know about all models
from app.db.base import Base

# Import all models so they're registered with Base.metadata
# Without these imports, Alembic won't detect the tables!
from app.models import (  # noqa: F401
    Channel,
    ContentItem,
    User,
    UserPreferences,
    UserSubscription,
)
# The noqa: F401 comment tells flake8:
# "These imports are intentional, don't warn about unused imports"

# ================================
# Alembic Config Object
# ================================

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Set the SQLAlchemy URL from our application settings
# This replaces the placeholder in alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ================================
# Metadata Target
# ================================

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# What is target_metadata?
# -------------------------
# This tells Alembic which models to track for migrations.
# Base.metadata contains information about all tables/columns
# that inherit from BaseModel.
#
# When you run: alembic revision --autogenerate
# Alembic compares:
# - What's in the database (current state)
# - What's in target_metadata (desired state)
# And generates migration to make them match!

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    
    What is offline mode?
    ---------------------
    Instead of connecting to the database and applying migrations,
    this just generates the SQL statements and prints them.
    
    When would you use this?
    ------------------------
    - Generate SQL to review before applying
    - Apply migrations manually
    - Document schema changes
    
    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.
    
    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Compare type means Alembic will detect column type changes
        compare_type=True,
        # Compare server default means Alembic will detect default value changes
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Run migrations with the given connection.
    
    This is the actual migration execution function.
    Called by run_migrations_online().
    
    Parameters:
        connection: Database connection to use
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Compare settings - what changes should Alembic detect?
        compare_type=True,  # Detect VARCHAR(50) → VARCHAR(100)
        compare_server_default=True,  # Detect default value changes
        # Render item - how to display items in migration
        render_as_batch=True,  # Use batch operations (safer)
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Create async engine and run migrations.
    
    Why async?
    ----------
    Our application uses async SQLAlchemy (asyncpg driver).
    Migrations need to use the same async approach.
    """
    # Create async engine from config
    # This reads the DATABASE_URL and creates engine
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # Don't use connection pooling for migrations
    )

    # Connect and run migrations
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    # Clean up
    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.
    
    What is online mode?
    --------------------
    Connects to the actual database and applies migrations.
    This is what you normally use.
    
    In this scenario we need to create an Engine
    and associate a connection with the context.
    
    Since we use async SQLAlchemy, we need to:
    1. Create async engine
    2. Run migrations in async context
    3. Use run_sync to execute migrations
    """
    asyncio.run(run_async_migrations())


# ================================
# Main Execution
# ================================

# When Alembic runs, it calls this
if context.is_offline_mode():
    # Offline mode: Generate SQL only
    run_migrations_offline()
else:
    # Online mode: Connect and apply migrations
    run_migrations_online()
