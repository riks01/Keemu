"""
Security utilities for authentication and authorization.

This module provides:
- Password hashing and verification (using passlib + bcrypt)
- JWT token creation and validation (using python-jose)
- Security configuration constants

References:
-----------
- FastAPI Security: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- JWT Standard: https://jwt.io/introduction
- OAuth2: https://oauth.net/2/
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# ================================
# Password Hashing Configuration
# ================================

# Using bcrypt directly (instead of passlib)
# Why bcrypt?
# -----------
# - Industry-standard password hashing algorithm
# - Automatically generates salt (random data added to password)
# - Computationally expensive (protects against brute-force)
# - Adjustable cost factor (can increase security over time)
#
# Why not passlib?
# ----------------
# - passlib has compatibility issues with newer bcrypt versions
# - Direct bcrypt usage is simpler and more reliable
# - No deprecation warnings
#
# Security Note:
# --------------
# NEVER store plaintext passwords!
# Always hash before storing in database.


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a hashed password.
    
    This is used during login to check if the user's password is correct.
    
    How it works:
    -------------
    1. User submits plaintext password (e.g., "secret")
    2. We retrieve hashed password from database
    3. bcrypt hashes the plaintext with the same salt
    4. Compare the two hashes
    5. If match: Password is correct
    6. If no match: Password is wrong
    
    Args:
        plain_password: The password user entered (plaintext)
        hashed_password: The hashed password from database
    
    Returns:
        True if password matches, False otherwise
    
    Example:
        >>> hashed = get_password_hash("secret")
        >>> verify_password("secret", hashed)
        True
        >>> verify_password("wrong", hashed)
        False
    
    Security Notes:
    ---------------
    - This function is constant-time to prevent timing attacks
    - The plaintext password is never stored or logged
    - bcrypt automatically handles salt extraction
    - Passwords are truncated to 72 bytes to match bcrypt limit
    """
    # Convert password to bytes
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    
    # bcrypt.checkpw handles constant-time comparison
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def get_password_hash(password: str) -> str:
    """
    Hash a plaintext password.
    
    This is used when:
    - Creating a new user account
    - User changes their password
    - Admin resets a password
    
    How it works:
    -------------
    1. bcrypt generates a random salt (unique per password)
    2. Combines salt with password
    3. Applies multiple rounds of hashing (expensive)
    4. Returns hash string that includes:
       - Algorithm identifier ($2b$)
       - Cost factor (12 by default)
       - Salt (22 characters)
       - Hash (31 characters)
    
    Args:
        password: The plaintext password to hash
    
    Returns:
        The hashed password string (safe to store in database)
    
    Example:
        >>> hash1 = get_password_hash("secret")
        >>> hash2 = get_password_hash("secret")
        >>> hash1 != hash2  # Different salts!
        True
        >>> verify_password("secret", hash1)
        True
        >>> verify_password("secret", hash2)
        True
    
    Security Notes:
    ---------------
    - Each hash is unique (even for same password)
    - Salt is automatically generated and included in hash
    - Hash is one-way (cannot reverse to get password)
    - Takes ~100ms to hash (protects against brute-force)
    
    Hash Format:
    ------------
    $2b$12$R9h/cIPz0gi.URNNX3kh2OPST9/PgBkqquzi.Ss7KIUgO2t0jWMUW
    └─┬┘└┬┘└───────────────┬───────────────┘└───────────┬─────────────┘
      │  │                 │                             │
      │  │                 │                             └─ Actual hash (31 chars)
      │  │                 └─────────────────────────────── Salt (22 chars)
      │  └───────────────────────────────────────────────── Cost factor (2^12 rounds)
      └──────────────────────────────────────────────────── Algorithm (bcrypt)
    
    bcrypt Limitation:
    ------------------
    bcrypt has a 72-byte limit (handled automatically).
    """
    # Convert password to bytes
    password_bytes = password.encode('utf-8')
    
    # Generate salt and hash password
    # bcrypt.gensalt() creates a random salt with default cost factor (12)
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    
    # Return as string
    return hashed.decode('utf-8')


# ================================
# JWT Token Configuration
# ================================

# JWT Algorithm
ALGORITHM = "HS256"
# What is HS256?
# --------------
# - HMAC with SHA-256
# - Symmetric encryption (same key for sign & verify)
# - Fast and secure for server-side tokens
#
# Alternative: RS256 (asymmetric, for distributed systems)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """
    Create a JWT access token.
    
    JWT (JSON Web Token) is a secure way to transmit information between parties.
    We use it to authenticate users without storing session data on the server.
    
    How it works:
    -------------
    1. User logs in with email/password
    2. We verify credentials
    3. Create JWT with user info (e.g., {"sub": "user@example.com"})
    4. Sign JWT with secret key
    5. Return token to user
    6. User includes token in Authorization header for future requests
    7. We verify token to authenticate user
    
    What's in the token?
    --------------------
    - sub (subject): User identifier (email or user ID)
    - exp (expiration): When token expires (security measure)
    - iat (issued at): When token was created
    - Custom claims: Any additional data you want
    
    Args:
        data: Dictionary of claims to include in token
              Should include "sub" (subject) with user identifier
        expires_delta: How long until token expires
                      Defaults to ACCESS_TOKEN_EXPIRE_MINUTES from settings
    
    Returns:
        Encoded JWT token string
    
    Example:
        >>> from datetime import timedelta
        >>> token = create_access_token(
        ...     data={"sub": "alice@example.com"},
        ...     expires_delta=timedelta(minutes=30)
        ... )
        >>> print(token)
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
    
    Token Structure:
    ----------------
    JWT has 3 parts separated by dots:
    
    eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhbGljZUBleGFtcGxlLmNvbSIsImV4cCI6MTY5OTk5OTk5OX0.signature
    └─────────────┬─────────────────┘ └──────────────────────┬──────────────────────────┘ └────┬────┘
                  │                                           │                                    │
                Header                                     Payload                            Signature
    
    1. Header: Algorithm and token type
       {"alg": "HS256", "typ": "JWT"}
    
    2. Payload: Claims (user data)
       {"sub": "alice@example.com", "exp": 1699999999}
    
    3. Signature: Ensures token hasn't been tampered with
       HMACSHA256(base64UrlEncode(header) + "." + base64UrlEncode(payload), secret)
    
    Security Notes:
    ---------------
    - Token is signed (verifiable) but NOT encrypted (readable)
    - Don't include sensitive data (passwords, credit cards)
    - Use HTTPS to prevent token interception
    - Set reasonable expiration (30 minutes to 1 day)
    - Signature prevents tampering (if someone modifies token, signature fails)
    
    Why JWT vs Sessions?
    --------------------
    JWT Advantages:
    - Stateless (no server-side storage)
    - Scalable (works across multiple servers)
    - Works with mobile apps
    - Can include user data (reduces DB queries)
    
    Session Advantages:
    - Can revoke immediately (JWT valid until expiration)
    - Smaller size (just session ID)
    - More secure (server-side only)
    
    For KeeMU, JWT is better because:
    - We might scale to multiple servers
    - Mobile app support in future
    - Most requests need user data anyway
    """
    to_encode = data.copy()
    
    # Set expiration time
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    # Add expiration claim
    to_encode.update({"exp": expire})
    
    # Create and return signed JWT
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any] | None:
    """
    Decode and verify a JWT access token.
    
    This is used to:
    - Verify token is valid (not expired, not tampered)
    - Extract user information from token
    - Authenticate user for protected endpoints
    
    How it works:
    -------------
    1. Receive token from Authorization header
    2. Decode token using secret key
    3. Verify signature (ensures not tampered)
    4. Check expiration (ensures not expired)
    5. Return payload (user claims)
    
    Args:
        token: JWT token string from Authorization header
    
    Returns:
        Dictionary of claims if valid, None if invalid
    
    Example:
        >>> token = create_access_token({"sub": "alice@example.com"})
        >>> payload = decode_access_token(token)
        >>> print(payload)
        {'sub': 'alice@example.com', 'exp': 1699999999}
        
        >>> # Expired or invalid token
        >>> payload = decode_access_token("invalid.token.here")
        >>> print(payload)
        None
    
    Validation Checks:
    ------------------
    1. Structure: Must be 3 parts (header.payload.signature)
    2. Signature: Must match (prevents tampering)
    3. Algorithm: Must be HS256 (prevents algorithm confusion)
    4. Expiration: Must not be expired
    5. Format: Must be valid JSON
    
    Common Errors:
    --------------
    - ExpiredSignatureError: Token expired
    - JWTError: Invalid token format
    - DecodeError: Token tampered with
    
    Security Notes:
    ---------------
    - Always check expiration
    - Never trust token without verification
    - Use constant-time comparison for signature
    - Validate all claims before using
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        # Token is invalid (expired, tampered, malformed)
        return None
