"""
Pydantic schemas for Blog/RSS API endpoints.

These schemas define the request/response structures for blog-related operations.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, HttpUrl, field_validator, ConfigDict


# ========================================
# Request Schemas
# ========================================


class BlogDiscoverRequest(BaseModel):
    """Request schema for discovering RSS feed from a blog URL."""
    
    blog_url: str = Field(
        ...,
        description="Blog homepage URL to discover RSS feed from",
        min_length=1,
        max_length=2000,
        examples=[
            "https://example.com/blog",
            "https://blog.example.com",
            "example.com/blog"
        ]
    )
    
    @field_validator('blog_url')
    @classmethod
    def validate_blog_url(cls, v: str) -> str:
        """Validate and clean the blog URL."""
        v = v.strip()
        if not v:
            raise ValueError("Blog URL cannot be empty")
        return v


class BlogSubscribeRequest(BaseModel):
    """Request schema for subscribing to a blog/RSS feed."""
    
    blog_url: Optional[str] = Field(
        None,
        description="Blog homepage URL (will auto-discover feed)",
        max_length=2000,
        examples=["https://example.com/blog"]
    )
    
    feed_url: Optional[str] = Field(
        None,
        description="Direct RSS/Atom feed URL",
        max_length=2000,
        examples=["https://example.com/feed", "https://example.com/rss"]
    )
    
    custom_display_name: Optional[str] = Field(
        None,
        description="Custom name for the blog (overrides auto-detected name)",
        max_length=200,
        examples=["Tech Blog - My Favorite"]
    )
    
    notification_enabled: bool = Field(
        True,
        description="Whether to receive notifications for new articles"
    )
    
    @field_validator('blog_url', 'feed_url')
    @classmethod
    def validate_urls(cls, v: Optional[str]) -> Optional[str]:
        """Validate and clean URLs."""
        if v:
            v = v.strip()
            if not v:
                return None
        return v
    
    def model_post_init(self, __context: Any) -> None:
        """Validate that at least one URL is provided."""
        if not self.blog_url and not self.feed_url:
            raise ValueError("Either blog_url or feed_url must be provided")


class BlogSubscriptionUpdate(BaseModel):
    """Request schema for updating a blog subscription."""
    
    is_active: Optional[bool] = Field(
        None,
        description="Pause/resume subscription"
    )
    
    custom_display_name: Optional[str] = Field(
        None,
        description="Update custom display name",
        max_length=200
    )
    
    notification_enabled: Optional[bool] = Field(
        None,
        description="Toggle notifications"
    )


# ========================================
# Response Schemas
# ========================================


class BlogDiscoverResponse(BaseModel):
    """Response schema for RSS feed discovery."""
    
    model_config = ConfigDict(from_attributes=True)

    success: bool = Field(
        ...,
        description="Whether feed discovery was successful"
    )
    
    feed_url: Optional[str] = Field(
        None,
        description="Discovered RSS/Atom feed URL"
    )
    
    blog_url: str = Field(
        ...,
        description="Original blog URL queried"
    )
    
    blog_title: Optional[str] = Field(
        None,
        description="Detected blog title"
    )
    
    feed_type: Optional[str] = Field(
        None,
        description="Type of feed (RSS 2.0, Atom, etc.)"
    )
    
    message: Optional[str] = Field(
        None,
        description="Human-readable message about discovery result"
    )


class BlogMetadata(BaseModel):
    """Blog metadata information."""
    
    blog_name: str = Field(..., description="Blog name")
    blog_url: Optional[str] = Field(None, description="Blog homepage URL")
    feed_url: str = Field(..., description="RSS feed URL")
    description: Optional[str] = Field(None, description="Blog description")
    language: Optional[str] = Field(None, description="Blog language code")
    last_updated: Optional[datetime] = Field(None, description="Last feed update time")


class BlogSubscriptionResponse(BaseModel):
    """Response schema for a single blog subscription."""
    
    id: int = Field(..., description="Subscription ID")
    user_id: int = Field(..., description="User ID")
    channel_id: int = Field(..., description="Channel ID")
    
    blog_name: str = Field(..., description="Blog name")
    feed_url: str = Field(..., description="RSS feed URL")
    blog_url: Optional[str] = Field(None, description="Blog homepage URL")
    
    custom_display_name: Optional[str] = Field(
        None,
        description="User's custom name for the blog"
    )
    
    is_active: bool = Field(..., description="Whether subscription is active")
    notification_enabled: bool = Field(..., description="Notifications enabled")
    
    article_count: int = Field(
        0,
        description="Number of articles fetched from this blog"
    )
    
    last_fetched_at: Optional[datetime] = Field(
        None,
        description="When articles were last fetched"
    )
    
    created_at: datetime = Field(..., description="Subscription creation time")
    updated_at: datetime = Field(..., description="Last update time")
    
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional blog metadata"
    )
    


class BlogListResponse(BaseModel):
    """Response schema for list of blog subscriptions."""
    
    subscriptions: List[BlogSubscriptionResponse] = Field(
        ...,
        description="List of blog subscriptions"
    )
    
    total: int = Field(..., description="Total number of subscriptions")
    page: int = Field(1, description="Current page number")
    page_size: int = Field(20, description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")
    
    active_count: int = Field(0, description="Number of active subscriptions")
    paused_count: int = Field(0, description="Number of paused subscriptions")


class BlogArticleSummary(BaseModel):
    """Summary information for a blog article."""
    
    id: int = Field(..., description="Article content item ID")
    title: str = Field(..., description="Article title")
    url: str = Field(..., description="Article URL")
    author: Optional[str] = Field(None, description="Article author")
    published_at: Optional[datetime] = Field(None, description="Publication date")
    word_count: Optional[int] = Field(None, description="Article word count")
    read_time_minutes: Optional[int] = Field(None, description="Estimated read time")
    excerpt: Optional[str] = Field(None, description="Article excerpt/summary")


class BlogDetailsResponse(BaseModel):
    """Detailed response for a single blog subscription."""
    
    subscription: BlogSubscriptionResponse = Field(
        ...,
        description="Subscription details"
    )
    
    recent_articles: List[BlogArticleSummary] = Field(
        [],
        description="Recent articles from this blog"
    )
    
    statistics: Dict[str, Any] = Field(
        {},
        description="Blog-specific statistics"
    )


class BlogStatsResponse(BaseModel):
    """Response schema for blog statistics."""
    
    total_subscriptions: int = Field(
        ...,
        description="Total number of blog subscriptions"
    )
    
    active_subscriptions: int = Field(
        ...,
        description="Number of active subscriptions"
    )
    
    paused_subscriptions: int = Field(
        ...,
        description="Number of paused subscriptions"
    )
    
    total_articles: int = Field(
        ...,
        description="Total articles collected from all blogs"
    )
    
    articles_today: int = Field(
        ...,
        description="Articles fetched today"
    )
    
    articles_this_week: int = Field(
        ...,
        description="Articles fetched this week"
    )
    
    articles_this_month: int = Field(
        ...,
        description="Articles fetched this month"
    )
    
    by_blog: List[Dict[str, Any]] = Field(
        [],
        description="Statistics per blog"
    )
    
    fetch_success_rate: float = Field(
        ...,
        description="Percentage of successful fetches (0-100)"
    )
    
    average_articles_per_blog: float = Field(
        ...,
        description="Average number of articles per blog"
    )
    
    most_active_blog: Optional[Dict[str, Any]] = Field(
        None,
        description="Blog with most articles"
    )
    
    recent_fetch_errors: List[Dict[str, Any]] = Field(
        [],
        description="Recent fetch errors (for debugging)"
    )


class BlogRefreshResponse(BaseModel):
    """Response schema for manual blog refresh."""
    
    success: bool = Field(..., description="Whether refresh was triggered")
    message: str = Field(..., description="Status message")
    task_id: Optional[str] = Field(None, description="Celery task ID if async")
    estimated_time: Optional[int] = Field(
        None,
        description="Estimated time to completion in seconds"
    )


class ErrorResponse(BaseModel):
    """Standard error response."""
    
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")

