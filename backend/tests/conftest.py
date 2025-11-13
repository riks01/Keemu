"""
Pytest configuration and fixtures.

This file is automatically discovered by pytest and provides
shared fixtures for all test modules.

References:
-----------
- Pytest Fixtures: https://docs.pytest.org/en/stable/fixture.html
- FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing/
- Testing Flask/SQLAlchemy: https://pytest-with-eric.com/api-testing/pytest-flask-postgresql-testing/
"""

import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.base import Base
from app.db.deps import get_db
from app.main import app
from app.models.user import SummaryLength, UpdateFrequency, User, UserPreferences


# ================================
# Pytest Configuration
# ================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """
    Create an event loop for the test session.
    
    This fixture ensures all async tests use the same event loop.
    Required for pytest-asyncio.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ================================
# Database Fixtures
# ================================

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """
    Create a test database engine.
    
    Uses the same database as development but isolated tables.
    For production testing, use a separate test database.
    
    NullPool disables connection pooling for tests.
    """
    engine = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,  # Disable pooling for tests
        echo=False,  # Set to True for SQL debugging
    )
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create a database session for each test.
    
    Each test gets a fresh session with transaction that is rolled back after test.
    This ensures test isolation without actually committing changes.
    
    Pattern from: https://pytest-with-eric.com/api-testing/pytest-flask-postgresql-testing/
    """
    # Create connection
    connection = await test_engine.connect()
    
    # Begin outer transaction
    transaction = await connection.begin()
    
    # Create session bound to connection
    async_session = sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session() as session:
        # Begin nested transaction
        nested = await connection.begin_nested()
        
        yield session
        
        # Rollback nested transaction
        if nested.is_active:
            await nested.rollback()
        
    # Rollback outer transaction
    await transaction.rollback()
    
    # Close connection
    await connection.close()


# ================================
# FastAPI Client Fixtures
# ================================

@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for testing FastAPI endpoints.
    
    Overrides the get_db dependency to use test database session.
    
    Usage:
        async def test_something(client: AsyncClient):
            response = await client.get("/api/v1/endpoint")
            assert response.status_code == 200
    """
    # Override database dependency
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    # Clean up
    app.dependency_overrides.clear()


# ================================
# User Fixtures
# ================================

@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """
    Create a test user with preferences and password.
    
    This user can be used across multiple tests.
    Password is "testpass123" (hashed).
    """
    from app.core.security import get_password_hash
    
    user = User(
        email="test@example.com",
        name="Test User",
        hashed_password=get_password_hash("testpass123"),  # Short password for testing
        timezone="UTC",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()
    
    # Create preferences
    preferences = UserPreferences(
        user_id=user.id,
        update_frequency=UpdateFrequency.WEEKLY,
        summary_length=SummaryLength.STANDARD,
        email_notifications_enabled=True
    )
    db_session.add(preferences)
    await db_session.commit()
    await db_session.refresh(user)
    
    return user


@pytest_asyncio.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    """
    Create an inactive test user.
    
    Used for testing authentication with disabled accounts.
    Password is "testpass123" (hashed).
    """
    from app.core.security import get_password_hash
    
    user = User(
        email="inactive@example.com",
        name="Inactive User",
        hashed_password=get_password_hash("testpass123"),
        timezone="UTC",
        is_active=False
    )
    db_session.add(user)
    await db_session.flush()
    
    preferences = UserPreferences(
        user_id=user.id,
        update_frequency=UpdateFrequency.WEEKLY,
        summary_length=SummaryLength.STANDARD,
        email_notifications_enabled=True
    )
    db_session.add(preferences)
    await db_session.commit()
    await db_session.refresh(user)
    
    return user


# ================================
# Authentication Fixtures
# ================================

@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    """
    Create authentication headers with JWT token.
    
    Usage:
        async def test_protected_endpoint(client: AsyncClient, auth_headers: dict):
            response = await client.get("/api/v1/auth/me", headers=auth_headers)
            assert response.status_code == 200
    """
    from datetime import timedelta
    from app.core.security import create_access_token
    
    # Create token for test user
    token = create_access_token(
        data={"sub": test_user.email},
        expires_delta=timedelta(minutes=30)
    )
    
    return {
        "Authorization": f"Bearer {token}"
    }


@pytest.fixture
def expired_token() -> str:
    """
    Create an expired JWT token for testing.
    """
    from datetime import timedelta
    from app.core.security import create_access_token
    
    # Create token that expired 1 hour ago
    token = create_access_token(
        data={"sub": "test@example.com"},
        expires_delta=timedelta(hours=-1)
    )
    
    return token


# ================================
# Utility Fixtures
# ================================

@pytest.fixture
def sample_user_data() -> dict:
    """
    Sample user registration data.
    Note: Using short password to avoid bcrypt 72-byte limit in tests.
    """
    return {
        "email": "newuser@example.com",
        "name": "New User",
        "password": "testpass123",  # Short password for testing (avoids bcrypt limit)
        "profession": "Software Engineer",
        "date_of_birth": "1990-01-15",
        "timezone": "America/New_York"
    }


@pytest.fixture
def sample_login_data() -> dict:
    """
    Sample login credentials.
    Note: Using short password to avoid bcrypt 72-byte limit in tests.
    """
    return {
        "username": "test@example.com",  # OAuth2 uses 'username' field
        "password": "testpass123"  # Short password for testing
    }


# ================================
# Pytest Hooks
# ================================

def pytest_addoption(parser):
    """Add custom pytest options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require network access and real API keys"
    )


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires network and API keys)"
    )
