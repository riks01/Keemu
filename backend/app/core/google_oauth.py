"""
Google OAuth utilities.

This module provides functions for Google OAuth authentication.

References:
-----------
- Google OAuth2: https://developers.google.com/identity/protocols/oauth2
- google-auth library: https://google-auth.readthedocs.io/
"""

from typing import Dict

from google.auth.transport import requests
from google.oauth2 import id_token
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def verify_google_token(token: str) -> Dict[str, str]:
    """
    Verify Google ID token and extract user information.
    
    This function verifies a Google ID token received from the frontend
    and extracts the user's information (email, name, picture).
    
    How Google OAuth Works:
    -----------------------
    1. Frontend redirects user to Google OAuth consent page
    2. User authorizes the application
    3. Google redirects back to frontend with authorization code
    4. Frontend exchanges code for ID token (using Google's SDK)
    5. Frontend sends ID token to this endpoint
    6. We verify the token with Google
    7. Extract user info from verified token
    8. Create/update user in our database
    9. Generate our own JWT token
    10. Return JWT token to frontend
    
    Args:
        token: Google ID token from frontend
    
    Returns:
        Dictionary with user info:
        {
            "email": "user@gmail.com",
            "name": "John Doe",
            "picture": "https://lh3.googleusercontent.com/...",
            "email_verified": True,
            "sub": "google_user_id"
        }
    
    Raises:
        HTTPException 401: If token is invalid or verification fails
    
    Example:
        try:
            user_info = await verify_google_token(id_token_string)
            print(f"User: {user_info['email']}")
        except HTTPException:
            print("Invalid token")
    
    Security Notes:
    ---------------
    - Always verify tokens server-side
    - Never trust tokens without verification
    - Check token audience matches your client ID
    - Check token issuer is Google
    - Verify token expiration
    
    Token Structure:
    ----------------
    Google ID tokens contain:
    - sub: Google user ID (unique identifier)
    - email: User's email address
    - email_verified: Whether email is verified
    - name: User's full name
    - picture: Profile picture URL
    - iss: Issuer (accounts.google.com)
    - aud: Audience (your client ID)
    - exp: Expiration timestamp
    - iat: Issued at timestamp
    """
    try:
        # Verify token with Google
        idinfo = id_token.verify_oauth2_token(
            token,
            requests.Request(),
            settings.GOOGLE_CLIENT_ID
        )
        
        # Verify token issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            logger.warning(f"Invalid token issuer: {idinfo['iss']}")
            raise ValueError('Invalid issuer')
        
        # Verify email is verified
        if not idinfo.get('email_verified', False):
            logger.warning(f"Email not verified: {idinfo.get('email')}")
            raise ValueError('Email not verified')
        
        logger.info(f"Google token verified for user: {idinfo.get('email')}")
        
        return {
            "email": idinfo["email"],
            "name": idinfo.get("name", ""),
            "picture": idinfo.get("picture", ""),
            "email_verified": idinfo.get("email_verified", False),
            "sub": idinfo["sub"]  # Google user ID
        }
        
    except ValueError as e:
        logger.error(f"Token verification failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Google token: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error verifying token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not verify Google token"
        )


def check_google_oauth_configured() -> bool:
    """
    Check if Google OAuth is properly configured.
    
    Returns:
        True if configured, False otherwise
    """
    return bool(
        settings.GOOGLE_CLIENT_ID and 
        settings.GOOGLE_CLIENT_SECRET
    )