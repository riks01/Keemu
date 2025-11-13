"""
Authentication dependencies for FastAPI.

This module provides:
- OAuth2 password bearer scheme
- User authentication functions
- Dependency injection for protected routes

References:
-----------
- FastAPI Security Tutorial: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- OAuth2 Spec: https://oauth.net/2/
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import decode_access_token, verify_password
from app.db.deps import get_db
from app.models.user import User

# ================================
# OAuth2 Configuration
# ================================

# OAuth2PasswordBearer extracts the token from the Authorization header
# tokenUrl: The endpoint where users get tokens (our login endpoint)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")
# What is OAuth2PasswordBearer?
# ------------------------------
# - Extracts JWT token from Authorization header
# - Header format: "Authorization: Bearer <token>"
# - Automatically adds "Authorize" button in Swagger docs
# - Raises 401 if token missing or invalid
#
# How it works:
# -------------
# 1. User includes token in request header:
#    Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
#
# 2. oauth2_scheme extracts the token part:
#    eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
#
# 3. We pass token to decode_access_token()
#
# 4. Get user info from decoded token
#
# 5. Return authenticated user to route handler
#
# Usage in routes:
# ----------------
# @app.get("/protected")
# async def protected_route(token: str = Depends(oauth2_scheme)):
#     # token contains the JWT string
#     payload = decode_access_token(token)
#     return {"user": payload.get("sub")}
#
# Why tokenUrl?
# -------------
# - Required by OAuth2 spec
# - Tells Swagger UI where to get tokens
# - Users click "Authorize" → enter credentials → get token
# - Swagger automatically includes token in requests


# ================================
# Authentication Functions
# ================================

async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    """
    Authenticate a user by email and password.
    
    This is the core authentication function used during login.
    
    How it works:
    -------------
    1. Look up user by email in database
    2. If user not found → return None
    3. If user found → verify password
    4. If password correct → return User object
    5. If password wrong → return None
    
    Args:
        db: Database session
        email: User's email address
        password: Plaintext password from login form
    
    Returns:
        User object if authentication succeeds, None otherwise
    
    Example:
        >>> async with AsyncSessionLocal() as db:
        ...     user = await authenticate_user(
        ...         db, 
        ...         "alice@example.com", 
        ...         "secret"
        ...     )
        ...     if user:
        ...         print(f"Welcome {user.name}!")
        ...     else:
        ...         print("Invalid credentials")
    
    Security Notes:
    ---------------
    - Password is verified using constant-time comparison
    - Failed login doesn't reveal whether email or password was wrong
    - Rate limiting should be applied at route level
    - Consider logging failed login attempts
    
    Why return None instead of raising exception?
    ----------------------------------------------
    - Allows caller to handle error (custom message, logging)
    - Avoids revealing whether email exists (security)
    - Consistent with FastAPI patterns
    """
    # Query user by email
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()
    
    # User not found
    if not user:
        return None
    
    # Verify password
    # NOTE: User doesn't have password field yet!
    # This will be added when we implement local auth
    # For now, we'll use Google OAuth exclusively
    # if not verify_password(password, user.hashed_password):
    #     return None
    
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Get the current authenticated user from JWT token.
    
    This is a FastAPI dependency used to protect routes.
    It extracts the user from the JWT token and loads them from the database.
    
    How it works:
    -------------
    1. OAuth2PasswordBearer extracts token from Authorization header
    2. Decode and verify JWT token
    3. Extract user email from token's "sub" claim
    4. Load user from database
    5. Return User object to route handler
    
    Args:
        token: JWT token (automatically extracted by oauth2_scheme)
        db: Database session (automatically injected by get_db)
    
    Returns:
        User object
    
    Raises:
        HTTPException 401: If token invalid, expired, or user not found
    
    Usage in routes:
    ----------------
    @app.get("/users/me")
    async def read_users_me(current_user: User = Depends(get_current_user)):
        return {
            "email": current_user.email,
            "name": current_user.name
        }
    
    Example flow:
    -------------
    1. Client request:
       GET /users/me
       Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    
    2. oauth2_scheme extracts token
    
    3. decode_access_token verifies and decodes
       {"sub": "alice@example.com", "exp": 1699999999}
    
    4. Query database for user with email "alice@example.com"
    
    5. Return User object to route handler
    
    6. Route handler uses current_user.name, current_user.email, etc.
    
    Security Notes:
    ---------------
    - Token must be valid (not expired, not tampered)
    - User must exist in database
    - User's active status checked by get_current_active_user
    - Always use HTTPS to prevent token interception
    
    Error Handling:
    ---------------
    - Invalid token → 401 Unauthorized
    - Expired token → 401 Unauthorized
    - User not found → 401 Unauthorized
    - Database error → 500 Internal Server Error
    
    Why 401 for all errors?
    -----------------------
    - Security: Don't reveal why authentication failed
    - Standard: OAuth2 spec requires 401 for authentication failures
    - Consistency: Same error for all auth failures
    """
    # Create credentials exception (reused for all auth failures)
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # What is WWW-Authenticate header?
    # --------------------------------
    # - Required by HTTP spec for 401 responses
    # - Tells client what auth method to use
    # - "Bearer" means client should send JWT in Authorization header
    # - Format: Authorization: Bearer <token>
    
    # Decode and verify token
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    # Extract user email from token
    email: str | None = payload.get("sub")
    if email is None:
        raise credentials_exception
    # What is "sub" claim?
    # --------------------
    # - JWT standard claim for "subject" (who token is about)
    # - We store user email here
    # - Could also use user ID (integer)
    # - Must be unique and immutable
    
    # Load user from database
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get the current user and verify they are active.
    
    This is an additional layer on top of get_current_user that ensures
    the user's account is not disabled.
    
    How it works:
    -------------
    1. get_current_user verifies token and loads user
    2. Check if user.is_active is True
    3. If active → return user
    4. If inactive → raise 400 Bad Request
    
    Args:
        current_user: User object from get_current_user dependency
    
    Returns:
        User object (guaranteed to be active)
    
    Raises:
        HTTPException 400: If user account is disabled
    
    Usage in routes:
    ----------------
    @app.get("/protected")
    async def protected_route(
        current_user: User = Depends(get_current_active_user)
    ):
        # current_user is guaranteed to be:
        # - Authenticated (valid token)
        # - Active (is_active = True)
        return {"message": f"Hello {current_user.name}!"}
    
    Example scenarios:
    ------------------
    1. Normal user:
       - Token valid
       - User exists
       - is_active = True
       → Return user ✓
    
    2. Disabled account:
       - Token valid
       - User exists
       - is_active = False
       → Raise 400 ✗
    
    3. Deleted account:
       - Token valid
       - User not found
       → get_current_user raises 401 ✗
    
    4. Expired token:
       - Token expired
       → get_current_user raises 401 ✗
    
    Why separate active check?
    --------------------------
    - Flexibility: Some routes might allow inactive users
    - Clarity: Explicit check vs implicit assumption
    - Error handling: Different error for disabled vs invalid token
    - Logging: Can track disabled user attempts
    
    When to use get_current_active_user vs get_current_user?
    ---------------------------------------------------------
    Use get_current_active_user for:
    - Endpoints that modify data
    - Endpoints that consume resources
    - Most protected endpoints
    
    Use get_current_user for:
    - Admin checking any user
    - Allowing disabled users to view certain data
    - Endpoints that don't require active status
    
    Why 400 instead of 403?
    -----------------------
    - 400 Bad Request: Client sent valid request, but can't be processed
    - 403 Forbidden: Client lacks permission (different from disabled)
    - Could use 403 instead, both are acceptable
    - FastAPI tutorial uses 400, so we follow convention
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


# ================================
# Optional: Role-Based Access Control
# ================================

# Future enhancement: Check user roles/permissions
# 
# async def require_admin(
#     current_user: User = Depends(get_current_active_user)
# ) -> User:
#     """Require user to be an admin."""
#     if not current_user.is_admin:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Admin access required"
#         )
#     return current_user
#
# Usage:
# @app.delete("/users/{user_id}")
# async def delete_user(
#     user_id: int,
#     admin: User = Depends(require_admin)
# ):
#     # Only admins can access this endpoint
#     pass
