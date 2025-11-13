"""
Content Models

This module contains content-related models for the KeeMU application.

Models Included:
----------------
1. Channel - Shared content sources (YouTube channels, Reddit subreddits, Blogs)
2. UserSubscription - User's subscription to a channel (association object)
3. ContentItem - Actual content fetched from channels (videos, posts, articles)
4. ContentSourceType (Enum) - Type of content source
5. ProcessingStatus (Enum) - Content processing status

Database Tables:
----------------
- channels: Stores shared content sources
- user_subscriptions: Junction table for user-channel many-to-many relationship
- content_items: Stores actual content from channels

Relationships:
--------------
- User (Many) ←→ (Many) Channel via UserSubscription
- Channel (1) ←→ (Many) ContentItem

Learning Resources:
-------------------
- Many-to-Many: https://docs.sqlalchemy.org/en/20/orm/basic_relationships.html#many-to-many
- Association Object: https://docs.sqlalchemy.org/en/20/orm/basic_relationships.html#association-object
- JSONB in PostgreSQL: https://www.postgresql.org/docs/current/datatype-json.html
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import BaseModel, String100, String255, String500

if TYPE_CHECKING:
    from app.models.user import User


# ================================
# Enums
# ================================

class ContentSourceType(str, enum.Enum):
    """
    Enum for content source types.
    
    What Content Sources Do We Support?
    ------------------------------------
    KeeMU aggregates content from multiple platforms to create
    personalized digests for users.
    
    Supported Platforms:
    --------------------
    1. YOUTUBE: YouTube channels
    2. REDDIT: Reddit communities (subreddits)
    3. BLOG: Blogs and RSS feeds
    
    Why These Platforms?
    --------------------
    - YouTube: Most popular video platform for tech content
    - Reddit: Rich community discussions and news
    - Blogs: In-depth technical articles and tutorials
    """
    
    YOUTUBE = "youtube"
    REDDIT = "reddit"
    BLOG = "blog"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class ProcessingStatus(str, enum.Enum):
    """
    Enum for content processing status.
    
    Content Processing Pipeline:
    -----------------------------
    When content is fetched from a channel, it goes through several stages:
    
    1. PENDING → Just collected, waiting to be processed
    2. PROCESSING → Currently being processed (chunking, embedding)
    3. PROCESSED → Successfully processed and ready for RAG
    4. FAILED → Processing failed (will retry)
    
    Status Flow:
    ------------
    PENDING → PROCESSING → PROCESSED (success path)
                    ↓
                 FAILED (error path, will retry)
    
    Use Cases:
    ----------
    - Track which content needs processing
    - Monitor processing pipeline health
    - Retry failed content
    - Show users which content is available
    
    Example Queries:
    ----------------
    # Get pending content for processing
    pending = select(ContentItem).where(
        ContentItem.processing_status == ProcessingStatus.PENDING
    )
    
    # Get failed content for retry
    failed = select(ContentItem).where(
        ContentItem.processing_status == ProcessingStatus.FAILED
    )
    
    # Get processed content ready for RAG
    processed = select(ContentItem).where(
        ContentItem.processing_status == ProcessingStatus.PROCESSED
    )
    """
    
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


# ================================
# Channel Model (Shared Resource)
# ================================

class Channel(BaseModel):
    """
    Channel model - represents a shared content source.
    
    This model represents the actual content source (YouTube channel,
    Reddit subreddit, Blog feed) that is SHARED across multiple users.
    
    Table: channels
    ---------------
    One channel can have many subscribers (users).
    
    Key Difference from Old Design:
    --------------------------------
    OLD: Each user had their own ContentSource record for same channel
    NEW: One Channel record shared by all users who subscribe to it
    
    Benefits:
    ---------
    1. Fetch content once, serve to all subscribers
    2. Store metadata (description, thumbnail) in one place
    3. Easy analytics: "How many users follow this channel?"
    4. No duplicate data
    
    Example:
    --------
    Fireship YouTube channel:
    - 1 Channel record
    - 100 UserSubscription records (100 users subscribed)
    - Content fetched once, available to all 100 users
    
    Metadata Storage:
    -----------------
    We store channel-specific metadata:
    - name: "Fireship"
    - description: "High-intensity code tutorials"
    - thumbnail_url: "https://..."
    - subscriber_count: How many users follow this channel
    - last_fetched_at: When we last fetched content
    
    Platform-Specific Identifiers:
    -------------------------------
    YouTube: channel_id (e.g., "UCsBjURrPoezykLs9EqgamOA")
    Reddit: subreddit name (e.g., "programming")
    Blog: feed URL (e.g., "https://blog.example.com/feed.xml")
    """
    
    __tablename__ = "channels"
    
    # ================================
    # Channel Information
    # ================================
    
    source_type: Mapped[ContentSourceType] = mapped_column(
        nullable=False,
        index=True,
        comment="Type of content source (youtube, reddit, blog)"
    )
    # Platform type
    # Index for fast queries: "Show all YouTube channels"
    
    source_identifier: Mapped[str] = mapped_column(
        String255,
        nullable=False,
        comment="Platform-specific identifier (channel_id, subreddit, feed_url)"
    )
    # YouTube: "UCsBjURrPoezykLs9EqgamOA"
    # Reddit: "programming"
    # Blog: "https://blog.example.com/feed.xml"
    
    name: Mapped[str] = mapped_column(
        String100,
        nullable=False,
        comment="Channel/source name"
    )
    # Official name: "Fireship", "r/programming", "TechCrunch"
    
    description: Mapped[str | None] = mapped_column(
        String500,
        nullable=True,
        comment="Channel description"
    )
    # Optional: Store channel description for display
    
    thumbnail_url: Mapped[str | None] = mapped_column(
        String255,
        nullable=True,
        comment="Channel thumbnail/logo URL"
    )
    # Optional: Store thumbnail for UI display
    
    # ================================
    # Metadata & Analytics
    # ================================
    
    subscriber_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="Number of users subscribed to this channel"
    )
    # How many users follow this channel?
    # Updated automatically via relationship
    # Useful for analytics and recommendations
    
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this channel is active (not deleted/banned)"
    )
    # If a channel is deleted/banned on the platform, mark inactive
    # Don't fetch content from inactive channels
    
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Last time content was fetched from this channel (UTC)"
    )
    # When did we last fetch content from this channel?
    # For rate limiting and monitoring
    
    # ================================
    # Relationships
    # ================================
    
    subscriptions: Mapped[list["UserSubscription"]] = relationship(
        "UserSubscription",
        back_populates="channel",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    # One-to-many with UserSubscription
    # - One channel can have many subscriptions
    # - Delete channel → delete all subscriptions
    
    content_items: Mapped[list["ContentItem"]] = relationship(
        "ContentItem",
        back_populates="channel",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    # One-to-many with ContentItem
    # - One channel has many content items (videos, posts, articles)
    # - Delete channel → delete all its content
    # - Ordered by published date (newest first)
    
    # ================================
    # Constraints
    # ================================
    
    __table_args__ = (
        UniqueConstraint(
            'source_type',
            'source_identifier',
            name='uq_channel_source'
        ),
        # Prevent duplicate channels
        # Can't have two records for the same YouTube channel
    )
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"Channel(id={self.id}, type={self.source_type.value}, "
            f"name='{self.name}', subscribers={self.subscriber_count})"
        )


# ================================
# UserSubscription Model (Association Object)
# ================================

class UserSubscription(BaseModel):
    """
    User subscription to a channel (association object).
    
    This is the junction table that creates the many-to-many relationship
    between Users and Channels.
    
    Table: user_subscriptions
    -------------------------
    Each record represents one user's subscription to one channel.
    
    What is an Association Object?
    -------------------------------
    A regular many-to-many uses a simple junction table with just FKs.
    An association object adds extra data to the relationship:
    - is_active: User can pause/resume subscription
    - custom_display_name: User can rename channel
    - last_fetched_at: Track when content was last shown to this user
    - notification_enabled: User-specific notification settings
    
    Example:
    --------
    Alice subscribes to Fireship:
    - user_id: 1 (Alice)
    - channel_id: 10 (Fireship)
    - is_active: True
    - custom_display_name: "My Favorite Channel"
    - notification_enabled: True
    
    Bob subscribes to the same Fireship:
    - user_id: 2 (Bob)
    - channel_id: 10 (Same Fireship!)
    - is_active: False (paused)
    - custom_display_name: "Fireship" (default)
    - notification_enabled: False
    
    Benefits:
    ---------
    1. Users can customize their subscriptions independently
    2. User can pause without affecting others
    3. User can rename channels for personal organization
    4. Track per-user engagement metrics
    
    Relationships:
    --------------
    - user (many-to-one): Which user owns this subscription
    - channel (many-to-one): Which channel this subscription is for
    """
    
    __tablename__ = "user_subscriptions"
    
    # ================================
    # Foreign Keys
    # ================================
    
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to users table"
    )
    # Links to User
    # CASCADE: Delete user → delete their subscriptions
    # Index: Fast queries for "all subscriptions for this user"
    
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to channels table"
    )
    # Links to Channel
    # CASCADE: Delete channel → delete all subscriptions to it
    # Index: Fast queries for "all subscribers to this channel"
    
    # ================================
    # User-Specific Settings
    # ================================
    
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this subscription is active"
    )
    # User can pause subscriptions
    # Paused subscriptions don't appear in digests
    
    custom_display_name: Mapped[str | None] = mapped_column(
        String100,
        nullable=True,
        comment="User's custom name for this channel (optional)"
    )
    # User can rename channels for personal organization
    # If NULL, use channel.name as default
    
    notification_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether to notify user about new content from this channel"
    )
    # User can disable notifications for specific channels
    # Useful for "subscribed but not interested in every update"
    
    last_shown_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Last time content from this channel was shown to this user (UTC)"
    )
    # Track when user last saw content from this channel
    # Useful for:
    # - Showing "new" badges
    # - Prioritizing channels user hasn't seen recently
    # - Engagement analytics
    
    # ================================
    # Relationships
    # ================================
    
    user: Mapped["User"] = relationship(
        "User",
        back_populates="subscriptions",
        lazy="joined"
    )
    # Many-to-one with User
    # subscription.user gives you the User object
    
    channel: Mapped["Channel"] = relationship(
        "Channel",
        back_populates="subscriptions",
        lazy="joined"
    )
    # Many-to-one with Channel
    # subscription.channel gives you the Channel object
    
    # ================================
    # Constraints
    # ================================
    
    __table_args__ = (
        UniqueConstraint(
            'user_id',
            'channel_id',
            name='uq_user_channel'
        ),
        # A user can only subscribe to a channel once
        # Prevents duplicate subscriptions
    )
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"UserSubscription(id={self.id}, user_id={self.user_id}, "
            f"channel_id={self.channel_id}, active={self.is_active})"
        )
    
    @property
    def display_name(self) -> str:
        """
        Get the display name for this subscription.
        
        Returns custom name if set, otherwise channel name.
        """
        return self.custom_display_name or self.channel.name


# ================================
# ContentItem Model
# ================================

class ContentItem(BaseModel):
    """
    Content item model - represents actual content from a channel.
    
    This model stores the actual content fetched from channels:
    - YouTube: Videos (with transcripts)
    - Reddit: Posts (with comments)
    - Blog: Articles
    
    Table: content_items
    --------------------
    Each content item belongs to one channel.
    
    Content Processing Pipeline:
    ----------------------------
    1. COLLECTION: Celery task fetches content from channel
    2. STORAGE: Store raw content in this table (status: PENDING)
    3. PROCESSING: Extract/chunk/embed content (status: PROCESSING)
    4. READY: Content ready for RAG (status: PROCESSED)
    
    What We Store:
    --------------
    - Title: Video title, post title, article headline
    - Content Body: Full transcript, post text, article content
    - Author: Channel name, Reddit user, blog author
    - Published At: When content was originally published
    - Metadata: Platform-specific data (views, scores, duration, etc.)
    - Processing Status: Track pipeline progress
    
    Platform-Specific Data in Metadata (JSONB):
    -------------------------------------------
    
    YouTube Video:
    {
        "video_id": "dQw4w9WgXcQ",
        "duration": 213,  # seconds
        "view_count": 1000000,
        "like_count": 50000,
        "comment_count": 5000,
        "thumbnail_url": "https://...",
        "transcript_language": "en"
    }
    
    Reddit Post:
    {
        "post_id": "abc123",
        "subreddit": "programming",
        "score": 500,
        "num_comments": 50,
        "upvote_ratio": 0.95,
        "url": "https://reddit.com/r/programming/...",
        "top_comments": [
            {"author": "user1", "body": "Great post!", "score": 100},
            ...
        ]
    }
    
    Blog Article:
    {
        "url": "https://blog.example.com/article",
        "word_count": 1500,
        "tags": ["python", "tutorial"],
        "featured_image": "https://...",
        "excerpt": "A brief summary..."
    }
    
    Content Uniqueness:
    -------------------
    We use external_id to prevent duplicate content:
    - YouTube: video_id
    - Reddit: post_id
    - Blog: article URL
    
    Combined with channel_id, this ensures no duplicates.
    
    Example:
    --------
    # YouTube video
    video = ContentItem(
        channel_id=channel.id,
        external_id="dQw4w9WgXcQ",
        title="Never Gonna Give You Up",
        content_body="[Transcript here...]",
        author="Rick Astley",
        published_at=datetime(1987, 7, 27),
        content_metadata={"video_id": "dQw4w9WgXcQ", "duration": 213, ...},
        processing_status=ProcessingStatus.PENDING
    )
    """
    
    __tablename__ = "content_items"
    
    # ================================
    # Foreign Key (Links to Channel)
    # ================================
    
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to channels table"
    )
    # Links to Channel
    # CASCADE: Delete channel → delete all its content
    # Index: Fast queries for "all content from this channel"
    
    # ================================
    # Content Identification
    # ================================
    
    external_id: Mapped[str] = mapped_column(
        String255,
        nullable=False,
        comment="Platform-specific content ID (video_id, post_id, article_url)"
    )
    # Platform-specific unique identifier
    # YouTube: video_id ("dQw4w9WgXcQ")
    # Reddit: post_id ("abc123")
    # Blog: article URL or slug
    #
    # Combined with channel_id, prevents duplicate content
    
    # ================================
    # Content Data
    # ================================
    
    title: Mapped[str] = mapped_column(
        String500,
        nullable=False,
        comment="Content title"
    )
    # Video title, post title, article headline
    # Max 500 chars for long titles
    
    content_body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Full content text (transcript, post, article)"
    )
    # Full content as text
    # YouTube: Full transcript
    # Reddit: Post selftext + top comments
    # Blog: Full article content
    #
    # TEXT type: No length limit (unlike VARCHAR)
    # Can store very long transcripts or articles
    
    author: Mapped[str] = mapped_column(
        String100,
        nullable=False,
        comment="Content author/creator name"
    )
    # YouTube: Channel name
    # Reddit: Username (u/username)
    # Blog: Author name
    
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="When content was originally published (UTC)"
    )
    # Original publication date
    # Index: Fast queries for "recent content"
    # Timezone-aware for correct ordering
    
    # ================================
    # Processing & Metadata
    # ================================
    
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        nullable=False,
        default=ProcessingStatus.PENDING,
        index=True,
        comment="Processing pipeline status"
    )
    # Track where content is in the pipeline
    # Index: Fast queries for "pending content to process"
    #
    # PENDING → Just collected
    # PROCESSING → Currently being chunked/embedded
    # PROCESSED → Ready for RAG
    # FAILED → Processing error (will retry)
    
    content_metadata: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Platform-specific metadata (JSON)"
    )
    # Flexible storage for platform-specific data
    # JSONB: Binary JSON, queryable in PostgreSQL
    #
    # YouTube: views, likes, duration, thumbnail
    # Reddit: score, comments, upvote_ratio
    # Blog: tags, word_count, featured_image
    #
    # Note: Named 'content_metadata' because 'metadata' is reserved by SQLAlchemy
    #
    # JSONB allows querying like:
    # WHERE content_metadata->>'view_count' > '1000000'
    
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if processing failed"
    )
    # Store error details if processing fails
    # Helps with debugging and retry logic
    # NULL if no error
    
    # ================================
    # Relationships
    # ================================
    
    channel: Mapped["Channel"] = relationship(
        "Channel",
        back_populates="content_items",
        lazy="joined"
    )
    # Many-to-one with Channel
    # content_item.channel gives you the Channel object
    #
    # lazy="joined": Load channel with content item
    # Useful when displaying content (need channel name)
    
    chunks: Mapped[list["ContentChunk"]] = relationship(
        "ContentChunk",
        back_populates="content_item",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ContentChunk.chunk_index"
    )
    # One-to-many with ContentChunk
    # - One content item has many chunks
    # - Delete content → delete all chunks
    # - Ordered by chunk_index for sequential access
    
    # ================================
    # Constraints
    # ================================
    
    __table_args__ = (
        UniqueConstraint(
            'channel_id',
            'external_id',
            name='uq_channel_content'
        ),
        # Prevent duplicate content
        # Can't fetch the same video/post twice for same channel
    )
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"ContentItem(id={self.id}, channel_id={self.channel_id}, "
            f"title='{self.title[:30]}...', status={self.processing_status.value})"
        )
    
    @property
    def is_processed(self) -> bool:
        """Check if content is fully processed and ready for RAG."""
        return self.processing_status == ProcessingStatus.PROCESSED
    
    @property
    def needs_processing(self) -> bool:
        """Check if content needs to be processed."""
        return self.processing_status == ProcessingStatus.PENDING
    
    @property
    def has_failed(self) -> bool:
        """Check if content processing failed."""
        return self.processing_status == ProcessingStatus.FAILED


# ================================
# ContentChunk Model
# ================================

class ContentChunk(BaseModel):
    """
    Content chunk model - represents text chunks with embeddings for RAG.
    
    This model stores smaller chunks of content for efficient retrieval-augmented
    generation (RAG). Large content items (long videos, articles) are split into
    manageable chunks that can be embedded and searched semantically.
    
    Table: content_chunks
    ---------------------
    Each chunk belongs to one content item.
    
    Why Chunking?
    -------------
    RAG systems work better with smaller, focused text segments because:
    - Embedding models have token limits (typically 512-8192 tokens)
    - Smaller chunks = more precise retrieval
    - Better relevance scoring
    - Reduced context size for LLM generation
    
    Chunking Strategy (Content-Type Specific):
    -------------------------------------------
    
    YouTube Videos:
    - Chunk by time windows (2-3 minute segments)
    - Use transcript timestamps for boundaries
    - Preserve speaker context
    - Example: 15-min video → 5-7 chunks
    
    Reddit Posts:
    - Post + top-level comments as base chunk
    - Group reply threads together
    - Preserve conversation threading
    - Example: Post + 5 comments → 1-2 chunks
    
    Blog Articles:
    - Chunk by sections/headings
    - Semantic boundaries (paragraphs)
    - Preserve topic coherence
    - Example: 2000-word article → 3-5 chunks
    
    Chunk Metadata (JSONB):
    -----------------------
    Store chunk-specific information:
    
    YouTube:
    {
        "start_time": 120,  # seconds
        "end_time": 240,
        "speaker": "host",
        "transcript_language": "en"
    }
    
    Reddit:
    {
        "comment_depth": 1,
        "comment_ids": ["abc123", "def456"],
        "is_controversial": false
    }
    
    Blog:
    {
        "section": "Introduction",
        "heading_level": 2,
        "paragraph_indices": [0, 1, 2]
    }
    
    Hybrid Search Support:
    ----------------------
    This model supports both semantic and keyword search:
    
    1. Semantic Search (Vector Similarity):
       - embedding column (768-dim vector)
       - HNSW index for fast cosine similarity
       - Query: "What is React hooks?" → Find semantically similar chunks
    
    2. Keyword Search (Full-Text):
       - text_search_vector column (tsvector)
       - GIN index for fast text search
       - Query: "React AND hooks" → Find exact keyword matches
    
    3. Hybrid Search:
       - Combine both approaches with weighted scoring
       - Example: 0.6 * semantic_score + 0.3 * keyword_score + 0.1 * metadata_boost
    
    Processing Pipeline:
    --------------------
    1. Content fetched and stored in ContentItem
    2. Celery task chunks the content
    3. Generate embeddings for each chunk
    4. Generate tsvector for full-text search
    5. Store in this table with status=PROCESSED
    6. Ready for RAG queries
    
    Example Usage:
    --------------
    # Create chunks from content
    chunks = chunker.chunk_content(content_item)
    
    for i, chunk_text in enumerate(chunks):
        chunk = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=i,
            chunk_text=chunk_text,
            chunk_metadata={"start_time": i * 120, "end_time": (i+1) * 120},
            processing_status="pending"
        )
        db.add(chunk)
    
    # Later: Generate embeddings
    for chunk in pending_chunks:
        chunk.embedding = embedder.embed(chunk.chunk_text)
        chunk.text_search_vector = generate_tsvector(chunk.chunk_text)
        chunk.processing_status = "processed"
    """
    
    __tablename__ = "content_chunks"
    
    # ================================
    # Foreign Key (Links to ContentItem)
    # ================================
    
    content_item_id: Mapped[int] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to content_items table"
    )
    # Links to parent ContentItem
    # CASCADE: Delete content item → delete all its chunks
    # Index: Fast queries for "all chunks from this content item"
    
    # ================================
    # Chunk Information
    # ================================
    
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Order of this chunk within the content item (0-indexed)"
    )
    # Preserves chunk order within content
    # 0 = first chunk, 1 = second chunk, etc.
    # Used for:
    # - Reconstructing content in order
    # - Showing context (previous/next chunks)
    # - Sorting search results chronologically
    
    chunk_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The actual text content of this chunk"
    )
    # The chunked text content
    # Base for both embedding and full-text search
    # Typically 500-1000 words (800 tokens with overlap)
    # TEXT type: No length limit
    
    chunk_metadata: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Content-type specific metadata (timestamps, section info, etc.)"
    )
    # Flexible storage for chunk-specific data
    # YouTube: timestamps, speaker info
    # Reddit: comment IDs, depth
    # Blog: section headings, paragraph indices
    
    # ================================
    # Embeddings & Search Vectors
    # ================================
    
    embedding = mapped_column(
        Vector(768),
        nullable=True,
        comment="768-dimensional embedding vector for semantic search"
    )
    # Vector embedding for semantic similarity search
    # Dimensions: 768 (google/embeddinggemma-300m)
    # Generated by embedding model
    # Used for: Cosine similarity search with pgvector
    # NULL until processed
    #
    # Note: Using pgvector.sqlalchemy.Vector type
    # Stores as PostgreSQL vector(768) type
    
    # Note: text_search_vector will be added in migration as tsvector type
    # SQLAlchemy doesn't have a built-in TSVector type, but we can define it in migration
    
    # ================================
    # Processing Status
    # ================================
    
    processing_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="Processing status: pending, processing, processed, failed"
    )
    # Track chunk processing pipeline
    # - pending: Chunk created, needs embedding
    # - processing: Currently generating embedding
    # - processed: Ready for RAG
    # - failed: Embedding generation failed (will retry)
    #
    # Index: Fast queries for "chunks that need processing"
    
    # ================================
    # Relationships
    # ================================
    
    content_item: Mapped["ContentItem"] = relationship(
        "ContentItem",
        back_populates="chunks",
        lazy="joined"
    )
    # Many-to-one with ContentItem
    # chunk.content_item gives you the parent ContentItem
    #
    # lazy="joined": Load content item with chunk
    # Useful when we need source metadata (channel, title)
    
    # ================================
    # Constraints
    # ================================
    
    __table_args__ = (
        UniqueConstraint(
            'content_item_id',
            'chunk_index',
            name='uq_content_item_chunk_index'
        ),
        # Prevent duplicate chunk indices for same content
        # Each content item has unique chunk sequence: 0, 1, 2, ...
    )
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        preview = self.chunk_text[:50] + "..." if self.chunk_text else ""
        return (
            f"ContentChunk(id={self.id}, content_item_id={self.content_item_id}, "
            f"index={self.chunk_index}, text='{preview}')"
        )
    
    @property
    def is_processed(self) -> bool:
        """Check if chunk is fully processed and ready for RAG."""
        return self.processing_status == "processed"
    
    @property
    def needs_processing(self) -> bool:
        """Check if chunk needs to be processed."""
        return self.processing_status == "pending"
