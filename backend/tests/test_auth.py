"""
Authentication endpoint tests.

Tests for:
- Login endpoint
- Registration endpoint
- Get current user endpoint
- Token validation
- Authentication dependencies

References:
-----------
- FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing/
- Pytest Async: https://pytest-asyncio.readthedocs.io/
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decode_access_token
from app.models.user import User


# ================================
# Login Endpoint Tests
# ================================

@pytest.mark.asyncio
class TestLogin:
    """Test login endpoint."""
    
    async def test_login_success(
        self,
        client: AsyncClient,
        test_user: User,
        sample_login_data: dict
    ):
        """Test successful login with valid credentials."""
        response = await client.post(
            "/api/v1/auth/login",
            data=sample_login_data
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
    
    async def test_login_wrong_password(
        self,
        client: AsyncClient,
        test_user: User
    ):
        """Test login with wrong password."""
        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "test@example.com",
                "password": "wrongpassword"
            }
        )
        
        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()
    
    async def test_login_user_not_found(
        self,
        client: AsyncClient
    ):
        """Test login with non-existent user."""
        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "nonexistent@example.com",
                "password": "password123"
            }
        )
        
        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()


# ================================
# Registration Endpoint Tests
# ================================

@pytest.mark.asyncio
class TestRegistration:
    """Test registration endpoint."""
    
    async def test_register_success(
        self,
        client: AsyncClient,
        sample_user_data: dict
    ):
        """Test successful user registration."""
        response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data
        )
        
        assert response.status_code == 201
        data = response.json()
        assert "user" in data
        assert "access_token" in data
        assert "token_type" in data
        assert data["user"]["email"] == sample_user_data["email"]
        assert data["user"]["name"] == sample_user_data["name"]
        assert data["token_type"] == "bearer"
    
    async def test_register_duplicate_email(
        self,
        client: AsyncClient,
        test_user: User,
        sample_user_data: dict
    ):
        """Test registration with existing email."""
        sample_user_data["email"] = test_user.email
        
        response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data
        )
        
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()
    
    async def test_register_invalid_email(
        self,
        client: AsyncClient,
        sample_user_data: dict
    ):
        """Test registration with invalid email format."""
        sample_user_data["email"] = "invalid-email"
        
        response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data
        )
        
        # Pydantic validation should fail
        assert response.status_code == 422
    
    async def test_register_short_password(
        self,
        client: AsyncClient,
        sample_user_data: dict
    ):
        """Test registration with password too short."""
        sample_user_data["password"] = "short"
        
        response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data
        )
        
        # Pydantic validation should fail
        assert response.status_code == 422


# ================================
# Get Current User Tests
# ================================

@pytest.mark.asyncio
class TestGetCurrentUser:
    """Test get current user endpoint."""
    
    async def test_get_current_user_success(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User
    ):
        """Test getting current user with valid token."""
        response = await client.get(
            "/api/v1/auth/me",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify user data
        assert data["email"] == test_user.email
        assert data["name"] == test_user.name
        assert data["id"] == test_user.id
        assert data["is_active"] == True
        assert "profile_picture" in data
        assert "profession" in data
        assert "date_of_birth" in data
        assert "timezone" in data
    
    async def test_get_current_user_no_token(
        self,
        client: AsyncClient
    ):
        """Test getting current user without token."""
        response = await client.get("/api/v1/auth/me")
        
        assert response.status_code == 401
        assert "not authenticated" in response.json()["detail"].lower()
    
    async def test_get_current_user_invalid_token(
        self,
        client: AsyncClient
    ):
        """Test getting current user with invalid token."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid_token_here"}
        )
        
        assert response.status_code == 401
    
    async def test_get_current_user_expired_token(
        self,
        client: AsyncClient,
        expired_token: str
    ):
        """Test getting current user with expired token."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"}
        )
        
        assert response.status_code == 401
    
    async def test_get_current_user_inactive(
        self,
        client: AsyncClient,
        inactive_user: User
    ):
        """Test getting current user when account is inactive."""
        from datetime import timedelta
        
        # Create token for inactive user
        token = create_access_token(
            data={"sub": inactive_user.email},
            expires_delta=timedelta(minutes=30)
        )
        
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 400
        assert "inactive" in response.json()["detail"].lower()


# ================================
# Auth Health Check Tests
# ================================

@pytest.mark.asyncio
class TestAuthHealthCheck:
    """Test authenticated health check endpoint."""
    
    async def test_health_check_success(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_user: User
    ):
        """Test health check with valid token."""
        response = await client.get(
            "/api/v1/auth/health",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "healthy"
        assert data["user_id"] == test_user.id
        assert data["user_email"] == test_user.email
        assert data["authenticated"] == True
    
    async def test_health_check_no_token(
        self,
        client: AsyncClient
    ):
        """Test health check without token."""
        response = await client.get("/api/v1/auth/health")
        
        assert response.status_code == 401


# ================================
# JWT Token Tests
# ================================

class TestJWTTokens:
    """Test JWT token creation and validation."""
    
    def test_create_access_token(self):
        """Test creating a JWT access token."""
        from datetime import timedelta
        
        token = create_access_token(
            data={"sub": "test@example.com"},
            expires_delta=timedelta(minutes=30)
        )
        
        assert isinstance(token, str)
        assert len(token) > 0
        
        # Token should have 3 parts (header.payload.signature)
        parts = token.split(".")
        assert len(parts) == 3
    
    def test_decode_access_token(self):
        """Test decoding a valid JWT token."""
        from datetime import timedelta
        
        # Create token
        email = "test@example.com"
        token = create_access_token(
            data={"sub": email},
            expires_delta=timedelta(minutes=30)
        )
        
        # Decode token
        payload = decode_access_token(token)
        
        assert payload is not None
        assert payload["sub"] == email
        assert "exp" in payload
    
    def test_decode_invalid_token(self):
        """Test decoding an invalid token."""
        payload = decode_access_token("invalid.token.here")
        
        assert payload is None
    
    def test_decode_expired_token(self, expired_token: str):
        """Test decoding an expired token."""
        payload = decode_access_token(expired_token)
        
        assert payload is None


# ================================
# Password Hashing Tests
# ================================

class TestPasswordHashing:
    """Test password hashing utilities (not async)."""
    
    def test_password_hash(self):
        """Test password hashing with short password (avoids bcrypt 72-byte limit)."""
        from app.core.security import get_password_hash
        
        password = "testpass123"  # Short password for testing
        hashed = get_password_hash(password)
        
        assert isinstance(hashed, str)
        assert len(hashed) > 0
        assert hashed != password
        
        # Hash should be different each time (different salt)
        hashed2 = get_password_hash(password)
        assert hashed != hashed2
    
    def test_verify_password(self):
        """Test password verification with short password."""
        from app.core.security import get_password_hash, verify_password
        
        password = "testpass123"  # Short password for testing
        hashed = get_password_hash(password)
        
        # Correct password
        assert verify_password(password, hashed) == True
        
        # Wrong password
        assert verify_password("wrongpass", hashed) == False
    
    def test_verify_password_constant_time(self):
        """Test password verification is constant-time."""
        from app.core.security import get_password_hash, verify_password
        import time
        
        password = "testpass123"  # Short password for testing
        hashed = get_password_hash(password)
        
        # Measure time for correct password
        start = time.perf_counter()
        verify_password(password, hashed)
        time_correct = time.perf_counter() - start
        
        # Measure time for wrong password
        start = time.perf_counter()
        verify_password("wrongpass", hashed)
        time_wrong = time.perf_counter() - start
        
        # Times should be similar (constant-time)
        # Allow 50% variation for system noise
        ratio = max(time_correct, time_wrong) / min(time_correct, time_wrong)
        assert ratio < 2.0  # Should be close to 1.0


# ================================
# Authentication Dependencies Tests
# ================================

@pytest.mark.asyncio
class TestAuthDependencies:
    """Test authentication dependency functions."""
    
    async def test_get_current_user_dependency(
        self,
        db_session: AsyncSession,
        test_user: User
    ):
        """Test get_current_user dependency."""
        from datetime import timedelta
        from app.core.auth import get_current_user
        from app.core.security import create_access_token
        
        # Create token
        token = create_access_token(
            data={"sub": test_user.email},
            expires_delta=timedelta(minutes=30)
        )
        
        # Call dependency
        user = await get_current_user(token=token, db=db_session)
        
        assert user is not None
        assert user.email == test_user.email
        assert user.id == test_user.id
    
    async def test_get_current_user_invalid_token(
        self,
        db_session: AsyncSession
    ):
        """Test get_current_user with invalid token."""
        from app.core.auth import get_current_user
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token="invalid_token", db=db_session)
        
        assert exc_info.value.status_code == 401
    
    async def test_get_current_active_user_dependency(
        self,
        test_user: User
    ):
        """Test get_current_active_user dependency."""
        from app.core.auth import get_current_active_user
        
        # Active user should pass
        user = await get_current_active_user(current_user=test_user)
        assert user == test_user
    
    async def test_get_current_active_user_inactive(
        self,
        inactive_user: User
    ):
        """Test get_current_active_user with inactive user."""
        from app.core.auth import get_current_active_user
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(current_user=inactive_user)
        
        assert exc_info.value.status_code == 400
        assert "inactive" in exc_info.value.detail.lower()


# ================================
# Integration Tests
# ================================

@pytest.mark.asyncio
class TestAuthenticationFlow:
    """Test complete authentication flow."""
    
    async def test_full_auth_flow(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User
    ):
        """Test complete authentication flow."""
        from datetime import timedelta
        from app.core.security import create_access_token
        
        # 1. Create token (simulating login)
        token = create_access_token(
            data={"sub": test_user.email},
            expires_delta=timedelta(minutes=30)
        )
        
        # 2. Access protected endpoint
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        
        # 3. Access health check
        response = await client.get(
            "/api/v1/auth/health",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        assert response.json()["authenticated"] == True
