"""
Configuration management using Pydantic Settings.
All environment variables are loaded and validated here.
"""

from typing import List, Literal, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ================================
    # Application Configuration
    # ================================
    APP_NAME: str = "KeeMU"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    SECRET_KEY: str = Field(..., min_length=32)

    # API Configuration
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8000"

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def parse_origins(cls, v: str) -> List[str]:
        """Parse comma-separated origins into list."""
        return [origin.strip() for origin in v.split(",")]

    # ================================
    # Database Configuration
    # ================================
    DATABASE_URL: str = Field(..., description="PostgreSQL connection string")
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10

    # ================================
    # Redis Configuration
    # ================================
    REDIS_URL: str = "redis://redis:6379/0"

    # ================================
    # JWT Authentication
    # ================================
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minutes for access tokens
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # 7 days for refresh tokens
    
    # JWT Algorithm (HS256 = HMAC with SHA-256)
    # This is the standard algorithm for symmetric key JWT
    JWT_ALGORITHM: str = "HS256"
    
    # ================================
    # Google OAuth
    # ================================
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    # ================================
    # YouTube API
    # ================================
    YOUTUBE_API_KEY: Optional[str] = None
    YOUTUBE_MAX_VIDEOS_PER_FETCH: int = 50
    YOUTUBE_QUOTA_LIMIT_PER_DAY: int = 10000
    YOUTUBE_REQUEST_TIMEOUT: int = 30
    YOUTUBE_RETRY_ATTEMPTS: int = 3
    YOUTUBE_RETRY_DELAY_SECONDS: int = 5
    YOUTUBE_PREFERRED_TRANSCRIPT_LANGUAGES: str = "en,en-US,en-GB"
    YOUTUBE_CHECK_INTERVAL_HOURS: int = 6  # Check for new content every 6 hours

    @field_validator("YOUTUBE_PREFERRED_TRANSCRIPT_LANGUAGES")
    @classmethod
    def parse_transcript_languages(cls, v: str) -> List[str]:
        """Parse comma-separated languages into list."""
        return [lang.strip() for lang in v.split(",")]
    
    # ================================
    # Rate Limiting
    # ================================
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_ANONYMOUS: int = 20  # Requests per minute for anonymous users
    RATE_LIMIT_AUTHENTICATED: int = 100  # Requests per minute for authenticated users

    # ================================
    # Reddit API
    # ================================
    REDDIT_CLIENT_ID: Optional[str] = None
    REDDIT_CLIENT_SECRET: Optional[str] = None
    REDDIT_USER_AGENT: str = "KeeMU/1.0"

    # ================================
    # AI Service Configuration
    # ================================
    # Anthropic Claude
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-3-5-haiku-20241022"
    ANTHROPIC_MAX_TOKENS: int = 4096

    # Google Gemini (backup/optional)
    GEMINI_API_KEY: Optional[str] = None

    # OpenAI (for Whisper transcription fallback)
    OPENAI_API_KEY: Optional[str] = None

    # ================================
    # Embedding Configuration
    # ================================
    EMBEDDING_MODEL: str = "google/embeddinggemma-300m"
    EMBEDDING_DIMENSION: int = 768
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_DEVICE: Literal["cpu", "cuda", "mps"] = "cpu"

    # ================================
    # Vector Database Configuration
    # ================================
    VECTOR_DB_TYPE: Literal["pgvector", "pinecone"] = "pgvector"

    # Pinecone (optional)
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_ENVIRONMENT: Optional[str] = None
    PINECONE_INDEX_NAME: str = "keemu-embeddings"

    # ================================
    # Email Configuration
    # ================================
    SENDGRID_API_KEY: Optional[str] = None
    SENDGRID_FROM_EMAIL: Optional[str] = None
    SENDGRID_FROM_NAME: str = "KeeMU"

    # ================================
    # JWT Configuration
    # ================================
    JWT_SECRET_KEY: str = Field(..., min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    JWT_REFRESH_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 days

    # ================================
    # Content Collection Configuration
    # ================================
    YOUTUBE_CHECK_INTERVAL_HOURS: int = 6
    REDDIT_CHECK_INTERVAL_HOURS: int = 1
    BLOG_CHECK_INTERVAL_HOURS: int = 12
    MAX_CONTENT_AGE_DAYS: int = 90

    # ================================
    # Processing Configuration
    # ================================
    USE_LOCAL_WHISPER: bool = False
    CHUNK_SIZE_TOKENS: int = 800
    CHUNK_OVERLAP_TOKENS: int = 100
    MAX_CHUNKS_PER_CONTENT: int = 50

    # ================================
    # RAG Configuration
    # ================================
    RAG_TOP_K_RETRIEVAL: int = 15
    RAG_TOP_K_RERANK: int = 5
    RAG_MAX_CONTEXT_TOKENS: int = 3000

    # ================================
    # Summary Configuration
    # ================================
    SUMMARY_SOURCE_MAX_WORDS: int = 300
    SUMMARY_OVERALL_MAX_WORDS: int = 800

    # ================================
    # Rate Limiting
    # ================================
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    # ================================
    # Celery Configuration
    # ================================
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/0"
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    # Celery accept content as comma-separated string, we'll parse it
    CELERY_ACCEPT_CONTENT: str = "json"
    CELERY_TIMEZONE: str = "UTC"
    CELERY_ENABLE_UTC: bool = True
    
    @property
    def celery_accept_content_list(self) -> List[str]:
        """Parse CELERY_ACCEPT_CONTENT into a list."""
        return [item.strip() for item in self.CELERY_ACCEPT_CONTENT.split(",")]

    # ================================
    # Logging Configuration
    # ================================
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "json"

    # ================================
    # Monitoring (optional)
    # ================================
    SENTRY_DSN: Optional[str] = None

    # ================================
    # Feature Flags
    # ================================
    ENABLE_EMAIL_NOTIFICATIONS: bool = True
    ENABLE_COST_TRACKING: bool = True
    ENABLE_ANALYTICS: bool = True

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.APP_ENV == "production"


# Global settings instance
settings = Settings()
