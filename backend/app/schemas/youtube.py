"""
Pydantic schemas for YouTube API endpoints.

These schemas define the request/response structures for YouTube-related operations.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ========================================
# Request Schemas
# ========================================

class YouTubeChannelSearchRequest(BaseModel):
    """Request schema for searching/validating a YouTube channel."""
    
    query: str = Field(
        ...,
        description="YouTube channel URL, channel ID, username, or handle",
        min_length=1,
        max_length=500,
        examples=[
            "https://youtube.com/@Fireship",
            "https://youtube.com/channel/UCsBjURrPoezykLs9EqgamOA",
            "UCsBjURrPoezykLs9EqgamOA",
            "@Fireship"
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


class YouTubeSubscriptionCreate(BaseModel):
    """Request schema for creating a new YouTube subscription."""
    
    channel_id: str = Field(
        ...,
        description="YouTube channel ID (starts with UC, typically 24 chars)",
        min_length=20,
        max_length=30,
        examples=["UCsBjURrPoezykLs9EqgamOA"]
    )
    
    custom_display_name: Optional[str] = Field(
        None,
        description="Custom name for the channel (overrides official name)",
        max_length=100,
        examples=["Fireship - My Favorite"]
    )
    
    notification_enabled: bool = Field(
        True,
        description="Whether to receive notifications for new content"
    )
    
    @field_validator('channel_id')
    @classmethod
    def validate_channel_id(cls, v: str) -> str:
        """Validate YouTube channel ID format."""
        if not v.startswith('UC'):
            raise ValueError("YouTube channel IDs must start with 'UC'")
        if len(v) < 20 or len(v) > 30:
            raise ValueError("Invalid channel ID length")
        return v


class YouTubeSubscriptionUpdate(BaseModel):
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


# ========================================
# Response Schemas
# ========================================

class YouTubeChannelInfo(BaseModel):
    """YouTube channel information (search result or subscription details)."""
    
    channel_id: str = Field(
        ...,
        description="YouTube channel ID"
    )
    
    name: str = Field(
        ...,
        description="Official channel name"
    )
    
    description: Optional[str] = Field(
        None,
        description="Channel description"
    )
    
    thumbnail_url: Optional[str] = Field(
        None,
        description="Channel thumbnail/avatar URL"
    )
    
    subscriber_count: int = Field(
        ...,
        description="Number of subscribers (from YouTube)"
    )
    
    video_count: int = Field(
        ...,
        description="Total number of videos on the channel"
    )
    
    view_count: int = Field(
        ...,
        description="Total channel views"
    )
    
    custom_url: Optional[str] = Field(
        None,
        description="Channel's custom URL/handle",
        examples=["@fireship"]
    )
    
    published_at: Optional[str] = Field(
        None,
        description="Channel creation date (ISO format)"
    )


class YouTubeSubscriptionResponse(BaseModel):
    """Response schema for a single subscription."""
    
    id: int = Field(
        ...,
        description="Subscription ID (database primary key)"
    )
    
    user_id: int = Field(
        ...,
        description="User who owns this subscription"
    )
    
    channel: YouTubeChannelInfo = Field(
        ...,
        description="Channel information"
    )
    
    is_active: bool = Field(
        ...,
        description="Whether subscription is active (or paused)"
    )
    
    custom_display_name: Optional[str] = Field(
        None,
        description="User's custom name for the channel"
    )
    
    notification_enabled: bool = Field(
        ...,
        description="Whether notifications are enabled"
    )
    
    last_shown_at: Optional[datetime] = Field(
        None,
        description="Last time content from this channel was shown to user"
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


class YouTubeSubscriptionList(BaseModel):
    """Response schema for listing subscriptions."""
    
    subscriptions: List[YouTubeSubscriptionResponse] = Field(
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


class YouTubeChannelSearchResponse(BaseModel):
    """Response schema for channel search."""
    
    found: bool = Field(
        ...,
        description="Whether a channel was found"
    )
    
    channel: Optional[YouTubeChannelInfo] = Field(
        None,
        description="Channel information if found"
    )
    
    already_subscribed: bool = Field(
        False,
        description="Whether user is already subscribed to this channel"
    )
    
    subscription_id: Optional[int] = Field(
        None,
        description="Subscription ID if already subscribed"
    )


class YouTubeRefreshResponse(BaseModel):
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
    
    estimated_videos: Optional[int] = Field(
        None,
        description="Estimated number of videos to fetch"
    )


class YouTubeSubscriptionStats(BaseModel):
    """Statistics about user's YouTube subscriptions."""
    
    total_subscriptions: int
    active_subscriptions: int
    paused_subscriptions: int
    total_channels_in_system: int
    total_videos_fetched: int
    videos_in_last_7_days: int
    last_refresh: Optional[datetime]


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

