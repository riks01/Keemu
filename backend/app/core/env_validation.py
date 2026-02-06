"""
Environment variable validation and security checks.

This module validates that all required environment variables are properly
configured before the application starts.
"""

import sys
from typing import List, Tuple, Optional
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EnvironmentValidationError(Exception):
    """Raised when environment validation fails."""
    pass


def validate_secret_key(key_name: str, key_value: Optional[str], min_length: int = 32) -> List[str]:
    """
    Validate that a secret key meets security requirements.
    
    Args:
        key_name: Name of the key (for error messages)
        key_value: The key value to validate
        min_length: Minimum required length
        
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    if not key_value:
        errors.append(f"{key_name} is not set")
        return errors
    
    if len(key_value) < min_length:
        errors.append(
            f"{key_name} is too short (must be at least {min_length} characters)"
        )
    
    # Check if it's a default/example value
    if "change" in key_value.lower() or "your-" in key_value.lower() or "example" in key_value.lower():
        errors.append(
            f"{key_name} appears to be a placeholder value - update with a real secret key"
        )
    
    # Warn if keys are the same
    if key_name == "JWT_SECRET_KEY" and key_value == settings.SECRET_KEY:
        errors.append(
            "JWT_SECRET_KEY should be different from SECRET_KEY for security"
        )
    
    return errors


def validate_database_url() -> List[str]:
    """
    Validate database URL configuration.
    
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    if not settings.DATABASE_URL:
        errors.append("DATABASE_URL is not set")
        return errors
    
    # Check for async driver
    if not settings.DATABASE_URL.startswith("postgresql+asyncpg://"):
        errors.append(
            "DATABASE_URL must use asyncpg driver (format: postgresql+asyncpg://...)"
        )
    
    # Check for default password in production
    if settings.is_production and "keemu_password" in settings.DATABASE_URL:
        errors.append(
            "DATABASE_URL contains default password - update with a secure password in production"
        )
    
    return errors


def validate_redis_url() -> List[str]:
    """
    Validate Redis URL configuration.
    
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    if not settings.REDIS_URL:
        errors.append("REDIS_URL is not set")
        return errors
    
    if not settings.REDIS_URL.startswith("redis://"):
        errors.append(
            "REDIS_URL must start with redis:// (format: redis://host:port/db)"
        )
    
    return errors


def validate_rag_dependencies() -> List[str]:
    """
    Validate that RAG system dependencies are configured.
    
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    warnings = []
    
    # Anthropic API key is REQUIRED for RAG to work
    if not settings.ANTHROPIC_API_KEY:
        errors.append(
            "ANTHROPIC_API_KEY is not set - RAG system will not work without this"
        )
    elif "your-" in settings.ANTHROPIC_API_KEY.lower():
        errors.append(
            "ANTHROPIC_API_KEY appears to be a placeholder - update with real API key"
        )
    
    # Warn about optional but useful services
    if not settings.YOUTUBE_API_KEY:
        warnings.append(
            "YOUTUBE_API_KEY not set - YouTube content collection will be disabled"
        )
    
    if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
        warnings.append(
            "Reddit credentials not set - Reddit content collection will be disabled"
        )
    
    if not settings.SENDGRID_API_KEY:
        warnings.append(
            "SENDGRID_API_KEY not set - Email notifications will be disabled"
        )
    
    # Log warnings
    for warning in warnings:
        logger.warning("environment_validation_warning", message=warning)
    
    return errors


def validate_production_settings() -> List[str]:
    """
    Validate production-specific settings.
    
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    if not settings.is_production:
        return errors
    
    # Check DEBUG is disabled
    if settings.DEBUG:
        errors.append("DEBUG must be false in production")
    
    # Check Sentry is configured
    if not settings.SENTRY_DSN:
        logger.warning(
            "sentry_not_configured",
            message="SENTRY_DSN not set in production - error tracking disabled"
        )
    
    # Check ALLOWED_ORIGINS doesn't include localhost
    if "localhost" in ",".join(settings.ALLOWED_ORIGINS):
        logger.warning(
            "localhost_in_allowed_origins",
            message="ALLOWED_ORIGINS includes localhost in production - may be insecure"
        )
    
    # Check LOG_FORMAT is JSON
    if settings.LOG_FORMAT != "json":
        logger.warning(
            "log_format_not_json",
            message="LOG_FORMAT should be 'json' in production for better log aggregation"
        )
    
    # Check LOG_LEVEL is not DEBUG
    if settings.LOG_LEVEL == "DEBUG":
        logger.warning(
            "log_level_is_debug",
            message="LOG_LEVEL is DEBUG in production - may impact performance"
        )
    
    return errors


def validate_environment() -> Tuple[bool, List[str]]:
    """
    Validate all environment variables.
    
    Returns:
        (is_valid, list_of_errors)
    """
    all_errors = []
    
    logger.info(
        "validating_environment",
        app_env=settings.APP_ENV,
        app_name=settings.APP_NAME
    )
    
    # Validate critical settings
    all_errors.extend(validate_secret_key("SECRET_KEY", settings.SECRET_KEY))
    all_errors.extend(validate_secret_key("JWT_SECRET_KEY", settings.JWT_SECRET_KEY))
    all_errors.extend(validate_database_url())
    all_errors.extend(validate_redis_url())
    all_errors.extend(validate_rag_dependencies())
    
    # Validate production settings
    if settings.is_production:
        all_errors.extend(validate_production_settings())
    
    # Report results
    if all_errors:
        logger.error(
            "environment_validation_failed",
            errors=all_errors,
            error_count=len(all_errors)
        )
        return False, all_errors
    else:
        logger.info(
            "environment_validation_successful",
            app_env=settings.APP_ENV,
            features_enabled={
                "youtube": bool(settings.YOUTUBE_API_KEY),
                "reddit": bool(settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET),
                "sendgrid": bool(settings.SENDGRID_API_KEY),
                "sentry": bool(settings.SENTRY_DSN),
            }
        )
        return True, []


def validate_or_exit():
    """
    Validate environment and exit if validation fails.
    
    This should be called during application startup.
    """
    is_valid, errors = validate_environment()
    
    if not is_valid:
        logger.critical(
            "startup_aborted_invalid_environment",
            errors=errors
        )
        print("\n❌ ENVIRONMENT VALIDATION FAILED\n")
        print("The following configuration errors were found:\n")
        for i, error in enumerate(errors, 1):
            print(f"  {i}. {error}")
        print("\nPlease fix these errors and restart the application.")
        print("See env_template for configuration reference.\n")
        sys.exit(1)
    
    logger.info("environment_validation_passed")

