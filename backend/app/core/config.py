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
    APP_NAME: str = Field("KeeMU", json_schema_extra={"env": "APP_NAME"})
    APP_ENV: Literal["development", "staging", "production"] = Field("development", json_schema_extra={"env": "APP_ENV"})
    DEBUG: bool = Field(True, json_schema_extra={"env": "DEBUG"})
    SECRET_KEY: str = Field(..., min_length=32, json_schema_extra={"env": "SECRET_KEY"})

    # API Configuration
    API_V1_PREFIX: str = Field("/api/v1", json_schema_extra={"env": "API_V1_PREFIX"})
    ALLOWED_ORIGINS: str = Field("http://localhost:3000,http://localhost:8000", json_schema_extra={"env": "ALLOWED_ORIGINS"})

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def parse_origins(cls, v: str) -> List[str]:
        """Parse comma-separated origins into list."""
        return [origin.strip() for origin in v.split(",")]

    # ================================
    # Database Configuration
    # ================================
    DATABASE_URL: str = Field(..., description="PostgreSQL connection string", json_schema_extra={"env": "DATABASE_URL"})
    DB_ECHO: bool = Field(False, json_schema_extra={"env": "DB_ECHO"})
    DB_POOL_SIZE: int = Field(20, json_schema_extra={"env": "DB_POOL_SIZE"})
    DB_MAX_OVERFLOW: int = Field(10, json_schema_extra={"env": "DB_MAX_OVERFLOW"})

    # ================================
    # Redis Configuration
    # ================================
    REDIS_URL: str = Field("redis://redis:6379/0", json_schema_extra={"env": "REDIS_URL"})

    # ================================
    # JWT Authentication
    # ================================
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(30, json_schema_extra={"env": "ACCESS_TOKEN_EXPIRE_MINUTES"})
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(7, json_schema_extra={"env": "REFRESH_TOKEN_EXPIRE_DAYS"})
    
    # JWT Algorithm (HS256 = HMAC with SHA-256)
    JWT_ALGORITHM: str = Field("HS256", json_schema_extra={"env": "JWT_ALGORITHM"})
    
    # ================================
    # Google OAuth
    # ================================
    GOOGLE_CLIENT_ID: Optional[str] = Field(None, json_schema_extra={"env": "GOOGLE_CLIENT_ID"})
    GOOGLE_CLIENT_SECRET: Optional[str] = Field(None, json_schema_extra={"env": "GOOGLE_CLIENT_SECRET"})
    GOOGLE_REDIRECT_URI: str = Field("http://localhost:8000/api/v1/auth/google/callback", json_schema_extra={"env": "GOOGLE_REDIRECT_URI"})

    # ================================
    # YouTube API
    # ================================
    YOUTUBE_API_KEY: Optional[str] = Field(None, json_schema_extra={"env": "YOUTUBE_API_KEY"})
    YOUTUBE_MAX_VIDEOS_PER_FETCH: int = Field(50, json_schema_extra={"env": "YOUTUBE_MAX_VIDEOS_PER_FETCH"})
    YOUTUBE_QUOTA_LIMIT_PER_DAY: int = Field(10000, json_schema_extra={"env": "YOUTUBE_QUOTA_LIMIT_PER_DAY"})
    YOUTUBE_REQUEST_TIMEOUT: int = Field(30, json_schema_extra={"env": "YOUTUBE_REQUEST_TIMEOUT"})
    YOUTUBE_RETRY_ATTEMPTS: int = Field(3, json_schema_extra={"env": "YOUTUBE_RETRY_ATTEMPTS"})
    YOUTUBE_RETRY_DELAY_SECONDS: int = Field(5, json_schema_extra={"env": "YOUTUBE_RETRY_DELAY_SECONDS"})
    YOUTUBE_PREFERRED_TRANSCRIPT_LANGUAGES: str = Field("en,en-US,en-GB", json_schema_extra={"env": "YOUTUBE_PREFERRED_TRANSCRIPT_LANGUAGES"})
    YOUTUBE_CHECK_INTERVAL_HOURS: int = Field(6, json_schema_extra={"env": "YOUTUBE_CHECK_INTERVAL_HOURS"})

    @field_validator("YOUTUBE_PREFERRED_TRANSCRIPT_LANGUAGES")
    @classmethod
    def parse_transcript_languages(cls, v: str) -> List[str]:
        """Parse comma-separated languages into list."""
        return [lang.strip() for lang in v.split(",")]
    
    # ================================
    # Rate Limiting
    # ================================
    RATE_LIMIT_ENABLED: bool = Field(True, json_schema_extra={"env": "RATE_LIMIT_ENABLED"})
    RATE_LIMIT_ANONYMOUS: int = Field(20, json_schema_extra={"env": "RATE_LIMIT_ANONYMOUS"})
    RATE_LIMIT_AUTHENTICATED: int = Field(100, json_schema_extra={"env": "RATE_LIMIT_AUTHENTICATED"})

    # ================================
    # Reddit API
    # ================================
    REDDIT_CLIENT_ID: Optional[str] = Field(None, json_schema_extra={"env": "REDDIT_CLIENT_ID"})
    REDDIT_CLIENT_SECRET: Optional[str] = Field(None, json_schema_extra={"env": "REDDIT_CLIENT_SECRET"})
    REDDIT_USER_AGENT: str = Field("KeeMU/1.0", json_schema_extra={"env": "REDDIT_USER_AGENT"})

    # ================================
    # AI Service Configuration
    # ================================
    ANTHROPIC_API_KEY: Optional[str] = Field(None, json_schema_extra={"env": "ANTHROPIC_API_KEY"})
    ANTHROPIC_MODEL: str = Field("claude-3-5-haiku-20241022", json_schema_extra={"env": "ANTHROPIC_MODEL"})
    ANTHROPIC_MAX_TOKENS: int = Field(4096, json_schema_extra={"env": "ANTHROPIC_MAX_TOKENS"})

    GEMINI_API_KEY: Optional[str] = Field(None, json_schema_extra={"env": "GEMINI_API_KEY"})
    OPENAI_API_KEY: Optional[str] = Field(None, json_schema_extra={"env": "OPENAI_API_KEY"})

    # ================================
    # Embedding Configuration
    # ================================
    EMBEDDING_MODEL: str = Field("ibm-granite/granite-embedding-107m-multilingual", json_schema_extra={"env": "EMBEDDING_MODEL"})
    EMBEDDING_DIMENSION: int = Field(384, json_schema_extra={"env": "EMBEDDING_DIMENSION"})
    EMBEDDING_BATCH_SIZE: int = Field(32, json_schema_extra={"env": "EMBEDDING_BATCH_SIZE"})
    EMBEDDING_DEVICE: Literal["cpu", "cuda", "mps"] = Field("cpu", json_schema_extra={"env": "EMBEDDING_DEVICE"})

    # ================================
    # Vector Database Configuration
    # ================================
    VECTOR_DB_TYPE: Literal["pgvector", "pinecone"] = Field("pgvector", json_schema_extra={"env": "VECTOR_DB_TYPE"})
    PINECONE_API_KEY: Optional[str] = Field(None, json_schema_extra={"env": "PINECONE_API_KEY"})
    PINECONE_ENVIRONMENT: Optional[str] = Field(None, json_schema_extra={"env": "PINECONE_ENVIRONMENT"})
    PINECONE_INDEX_NAME: str = Field("keemu-embeddings", json_schema_extra={"env": "PINECONE_INDEX_NAME"})

    # ================================
    # Email Configuration
    # ================================
    SENDGRID_API_KEY: Optional[str] = Field(None, json_schema_extra={"env": "SENDGRID_API_KEY"})
    SENDGRID_FROM_EMAIL: Optional[str] = Field(None, json_schema_extra={"env": "SENDGRID_FROM_EMAIL"})
    SENDGRID_FROM_NAME: str = Field("KeeMU", json_schema_extra={"env": "SENDGRID_FROM_NAME"})

    # ================================
    # JWT Configuration
    # ================================
    JWT_SECRET_KEY: str = Field(..., min_length=32, json_schema_extra={"env": "JWT_SECRET_KEY"})
    JWT_ALGORITHM: str = Field("HS256", json_schema_extra={"env": "JWT_ALGORITHM"})
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(10080, json_schema_extra={"env": "JWT_ACCESS_TOKEN_EXPIRE_MINUTES"})
    JWT_REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(43200, json_schema_extra={"env": "JWT_REFRESH_TOKEN_EXPIRE_MINUTES"})

    # ================================
    # Content Collection Configuration
    # ================================
    YOUTUBE_CHECK_INTERVAL_HOURS: int = Field(6, json_schema_extra={"env": "YOUTUBE_CHECK_INTERVAL_HOURS"})
    REDDIT_CHECK_INTERVAL_HOURS: int = Field(1, json_schema_extra={"env": "REDDIT_CHECK_INTERVAL_HOURS"})
    BLOG_CHECK_INTERVAL_HOURS: int = Field(12, json_schema_extra={"env": "BLOG_CHECK_INTERVAL_HOURS"})
    MAX_CONTENT_AGE_DAYS: int = Field(90, json_schema_extra={"env": "MAX_CONTENT_AGE_DAYS"})

    # ================================
    # Processing Configuration
    # ================================
    USE_LOCAL_WHISPER: bool = Field(False, json_schema_extra={"env": "USE_LOCAL_WHISPER"})
    CHUNK_SIZE_TOKENS: int = Field(800, json_schema_extra={"env": "CHUNK_SIZE_TOKENS"})
    CHUNK_OVERLAP_TOKENS: int = Field(100, json_schema_extra={"env": "CHUNK_OVERLAP_TOKENS"})
    MAX_CHUNKS_PER_CONTENT: int = Field(50, json_schema_extra={"env": "MAX_CHUNKS_PER_CONTENT"})

    # ================================
    # RAG Configuration
    # ================================
    RAG_TOP_K_RETRIEVAL: int = Field(15, json_schema_extra={"env": "RAG_TOP_K_RETRIEVAL"})
    RAG_TOP_K_RERANK: int = Field(5, json_schema_extra={"env": "RAG_TOP_K_RERANK"})
    RAG_MAX_CONTEXT_TOKENS: int = Field(3000, json_schema_extra={"env": "RAG_MAX_CONTEXT_TOKENS"})

    # ================================
    # Summary Configuration
    # ================================
    SUMMARY_SOURCE_MAX_WORDS: int = Field(300, json_schema_extra={"env": "SUMMARY_SOURCE_MAX_WORDS"})
    SUMMARY_OVERALL_MAX_WORDS: int = Field(800, json_schema_extra={"env": "SUMMARY_OVERALL_MAX_WORDS"})

    # ================================
    # Rate Limiting
    # ================================
    RATE_LIMIT_PER_MINUTE: int = Field(60, json_schema_extra={"env": "RATE_LIMIT_PER_MINUTE"})
    RATE_LIMIT_BURST: int = Field(10, json_schema_extra={"env": "RATE_LIMIT_BURST"})

    # ================================
    # Celery Configuration
    # ================================
    CELERY_BROKER_URL: str = Field("redis://redis:6379/0", json_schema_extra={"env": "CELERY_BROKER_URL"})
    CELERY_RESULT_BACKEND: str = Field("redis://redis:6379/0", json_schema_extra={"env": "CELERY_RESULT_BACKEND"})
    CELERY_TASK_SERIALIZER: str = Field("json", json_schema_extra={"env": "CELERY_TASK_SERIALIZER"})
    CELERY_RESULT_SERIALIZER: str = Field("json", json_schema_extra={"env": "CELERY_RESULT_SERIALIZER"})
    CELERY_ACCEPT_CONTENT: str = Field("json", json_schema_extra={"env": "CELERY_ACCEPT_CONTENT"})
    CELERY_TIMEZONE: str = Field("UTC", json_schema_extra={"env": "CELERY_TIMEZONE"})
    CELERY_ENABLE_UTC: bool = Field(True, json_schema_extra={"env": "CELERY_ENABLE_UTC"})
    
    @property
    def celery_accept_content_list(self) -> List[str]:
        """Parse CELERY_ACCEPT_CONTENT into a list."""
        return [item.strip() for item in self.CELERY_ACCEPT_CONTENT.split(",")]

    # ================================
    # Logging Configuration
    # ================================
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field("INFO", json_schema_extra={"env": "LOG_LEVEL"})
    LOG_FORMAT: Literal["json", "text"] = Field("json", json_schema_extra={"env": "LOG_FORMAT"})

    # ================================
    # Monitoring (optional)
    # ================================
    SENTRY_DSN: Optional[str] = Field(None, json_schema_extra={"env": "SENTRY_DSN"})

    # ================================
    # Feature Flags
    # ================================
    ENABLE_EMAIL_NOTIFICATIONS: bool = Field(True, json_schema_extra={"env": "ENABLE_EMAIL_NOTIFICATIONS"})
    ENABLE_COST_TRACKING: bool = Field(True, json_schema_extra={"env": "ENABLE_COST_TRACKING"})
    ENABLE_ANALYTICS: bool = Field(True, json_schema_extra={"env": "ENABLE_ANALYTICS"})

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
