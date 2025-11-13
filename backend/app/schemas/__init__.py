"""
Pydantic schemas for request/response validation.

Import all schemas here for easy access.
"""

from app.schemas.auth import (
    ErrorResponse,
    GoogleAuthRequest,
    Token,
    TokenData,
    UserLogin,
    UserRegister,
    UserResponse,
    UserWithToken,
)

__all__ = [
    # Authentication
    "Token",
    "TokenData",
    "UserLogin",
    "UserRegister",
    "UserResponse",
    "UserWithToken",
    "GoogleAuthRequest",
    "ErrorResponse",
]
