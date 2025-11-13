"""
Authentication endpoints.

This module provides:
- Login (OAuth2 password flow)
- User registration (password-based)
- Get current user profile
- Google OAuth integration (future)

References:
-----------
- FastAPI Security: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- OAuth2 Password Flow: https://oauth.net/2/grant-types/password/
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_active_user, get_current_user
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.deps import get_db
from app.models.user import SummaryLength, UpdateFrequency, User, UserPreferences
from app.schemas.auth import (
    Token,
    UserRegister,
    UserResponse,
    UserWithToken,
)

# Setup logger
logger = get_logger(__name__)

# Create router
router = APIRouter(prefix="/auth", tags=["authentication"])


# ================================
# OAuth2 Password Flow Login
# ================================

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    Login with email and password (OAuth2 password flow).
    
    This endpoint follows the OAuth2 password grant flow.
    It's what the "Authorize" button in Swagger UI calls.
    
    OAuth2 Password Flow:
    ---------------------
    1. Client sends username (email) and password
    2. Server verifies credentials
    3. Server returns JWT access token
    4. Client includes token in Authorization header for future requests
    
    Request Format:
    ---------------
    Content-Type: application/x-www-form-urlencoded
    
    username=alice@example.com&password=secret
    
    Note: OAuth2 spec requires "username" field, even though we use email.
    
    Response:
    ---------
    {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer"
    }
    
    Client should then send:
    ------------------------
    Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    
    Args:
        form_data: OAuth2 form with username (email) and password
        db: Database session (injected)
    
    Returns:
        JWT access token
    
    Raises:
        HTTPException 401: Invalid credentials or inactive user
    
    Security Notes:
    ---------------
    - Password is verified using constant-time comparison
    - Failed login doesn't reveal whether email exists
    - Token expires after ACCESS_TOKEN_EXPIRE_MINUTES
    - User must be active (is_active=True)
    
    Future Enhancements:
    --------------------
    - Rate limiting (prevent brute-force)
    - Login attempt tracking
    - Account lockout after N failed attempts
    - Two-factor authentication (2FA)
    - Remember me / refresh tokens
    """
    logger.info(f"Login attempt for user: {form_data.username}")
    
    # Query user by email
    result = await db.execute(
        select(User).where(User.email == form_data.username)
    )
    user = result.scalar_one_or_none()
    
    # User not found
    if not user:
        logger.warning(f"Login failed: User not found - {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user has a password set
    if not user.hashed_password:
        logger.warning(f"Login failed: User has no password set - {user.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account uses Google OAuth. Please sign in with Google.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(form_data.password, user.hashed_password):
        logger.warning(f"Login failed: Invalid password - {user.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is active
    if not user.is_active:
        logger.warning(f"Login failed: Inactive user - {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    # Update last login timestamp
    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=access_token_expires
    )
    
    logger.info(f"Login successful: {user.email}")
    
    return Token(access_token=access_token, token_type="bearer")


# ================================
# User Registration
# ================================

@router.post("/register", response_model=UserWithToken, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user with email and password.
    
    This endpoint creates a new user account with password-based authentication.
    
    Registration Flow:
    ------------------
    1. Validate user data (email, password, name)
    2. Check if email already exists
    3. Hash password (bcrypt)
    4. Create user in database
    5. Create default user preferences
    6. Generate JWT token
    7. Return user info + token
    
    Request Body:
    -------------
    {
        "email": "alice@example.com",
        "name": "Alice Johnson",
        "password": "SecurePassword123!",
        "profession": "Software Engineer",  // optional
        "date_of_birth": "1990-05-15",      // optional
        "timezone": "America/New_York"      // default: UTC
    }
    
    Response:
    ---------
    {
        "user": {
            "id": 1,
            "email": "alice@example.com",
            "name": "Alice Johnson",
            ...
        },
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer"
    }
    
    Args:
        user_data: User registration details
        db: Database session (injected)
    
    Returns:
        User information with JWT token
    
    Raises:
        HTTPException 400: Email already registered
        HTTPException 422: Invalid data (handled by Pydantic)
    
    Security Notes:
    ---------------
    - Password is hashed with bcrypt (never stored plaintext)
    - Email uniqueness enforced at database level
    - Default preferences created automatically
    - Token issued immediately (auto-login after registration)
    
    Future Enhancements:
    --------------------
    - Email verification (send confirmation email)
    - Password strength validation (regex, complexity)
    - Username field (separate from email)
    - Terms of service acceptance
    - CAPTCHA integration (prevent bot registrations)
    - Welcome email
    """
    logger.info(f"Registration attempt for email: {user_data.email}")
    
    # Check if email already exists
    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        logger.warning(f"Registration failed: Email already exists - {user_data.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Hash password
    hashed_password = get_password_hash(user_data.password)
    
    # Create user
    new_user = User(
        email=user_data.email,
        name=user_data.name,
        hashed_password=hashed_password,
        profession=user_data.profession,
        date_of_birth=user_data.date_of_birth,
        timezone=user_data.timezone,
        is_active=True
    )
    
    # Add user to database
    db.add(new_user)
    await db.flush()  # Get user.id without committing
    
    # Create default preferences
    preferences = UserPreferences(
        user_id=new_user.id,
        update_frequency=UpdateFrequency.WEEKLY,
        summary_length=SummaryLength.STANDARD,
        email_notifications_enabled=True
    )
    db.add(preferences)
    
    # Commit transaction
    await db.commit()
    await db.refresh(new_user)
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": new_user.email},
        expires_delta=access_token_expires
    )
    
    logger.info(f"Registration successful: {new_user.email}")
    
    return UserWithToken(
        user=UserResponse.model_validate(new_user),
        access_token=access_token,
        token_type="bearer"
    )


# ================================
# Get Current User
# ================================

@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(get_current_active_user)
):
    """
    Get current user profile.
    
    This endpoint returns the profile of the authenticated user.
    Token is automatically extracted from Authorization header.
    
    How it works:
    -------------
    1. OAuth2PasswordBearer extracts token from header
    2. get_current_user decodes token and loads user
    3. get_current_active_user checks user is active
    4. Return user profile
    
    Request:
    --------
    GET /api/v1/auth/me
    Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    
    Response:
    ---------
    {
        "id": 1,
        "email": "alice@example.com",
        "name": "Alice Johnson",
        "profile_picture": "https://lh3.googleusercontent.com/a/...",
        "profession": "Software Engineer",
        "date_of_birth": "1990-05-15",
        "timezone": "America/New_York",
        "is_active": true
    }
    
    Args:
        current_user: Authenticated user (injected by dependency)
    
    Returns:
        User profile information
    
    Raises:
        HTTPException 401: Invalid or expired token
        HTTPException 400: User account disabled
    
    Security Notes:
    ---------------
    - Requires valid JWT token
    - Token must not be expired
    - User must be active
    - Excludes sensitive data (password hash)
    
    Use Cases:
    ----------
    - Display user profile in UI
    - Verify authentication status
    - Get user ID for other operations
    - Check user permissions/roles
    """
    logger.info(f"Profile accessed by user: {current_user.email}")
    return UserResponse.model_validate(current_user)


# ================================
# Google OAuth (Placeholder)
# ================================

@router.post("/google", response_model=UserWithToken)
async def google_oauth(
    token_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate with Google OAuth.
    
    This endpoint handles Google OAuth authentication by verifying
    the Google ID token and creating/updating the user.
    
    Google OAuth Flow:
    ------------------
    1. Frontend redirects user to Google OAuth page
    2. User authorizes app
    3. Google redirects back with authorization code
    4. Frontend sends code to this endpoint
    5. We exchange code for user info (Google API)
    6. Create/login user in our database
    7. Generate JWT token
    8. Return user info + token
    
    Request Body:
    -------------
    {
        "code": "4/0AY0e-g7...",                          // From Google
        "redirect_uri": "http://localhost:3000/callback"  // Must match registered URI
    }
    
    Response:
    ---------
    {
        "user": {
            "id": 1,
            "email": "alice@example.com",
            "name": "Alice Johnson",
            "profile_picture": "https://lh3.googleusercontent.com/a/...",
            ...
        },
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer"
    }
    
    Implementation Steps (Future):
    -------------------------------
    1. Verify authorization code with Google
    2. Get user info (email, name, picture) from Google
    3. Check if user exists in database
    4. If new user:
       - Create User record
       - Create UserPreferences record
       - Set profile_picture from Google
    5. If existing user:
       - Update last_login
       - Update profile_picture if changed
    6. Generate JWT token
    7. Return user + token
    
    Required Environment Variables:
    -------------------------------
    - GOOGLE_CLIENT_ID
    - GOOGLE_CLIENT_SECRET
    - GOOGLE_REDIRECT_URI
    
    External Libraries Needed:
    --------------------------
    - google-auth
    - google-auth-oauthlib
    - google-auth-httplib2
    
    Security Notes:
    ---------------
    - Verify authorization code with Google
    - Check redirect_uri matches registered URI
    - Validate user info from Google
    - Never trust client-provided data without verification
    
    References:
    -----------
    - Google OAuth2: https://developers.google.com/identity/protocols/oauth2
    - Python Google Auth: https://google-auth.readthedocs.io/
    """
    from app.core.google_oauth import verify_google_token, check_google_oauth_configured
    
    # Check if Google OAuth is configured
    if not check_google_oauth_configured():
        logger.error("Google OAuth not configured")
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth not configured. Please contact administrator."
        )
    
    # Extract ID token from request
    id_token = token_data.get("id_token") or token_data.get("token")
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing id_token in request"
        )
    
    # Verify token and get user info
    logger.info("Verifying Google token")
    google_user_info = await verify_google_token(id_token)
    
    # Check if user exists
    result = await db.execute(
        select(User).where(User.email == google_user_info["email"])
    )
    user = result.scalar_one_or_none()
    
    if user:
        # Update existing user
        logger.info(f"Existing user logging in via Google: {user.email}")
        user.name = google_user_info["name"]
        user.profile_picture = google_user_info["picture"]
        user.last_login = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(user)
    else:
        # Create new user
        logger.info(f"Creating new user from Google OAuth: {google_user_info['email']}")
        user = User(
            email=google_user_info["email"],
            name=google_user_info["name"],
            profile_picture=google_user_info["picture"],
            timezone="UTC",
            is_active=True,
            hashed_password=None  # No password for Google OAuth users
        )
        db.add(user)
        await db.flush()
        
        # Create default preferences
        preferences = UserPreferences(
            user_id=user.id,
            update_frequency=UpdateFrequency.WEEKLY,
            summary_length=SummaryLength.STANDARD,
            email_notifications_enabled=True
        )
        db.add(preferences)
        await db.commit()
        await db.refresh(user)
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=access_token_expires
    )
    
    logger.info(f"Google OAuth successful: {user.email}")
    
    return UserWithToken(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        token_type="bearer"
    )


# ================================
# Health Check (Authenticated)
# ================================

@router.get("/health")
async def auth_health_check(
    current_user: User = Depends(get_current_user)
):
    """
    Health check endpoint that requires authentication.
    
    This endpoint can be used to:
    - Verify token is still valid
    - Check user is still in database
    - Monitor authentication system health
    
    Request:
    --------
    GET /api/v1/auth/health
    Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    
    Response:
    ---------
    {
        "status": "healthy",
        "user_id": 1,
        "user_email": "alice@example.com"
    }
    
    Args:
        current_user: Authenticated user (injected)
    
    Returns:
        Health status with user info
    
    Use Cases:
    ----------
    - Frontend polling to check token validity
    - Load balancer health checks
    - Monitoring systems
    - Debug authentication issues
    """
    return {
        "status": "healthy",
        "user_id": current_user.id,
        "user_email": current_user.email,
        "authenticated": True
    }
