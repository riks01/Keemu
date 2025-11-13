"""
Pydantic schemas for Reddit API endpoints.

These schemas define the request/response structures for Reddit-related operations.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ========================================
# Request Schemas
# ========================================


class RedditSubredditSearchRequest(BaseModel):
    """Request schema for searching/validating a subreddit."""
    
    query: str = Field(
        ...,
        description="Subreddit name, r/subreddit, or Reddit URL",
        min_length=1,
        max_length=500,
        examples=[
            "python",
            "r/python",
            "/r/learnpython",
            "https://reddit.com/r/python"
        ]
    )
    
    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        """Validate and clean the query string."""
        v = v.strip()
        if not v:
            raise ValueError("Query cannot be empty")
        return v


class RedditSubscriptionCreate(BaseModel):
    """Request schema for creating a new Reddit subscription."""
    
    subreddit_name: str = Field(
        ...,
        description="Subreddit name (without r/)",
        min_length=3,
        max_length=21,
        examples=["python", "learnprogramming"]
    )
    
    custom_display_name: Optional[str] = Field(
        None,
        description="Custom name for the subreddit (overrides official name)",
        max_length=100,
        examples=["Python Community - My Favorite"]
    )
    
    notification_enabled: bool = Field(
        True,
        description="Whether to receive notifications for new content"
    )
    
    comment_limit: int = Field(
        20,
        description="Maximum number of comments to fetch per post",
        ge=5,
        le=50
    )
    
    min_score: int = Field(
        10,
        description="Minimum post score threshold for fetching",
        ge=0,
        le=10000
    )
    
    min_comments: int = Field(
        3,
        description="Minimum number of comments required",
        ge=0,
        le=100
    )
    
    @field_validator('subreddit_name')
    @classmethod
    def validate_subreddit_name(cls, v: str) -> str:
        """Validate subreddit name format."""
        import re
        v = v.strip().lower()
        if not re.match(r'^[a-z0-9_]{3,21}$', v):
            raise ValueError(
                "Subreddit name must be 3-21 characters, alphanumeric and underscores only"
            )
        return v


class RedditSubscriptionUpdate(BaseModel):
    """Request schema for updating a subscription."""
    
    is_active: Optional[bool] = Field(
        None,
        description="Pause/resume subscription"
    )
    
    custom_display_name: Optional[str] = Field(
        None,
        description="Update custom display name",
        max_length=100
    )
    
    notification_enabled: Optional[bool] = Field(
        None,
        description="Toggle notifications"
    )
    
    comment_limit: Optional[int] = Field(
        None,
        description="Update comment limit per post",
        ge=5,
        le=50
    )
    
    min_score: Optional[int] = Field(
        None,
        description="Update minimum post score threshold",
        ge=0,
        le=10000
    )
    
    min_comments: Optional[int] = Field(
        None,
        description="Update minimum comments threshold",
        ge=0,
        le=100
    )


# ========================================
# Response Schemas
# ========================================


class RedditSubredditInfo(BaseModel):
    """Reddit subreddit information (search result or subscription details)."""
    
    name: str = Field(
        ...,
        description="Subreddit name (display name)"
    )
    
    title: str = Field(
        ...,
        description="Official subreddit title"
    )
    
    description: Optional[str] = Field(
        None,
        description="Subreddit public description"
    )
    
    icon_url: Optional[str] = Field(
        None,
        description="Subreddit icon/avatar URL"
    )
    
    banner_url: Optional[str] = Field(
        None,
        description="Subreddit banner URL"
    )
    
    subscribers: int = Field(
        ...,
        description="Number of subscribers"
    )
    
    over18: bool = Field(
        ...,
        description="NSFW/18+ content flag"
    )
    
    public: bool = Field(
        ...,
        description="Whether subreddit is public"
    )
    
    url: str = Field(
        ...,
        description="Reddit URL to subreddit"
    )
    
    created_at: Optional[str] = Field(
        None,
        description="Subreddit creation date (ISO format)"
    )


class RedditSubscriptionResponse(BaseModel):
    """Response schema for a single Reddit subscription."""
    
    id: int = Field(
        ...,
        description="Subscription ID (database primary key)"
    )
    
    user_id: int = Field(
        ...,
        description="User who owns this subscription"
    )
    
    subreddit: RedditSubredditInfo = Field(
        ...,
        description="Subreddit information"
    )
    
    is_active: bool = Field(
        ...,
        description="Whether subscription is active (or paused)"
    )
    
    custom_display_name: Optional[str] = Field(
        None,
        description="User's custom name for the subreddit"
    )
    
    notification_enabled: bool = Field(
        ...,
        description="Whether notifications are enabled"
    )
    
    comment_limit: int = Field(
        ...,
        description="Maximum comments fetched per post"
    )
    
    min_score: int = Field(
        ...,
        description="Minimum post score threshold"
    )
    
    min_comments: int = Field(
        ...,
        description="Minimum comments threshold"
    )
    
    last_shown_at: Optional[datetime] = Field(
        None,
        description="Last time content from this subreddit was shown to user"
    )
    
    created_at: datetime = Field(
        ...,
        description="When subscription was created"
    )
    
    updated_at: datetime = Field(
        ...,
        description="When subscription was last modified"
    )
    
    class Config:
        from_attributes = True


class RedditSubscriptionList(BaseModel):
    """Response schema for listing Reddit subscriptions."""
    
    subscriptions: List[RedditSubscriptionResponse] = Field(
        ...,
        description="List of subscriptions"
    )
    
    total: int = Field(
        ...,
        description="Total number of subscriptions"
    )
    
    active_count: int = Field(
        ...,
        description="Number of active subscriptions"
    )
    
    paused_count: int = Field(
        ...,
        description="Number of paused subscriptions"
    )


class RedditSubredditSearchResponse(BaseModel):
    """Response schema for subreddit search."""
    
    found: bool = Field(
        ...,
        description="Whether a subreddit was found"
    )
    
    subreddit: Optional[RedditSubredditInfo] = Field(
        None,
        description="Subreddit information if found"
    )
    
    already_subscribed: bool = Field(
        False,
        description="Whether user is already subscribed to this subreddit"
    )
    
    subscription_id: Optional[int] = Field(
        None,
        description="Subscription ID if already subscribed"
    )


class RedditRefreshResponse(BaseModel):
    """Response schema for manual refresh trigger."""
    
    success: bool = Field(
        ...,
        description="Whether refresh was triggered successfully"
    )
    
    message: str = Field(
        ...,
        description="Status message"
    )
    
    task_id: Optional[str] = Field(
        None,
        description="Celery task ID for tracking"
    )
    
    estimated_posts: Optional[int] = Field(
        None,
        description="Estimated number of posts to fetch"
    )


class RedditSubscriptionStats(BaseModel):
    """Statistics about user's Reddit subscriptions."""
    
    total_subscriptions: int = Field(
        ...,
        description="Total number of subscriptions"
    )
    
    active_subscriptions: int = Field(
        ...,
        description="Number of active subscriptions"
    )
    
    paused_subscriptions: int = Field(
        ...,
        description="Number of paused subscriptions"
    )
    
    total_subreddits_in_system: int = Field(
        ...,
        description="Total unique subreddits tracked across all users"
    )
    
    total_posts_fetched: int = Field(
        ...,
        description="Total Reddit posts fetched for this user"
    )
    
    posts_in_last_7_days: int = Field(
        ...,
        description="Posts fetched in the last 7 days"
    )
    
    average_engagement_score: Optional[float] = Field(
        None,
        description="Average engagement score of fetched posts"
    )
    
    last_refresh: Optional[datetime] = Field(
        None,
        description="Last time content was refreshed"
    )


class MessageResponse(BaseModel):
    """Generic message response."""
    
    message: str = Field(
        ...,
        description="Response message"
    )
    
    success: bool = Field(
        True,
        description="Whether operation succeeded"
    )


# ========================================
# Error Response Schemas
# ========================================


class ErrorDetail(BaseModel):
    """Detailed error information."""
    
    field: Optional[str] = Field(
        None,
        description="Field that caused the error (if applicable)"
    )
    
    message: str = Field(
        ...,
        description="Error message"
    )
    
    code: Optional[str] = Field(
        None,
        description="Error code for programmatic handling"
    )


class ErrorResponse(BaseModel):
    """Error response schema."""
    
    error: str = Field(
        ...,
        description="Error type or category"
    )
    
    message: str = Field(
        ...,
        description="Human-readable error message"
    )
    
    details: Optional[List[ErrorDetail]] = Field(
        None,
        description="Additional error details"
    )
    
    status_code: int = Field(
        ...,
        description="HTTP status code"
    )





