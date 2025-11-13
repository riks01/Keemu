"""
Database Session Management

This module handles the database connection lifecycle and session management.

Key Concepts:
--------------
1. Engine: The core of SQLAlchemy's database communication
2. Session: A workspace for database operations (like a transaction)
3. Connection Pooling: Reusing database connections for performance
4. Async Operations: Non-blocking database queries for FastAPI

Architecture Flow:
------------------
Application Start → Create Engine → Connection Pool Ready
↓
API Request → Get Session → Execute Queries → Commit/Rollback → Close Session
↓
Application Shutdown → Dispose Engine → Close All Connections

Learning Resources:
- SQLAlchemy Engine: https://docs.sqlalchemy.org/en/20/core/engines.html
- Async Sessions: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
"""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# ================================
# Database Engine Configuration
# ================================

def get_engine_config() -> dict[str, Any]:
    """
    Configure the database engine based on environment.
    
    What's an Engine?
    -----------------
    The Engine is SQLAlchemy's interface to the database. It:
    - Manages database connections
    - Executes SQL statements
    - Handles connection pooling
    - Manages transactions
    
    Connection Pooling Explained:
    ------------------------------
    Instead of creating a new connection for every query (slow!),
    SQLAlchemy maintains a "pool" of reusable connections.
    
    Think of it like a taxi stand:
    - Without pooling: Call a new taxi for every trip (slow)
    - With pooling: Taxis wait at the stand, ready to go (fast)
    
    Pool Types:
    -----------
    1. QueuePool (Production):
       - Maintains pool_size connections open
       - Can create max_overflow extra connections if needed
       - Connections are recycled after use
       - Best for production with steady traffic
    
    2. NullPool (Testing):
       - No connection pooling
       - Creates new connection for each request
       - Closes immediately after use
       - Best for testing to ensure isolation
    
    Our Configuration:
    ------------------
    - pool_size=20: Keep 20 connections ready (from settings.DB_POOL_SIZE)
    - max_overflow=10: Can create 10 more if all 20 are busy
    - Total max concurrent connections: 30
    - pool_pre_ping=True: Test connection before using (detect dead connections)
    - pool_recycle=3600: Recycle connections after 1 hour (prevent stale connections)
    - echo=False: Don't log all SQL (unless DEBUG mode)
    
    Why these numbers?
    ------------------
    - 20 connections handles ~100-200 concurrent requests well
    - 10 overflow handles traffic spikes
    - Adjust based on your server resources and traffic
    """
    
    # Base configuration applies to all environments
    config: dict[str, Any] = {
        # Echo SQL statements to logs (helpful for debugging)
        "echo": settings.DB_ECHO,
        
        # Test connection health before using ("pessimistic" disconnect handling)
        # Prevents errors from dead connections (network issues, database restarts)
        "pool_pre_ping": True,
        
        # Recycle connections after 1 hour (3600 seconds)
        # Prevents issues with databases that close idle connections
        # Also good for picking up config changes (e.g., password rotation)
        "pool_recycle": 3600,
        
        # Connection timeout: wait up to 30 seconds for available connection
        # If all connections are busy and overflow is maxed, wait this long
        # Then raise an error (prevents hanging forever)
        "pool_timeout": 30,
        
        # For async: Use PostgreSQL's native async driver
        # asyncpg is much faster than psycopg2 for async operations
        "connect_args": {
            # Set default schema search path
            "server_settings": {
                "application_name": settings.APP_NAME,
            }
        },
    }
    
    # Environment-specific configuration
    if settings.is_development:
        # Development: More debugging, normal pooling
        logger.info(
            "configuring_database_engine",
            environment="development",
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
        )
        config.update({
            # Use AsyncAdaptedQueuePool for async engines
            "poolclass": AsyncAdaptedQueuePool,
            "pool_size": settings.DB_POOL_SIZE,  # 20 connections
            "max_overflow": settings.DB_MAX_OVERFLOW,  # 10 extra
        })
    
    elif settings.is_production:
        # Production: Optimize for performance and reliability
        logger.info(
            "configuring_database_engine",
            environment="production",
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
        )
        config.update({
            "poolclass": AsyncAdaptedQueuePool,
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            # In production, might want even longer recycle time
            "pool_recycle": 7200,  # 2 hours
        })
    
    else:
        # Testing/Staging: Use NullPool for isolation
        logger.info(
            "configuring_database_engine",
            environment=settings.APP_ENV,
            pool_type="NullPool",
        )
        config.update({
            # No pooling - each test gets fresh connections
            "poolclass": NullPool,
        })
    
    return config


def create_engine() -> AsyncEngine:
    """
    Create the async database engine.
    
    Why Async?
    ----------
    FastAPI is built on async/await. Using async database operations:
    - Doesn't block the event loop
    - Allows handling many concurrent requests efficiently
    - Better resource utilization
    
    Performance Example:
    -------------------
    Sync (blocks):
        Request 1: Query (100ms) → blocks
        Request 2: Waits...
        Request 3: Waits...
        Total: 300ms for 3 requests
    
    Async (concurrent):
        Request 1: Query (100ms) → yields control
        Request 2: Query (100ms) → runs simultaneously
        Request 3: Query (100ms) → runs simultaneously
        Total: ~100ms for 3 requests
    
    Returns:
        AsyncEngine: The database engine instance
    """
    engine_config = get_engine_config()
    
    # Create async engine
    # The database URL must start with "postgresql+asyncpg://" for async
    # Example: postgresql+asyncpg://user:pass@localhost:5432/dbname
    engine = create_async_engine(
        settings.DATABASE_URL,
        **engine_config
    )
    
    logger.info(
        "database_engine_created",
        driver="asyncpg",
        pool_size=engine_config.get("pool_size", "NullPool"),
    )
    
    return engine


# ================================
# Global Engine Instance
# ================================
# Create the engine once when the module is imported
# This is efficient: one engine manages all connections
#
# The engine is thread-safe and designed to be a global singleton
# Don't create multiple engines - that defeats the purpose of pooling!
engine: AsyncEngine = create_engine()


# ================================
# Session Factory
# ================================

# Create a session factory (a "maker" of sessions)
# Think of this as a factory that produces database sessions on demand
#
# async_sessionmaker is a class that, when called, returns a new AsyncSession
# It's configured once here, then used throughout the application
AsyncSessionLocal = async_sessionmaker(
    # Which engine to use
    bind=engine,
    
    # Create AsyncSession instances
    class_=AsyncSession,
    
    # autoflush=False:
    # Don't automatically flush changes before queries
    # Gives you more control over when data is sent to database
    # You explicitly call session.flush() when needed
    autoflush=False,
    
    # autocommit=False:
    # Don't automatically commit after each operation
    # You explicitly call session.commit() when ready
    # This allows rolling back if something goes wrong
    autocommit=False,
    
    # expire_on_commit=False:
    # After commit, don't expire (invalidate) all loaded instances
    # This means you can still access attributes without re-querying
    # Useful for returning objects from the session after commit
    expire_on_commit=False,
)


# ================================
# Session Lifecycle Functions
# ================================

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get a database session for a single request.
    
    This is a dependency that FastAPI will call automatically.
    
    How It Works:
    -------------
    1. FastAPI receives a request
    2. Calls this function to get a session
    3. Passes session to your route handler
    4. After route completes (or errors), runs cleanup
    5. Session is closed, connection returned to pool
    
    The yield statement is special:
    -------------------------------
    - Code before yield: Setup (create session)
    - yield: Return session to the route
    - Code after yield: Cleanup (close session)
    
    This pattern ensures cleanup happens even if an error occurs!
    
    Usage in Routes:
    ----------------
    @app.get("/users")
    async def get_users(db: AsyncSession = Depends(get_session)):
        # 'db' is automatically provided by FastAPI
        users = await db.execute(select(User))
        return users.scalars().all()
    
    Error Handling:
    ---------------
    - If route succeeds: Session closed normally
    - If route raises exception: Session rolled back, then closed
    - Connection always returned to pool
    
    Yields:
        AsyncSession: A database session for this request
    """
    # Create a new session from the factory
    async with AsyncSessionLocal() as session:
        try:
            # Yield the session to the route handler
            # Everything between try and finally happens in the route
            yield session
            
        except Exception as e:
            # If an error occurred, rollback the transaction
            # This undoes any changes made during this request
            logger.error(
                "database_session_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            await session.rollback()
            # Re-raise the exception so FastAPI can handle it
            raise
            
        finally:
            # Always close the session, even if an error occurred
            # This returns the connection to the pool
            # The 'async with' automatically calls session.close()
            pass


async def init_db() -> None:
    """
    Initialize the database.
    
    This function is called during application startup to:
    1. Verify database connection
    2. Create tables (in development)
    3. Run any initialization logic
    
    When to Use:
    ------------
    - Development: Auto-create tables for quick iteration
    - Production: Use Alembic migrations instead (more controlled)
    
    Called from: app.main.lifespan() startup event
    """
    logger.info("initializing_database")
    
    try:
        # Test the connection
        async with engine.begin() as conn:
            # Try a simple query
            await conn.execute(text("SELECT 1"))
        
        logger.info("database_connection_successful")
        
        # In development, you might auto-create tables
        # In production, use Alembic migrations instead
        if settings.is_development:
            # Import Base to ensure all models are registered
            from app.db.base import Base
            
            async with engine.begin() as conn:
                # Create all tables defined by models
                # This is equivalent to CREATE TABLE IF NOT EXISTS
                await conn.run_sync(Base.metadata.create_all)
            
            logger.info("database_tables_created")
    
    except Exception as e:
        logger.error(
            "database_initialization_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def close_db() -> None:
    """
    Close the database connection pool.
    
    This function is called during application shutdown to:
    1. Close all active connections
    2. Clean up resources
    3. Ensure graceful shutdown
    
    Called from: app.main.lifespan() shutdown event
    
    Why Important:
    --------------
    - Prevents connection leaks
    - Allows database to clean up resources
    - Enables graceful deployment updates
    """
    logger.info("closing_database_connections")
    
    try:
        # Dispose of the engine
        # This closes all connections in the pool
        await engine.dispose()
        
        logger.info("database_connections_closed")
    
    except Exception as e:
        logger.error(
            "database_closure_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        # Don't raise - we're shutting down anyway


# ================================
# Database Health Check
# ================================

async def check_db_health() -> bool:
    """
    Check if the database is healthy and responsive.
    
    Use Cases:
    ----------
    - Health check endpoints
    - Monitoring systems
    - Startup validation
    - Load balancer health checks
    
    Returns:
        bool: True if database is healthy, False otherwise
    """
    try:
        async with engine.connect() as conn:
            # Execute a simple query
            await conn.execute(text("SELECT 1"))
        return True
    
    except Exception as e:
        logger.error(
            "database_health_check_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
