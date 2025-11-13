"""
Database Dependencies for FastAPI Routes

This module provides dependency injection functions for database sessions.

What is Dependency Injection?
------------------------------
Dependency Injection (DI) is a design pattern where objects receive their
dependencies from external sources rather than creating them.

In FastAPI, it means:
- Routes declare what they need (e.g., "I need a database session")
- FastAPI automatically provides it
- No manual session management in every route

Benefits:
---------
1. Less boilerplate: Don't repeat session creation in every route
2. Automatic cleanup: Sessions always closed, even on errors
3. Easy testing: Can inject mock sessions for tests
4. Type safety: Full IDE autocomplete and type checking

Example Without DI (Bad):
-------------------------
@app.get("/users")
async def get_users():
    # Manual session management - error prone!
    session = AsyncSessionLocal()
    try:
        users = await session.execute(select(User))
        return users.scalars().all()
    finally:
        await session.close()  # Easy to forget!

Example With DI (Good):
-----------------------
@app.get("/users")
async def get_users(db: AsyncSession = Depends(get_db)):
    # Clean and simple - FastAPI handles session lifecycle
    users = await db.execute(select(User))
    return users.scalars().all()

Learning Resources:
- FastAPI Dependencies: https://fastapi.tiangolo.com/tutorial/dependencies/
- Dependency Injection Pattern: https://en.wikipedia.org/wiki/Dependency_injection
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session


# ================================
# Database Session Dependency
# ================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session.
    
    This is the main dependency you'll use in your routes.
    
    How It Works:
    -------------
    1. Route function is called
    2. FastAPI sees Depends(get_db)
    3. FastAPI calls get_db()
    4. get_db() yields a session
    5. Session is passed to your route
    6. Route executes with the session
    7. After route completes, get_db() cleanup runs
    8. Session is closed and returned to pool
    
    The yield pattern ensures cleanup happens even if:
    - Route returns successfully
    - Route raises an exception
    - Client disconnects
    - Timeout occurs
    
    Usage in Routes:
    ----------------
    # Method 1: Explicit dependency
    @router.get("/users/{user_id}")
    async def get_user(
        user_id: int,
        db: AsyncSession = Depends(get_db)
    ):
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    # Method 2: Using type annotation (cleaner)
    @router.get("/users/{user_id}")
    async def get_user(
        user_id: int,
        db: DBSession  # Much cleaner!
    ):
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    Error Handling:
    ---------------
    If an error occurs in your route:
    - Session automatically rolls back changes
    - Connection is closed and returned to pool
    - Exception is propagated to FastAPI's error handlers
    
    Transaction Management:
    -----------------------
    Each request gets its own session/transaction:
    - Changes are isolated from other requests
    - You must explicitly commit: await db.commit()
    - Rollback happens automatically on errors
    
    Yields:
        AsyncSession: Database session for the current request
    """
    # Delegate to the session factory
    # This is a thin wrapper around get_session() from session.py
    async for session in get_session():
        yield session


# ================================
# Type Annotation Shortcut
# ================================

# Create a reusable type annotation for database dependencies
# This makes your route signatures cleaner and more readable
#
# Annotated is a Python 3.9+ feature that combines:
# - Type: AsyncSession (for type checkers and IDEs)
# - Metadata: Depends(get_db) (for FastAPI to inject dependency)
#
# Benefits:
# - Shorter route signatures
# - Consistent across all routes
# - Single source of truth for DB dependency
# - Easy to change if needed (e.g., switch to different session type)

DBSession = Annotated[AsyncSession, Depends(get_db)]

# Usage example:
# Before (verbose):
#   async def my_route(db: AsyncSession = Depends(get_db)):
#
# After (clean):
#   async def my_route(db: DBSession):
#
# Both do the same thing, but the second is more readable!


# ================================
# Optional: Repository Pattern Dependency
# ================================

# As your application grows, you might want to use the Repository pattern
# Repositories encapsulate data access logic, making it easier to:
# - Test (mock repositories instead of database)
# - Change storage (switch from PostgreSQL to MongoDB)
# - Reuse queries across routes
# - Keep routes thin and focused
#
# Example repository dependency (we'll implement this later):

# from typing import Type, TypeVar
# from app.repositories.base import BaseRepository
# 
# T = TypeVar("T", bound=BaseRepository)
# 
# def get_repository(repo_type: Type[T]) -> Callable[[DBSession], T]:
#     """
#     Create a dependency that provides a repository instance.
#     
#     Usage:
#     ------
#     @router.get("/users")
#     async def get_users(
#         user_repo: UserRepository = Depends(get_repository(UserRepository))
#     ):
#         return await user_repo.get_all()
#     """
#     def _get_repo(db: DBSession) -> T:
#         return repo_type(db)
#     return _get_repo


# ================================
# Testing Helpers
# ================================

def get_db_override(session: AsyncSession) -> callable:
    """
    Create a dependency override for testing.
    
    In tests, you often want to use a test database or mock session.
    This function creates an override that FastAPI can use.
    
    Usage in Tests:
    ---------------
    # test_users.py
    async def test_get_user():
        # Create test session (could be in-memory SQLite)
        test_session = create_test_session()
        
        # Override the dependency
        app.dependency_overrides[get_db] = get_db_override(test_session)
        
        # Make test request
        response = await client.get("/users/1")
        
        # Clean up
        app.dependency_overrides.clear()
    
    Why Useful:
    -----------
    - Test with known data
    - Avoid polluting production database
    - Faster tests (in-memory database)
    - Isolated tests (each test gets clean state)
    
    Args:
        session: The session to use instead of the real one
    
    Returns:
        A function that yields the test session
    """
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        yield session
    
    return _override


# ================================
# Database Transaction Dependency
# ================================

class DBTransaction:
    """
    Context manager for explicit transaction handling.
    
    Most of the time, FastAPI's default transaction handling is fine:
    - One transaction per request
    - Auto-commit on success
    - Auto-rollback on error
    
    But sometimes you need more control:
    - Multiple operations that must all succeed or fail
    - Savepoints (nested transactions)
    - Long-running transactions
    
    Usage:
    ------
    @router.post("/transfer")
    async def transfer_money(
        from_id: int,
        to_id: int,
        amount: float,
        db: DBSession
    ):
        # Explicit transaction - either both succeed or both fail
        async with DBTransaction(db):
            # Deduct from sender
            sender = await db.get(User, from_id)
            sender.balance -= amount
            
            # Add to receiver
            receiver = await db.get(User, to_id)
            receiver.balance += amount
            
            # Both changes committed together
            # If any error occurs, both are rolled back
    
    Advanced: Savepoints
    --------------------
    You can nest transactions using savepoints:
    
    async with DBTransaction(db):
        # Main transaction
        user = User(name="Alice")
        db.add(user)
        
        try:
            async with DBTransaction(db, savepoint=True):
                # Nested transaction (savepoint)
                post = Post(title="Test")
                db.add(post)
                # This might fail
                
        except Exception:
            # Nested transaction rolled back
            # But user is still added
            pass
    """
    
    def __init__(
        self,
        session: AsyncSession,
        savepoint: bool = False
    ):
        """
        Initialize transaction context.
        
        Args:
            session: The database session to use
            savepoint: If True, create a savepoint instead of full transaction
        """
        self.session = session
        self.savepoint = savepoint
        self._transaction = None
    
    async def __aenter__(self):
        """
        Enter the transaction context.
        
        Called when entering 'async with DBTransaction(db):'
        """
        if self.savepoint:
            # Create a savepoint (nested transaction)
            self._transaction = await self.session.begin_nested()
        else:
            # Begin a new transaction
            self._transaction = await self.session.begin()
        
        return self._transaction
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the transaction context.
        
        Called when leaving 'async with' block.
        
        Args:
            exc_type: Exception type if an error occurred
            exc_val: Exception value
            exc_tb: Exception traceback
        """
        if exc_type is not None:
            # An error occurred - rollback
            await self._transaction.rollback()
        else:
            # Success - commit
            await self._transaction.commit()
        
        # Return False to propagate exceptions
        return False


# ================================
# Export Public API
# ================================

# What other modules should import from this file
__all__ = [
    "get_db",          # Main dependency function
    "DBSession",       # Type annotation shortcut
    "get_db_override", # Testing helper
    "DBTransaction",   # Explicit transaction control
]
