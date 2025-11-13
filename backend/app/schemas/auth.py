"""
Authentication schemas (Pydantic models for request/response).

These schemas define:
- Request formats (what client sends)
- Response formats (what server returns)
- Data validation rules
- OpenAPI documentation

References:
-----------
- Pydantic: https://docs.pydantic.dev/latest/
- FastAPI Request Body: https://fastapi.tiangolo.com/tutorial/body/
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ================================
# Authentication Schemas
# ================================

class Token(BaseModel):
    """
    JWT token response.
    
    Returned after successful login.
    Client should store this token and include it in Authorization header.
    
    Example response:
        {
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "token_type": "bearer"
        }
    
    Client should send in future requests:
        Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    """
    access_token: str = Field(
        ..., 
        description="JWT access token",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."]
    )
    token_type: str = Field(
        default="bearer",
        description="Token type (always 'bearer' for JWT)"
    )


class TokenData(BaseModel):
    """
    Data extracted from JWT token.
    
    Used internally to validate and process tokens.
    Contains the claims we store in the JWT.
    """
    email: Optional[str] = Field(
        None,
        description="User's email address (from 'sub' claim)"
    )


# ================================
# User Registration/Login
# ================================

class UserLogin(BaseModel):
    """
    User login request.
    
    Client sends email and password to get JWT token.
    
    Example request:
        POST /api/v1/auth/login
        {
            "email": "alice@example.com",
            "password": "secret"
        }
    
    Note: For now, we only support Google OAuth.
    This schema is for future password-based auth.
    """
    email: EmailStr = Field(
        ...,
        description="User's email address",
        examples=["alice@example.com"]
    )
    password: str = Field(
        ...,
        min_length=8,
        description="User's password (minimum 8 characters)",
        examples=["SecurePassword123!"]
    )


class UserRegister(BaseModel):
    """
    User registration request.
    
    Client sends user details to create new account.
    
    Example request:
        POST /api/v1/auth/register
        {
            "email": "alice@example.com",
            "name": "Alice Johnson",
            "password": "SecurePassword123!",
            "profession": "Software Engineer",
            "date_of_birth": "1990-05-15"
        }
    
    Note: For now, we only support Google OAuth.
    This schema is for future password-based registration.
    """
    email: EmailStr = Field(
        ...,
        description="User's email address",
        examples=["alice@example.com"]
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="User's full name",
        examples=["Alice Johnson"]
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=100,
        description="User's password (minimum 8 characters)",
        examples=["SecurePassword123!"]
    )
    profession: Optional[str] = Field(
        None,
        max_length=100,
        description="User's profession or occupation",
        examples=["Software Engineer", "Product Manager", "Student"]
    )
    date_of_birth: Optional[date] = Field(
        None,
        description="User's date of birth (YYYY-MM-DD)",
        examples=["1990-05-15"]
    )
    timezone: str = Field(
        default="UTC",
        max_length=50,
        description="User's timezone (IANA timezone name)",
        examples=["America/New_York", "Europe/London", "Asia/Tokyo"]
    )


# ================================
# User Response Schemas
# ================================

class UserResponse(BaseModel):
    """
    User information response.
    
    Returned when fetching user profile or after registration.
    Excludes sensitive information like password hash.
    
    Example response:
        {
            "id": 1,
            "email": "alice@example.com",
            "name": "Alice Johnson",
            "profession": "Software Engineer",
            "date_of_birth": "1990-05-15",
            "timezone": "America/New_York",
            "is_active": true
        }
    """
    id: int = Field(..., description="User's unique ID")
    email: str = Field(..., description="User's email address")
    name: str = Field(..., description="User's full name")
    profile_picture: Optional[str] = Field(None, description="URL to profile picture")
    profession: Optional[str] = Field(None, description="User's profession")
    date_of_birth: Optional[date] = Field(None, description="User's date of birth")
    timezone: str = Field(..., description="User's timezone")
    is_active: bool = Field(..., description="Whether user account is active")
    
    model_config = {
        "from_attributes": True  # Allows converting SQLAlchemy model to Pydantic
    }


class UserWithToken(BaseModel):
    """
    User information with JWT token.
    
    Returned after successful login or registration.
    Contains both user details and authentication token.
    
    Example response:
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
    """
    user: UserResponse = Field(..., description="User information")
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")


# ================================
# Google OAuth Schemas
# ================================

class GoogleAuthRequest(BaseModel):
    """
    Google OAuth authentication request.
    
    Client sends authorization code from Google OAuth flow.
    We exchange it for user info and create/login user.
    
    Example request:
        POST /api/v1/auth/google
        {
            "code": "4/0AY0e-g7...",
            "redirect_uri": "http://localhost:3000/auth/callback"
        }
    
    OAuth Flow:
    -----------
    1. User clicks "Sign in with Google"
    2. Redirect to Google OAuth page
    3. User authorizes app
    4. Google redirects back with code
    5. Frontend sends code to this endpoint
    6. We exchange code for user info
    7. Create/login user
    8. Return JWT token
    """
    code: str = Field(
        ...,
        description="Authorization code from Google OAuth",
        examples=["4/0AY0e-g7..."]
    )
    redirect_uri: str = Field(
        ...,
        description="Redirect URI used in OAuth flow (must match registered URI)",
        examples=["http://localhost:3000/auth/callback"]
    )


# ================================
# Error Responses
# ================================

class ErrorResponse(BaseModel):
    """
    Standard error response format.
    
    Used for all API errors.
    
    Example:
        {
            "detail": "Invalid credentials"
        }
    """
    detail: str = Field(..., description="Error message")


# ================================
# Examples for API Documentation
# ================================

# These examples will appear in Swagger UI docs

LOGIN_EXAMPLE = {
    "email": "alice@example.com",
    "password": "SecurePassword123!"
}

REGISTER_EXAMPLE = {
    "email": "alice@example.com",
    "name": "Alice Johnson",
    "password": "SecurePassword123!",
    "profession": "Software Engineer",
    "date_of_birth": "1990-05-15",
    "timezone": "America/New_York"
}

TOKEN_RESPONSE_EXAMPLE = {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhbGljZUBleGFtcGxlLmNvbSIsImV4cCI6MTY5OTk5OTk5OX0.signature",
    "token_type": "bearer"
}

USER_RESPONSE_EXAMPLE = {
    "id": 1,
    "email": "alice@example.com",
    "name": "Alice Johnson",
    "profile_picture": "https://lh3.googleusercontent.com/a/...",
    "profession": "Software Engineer",
    "date_of_birth": "1990-05-15",
    "timezone": "America/New_York",
    "is_active": True
}
