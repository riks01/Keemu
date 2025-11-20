"""
User Models

This module contains the User, UserPreferences, and ContentSource models.

Models Included:
----------------
1. User - Core user account information
2. UserPreferences - User settings and preferences
3. ContentSource - Content sources users follow (YouTube, Reddit, Blogs)
4. SummaryLength (Enum) - Choice field for summary preferences
5. UpdateFrequency (Enum) - Choice field for update intervals
6. ContentSourceType (Enum) - Choice field for content source types

Database Tables:
----------------
- users: Stores user account data
- user_preferences: Stores user settings (1-to-1 with users)
- content_sources: Stores content sources (many-to-1 with users)

Learning Resources:
-------------------
- SQLAlchemy Relationships: https://docs.sqlalchemy.org/en/20/orm/basic_relationships.html
- Enums in SQLAlchemy: https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Enum
"""

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, String50, String100, String255

# Type checking imports - these are only imported for type hints, not at runtime
# This prevents circular import issues
if TYPE_CHECKING:
    from app.models.conversation import Conversation


# ================================
# Enums for Choice Fields
# ================================

class SummaryLength(str, enum.Enum):
    """
    Enum for summary length preferences.
    
    What's an Enum?
    ---------------
    An enumeration is a set of predefined constant values.
    Think of it like a dropdown menu in a form - users can only choose
    from these specific options.
    
    Benefits of Using Enums:
    ------------------------
    1. Type Safety: Can't set invalid values
    2. Database Integrity: PostgreSQL creates a CHECK constraint
    3. Self-Documenting: Code clearly shows valid options
    4. IDE Support: Autocomplete shows all choices
    
    Why (str, enum.Enum)?
    ---------------------
    - str: Makes the enum value a string (stored as text in database)
    - enum.Enum: Makes it an enumeration
    
    Database Storage:
    -----------------
    Stored as VARCHAR with CHECK constraint:
    CHECK (summary_length IN ('concise', 'standard', 'detailed'))
    
    Usage Example:
    --------------
    user_prefs.summary_length = SummaryLength.STANDARD
    if user_prefs.summary_length == SummaryLength.CONCISE:
        max_words = 300
    """
    
    CONCISE = "concise"      # ~300 words, quick overview
    STANDARD = "standard"    # ~500 words, balanced detail
    DETAILED = "detailed"    # ~800 words, comprehensive
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class UpdateFrequency(str, enum.Enum):
    """
    Enum for update frequency preferences.
    
    How Often Should Users Receive Digests?
    ----------------------------------------
    This determines the schedule for:
    - Content collection (how often we check sources)
    - Summary generation (when we create digests)
    - Email notifications (when users get notified)
    
    Frequency Options:
    ------------------
    - DAILY: Every day at user's preferred time
    - EVERY_3_DAYS: Every 3 days (Monday, Thursday, etc.)
    - WEEKLY: Once per week (user chooses day)
    - EVERY_2_WEEKS: Bi-weekly
    - MONTHLY: Once per month
    
    Custom Intervals:
    -----------------
    For now, we provide fixed options. Later we could add:
    - Custom day-of-week selection
    - Custom time preferences
    - Multiple digest times
    
    Usage Example:
    --------------
    if user_prefs.update_frequency == UpdateFrequency.DAILY:
        schedule_for_tomorrow()
    elif user_prefs.update_frequency == UpdateFrequency.WEEKLY:
        schedule_for_next_week(user_prefs.preferred_day)
    """
    
    DAILY = "daily"
    EVERY_3_DAYS = "every_3_days"
    WEEKLY = "weekly"
    EVERY_2_WEEKS = "every_2_weeks"
    MONTHLY = "monthly"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


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
       - Collect new videos from subscribed channels
       - Use YouTube Data API v3
       - Fetch video titles, descriptions, thumbnails
       - Example: "Fireship", "Traversy Media"
    
    2. REDDIT: Reddit communities (subreddits)
       - Collect top posts from subscribed subreddits
       - Use Reddit API (PRAW)
       - Fetch post titles, content, comments
       - Example: r/programming, r/python
    
    3. BLOG: Blogs and RSS feeds
       - Collect posts from RSS/Atom feeds
       - Use feedparser library
       - Fetch article titles, content, links
       - Example: blog.example.com/feed.xml
    
    Why These Platforms?
    --------------------
    - YouTube: Most popular video platform
    - Reddit: Rich community discussions
    - Blogs: Technical content, tutorials, news
    
    Future Platforms:
    -----------------
    Could add support for:
    - Twitter/X (via API)
    - Hacker News (RSS or API)
    - Medium (via RSS)
    - Dev.to (via API)
    - GitHub repos (via API)
    
    How It Works:
    -------------
    1. User adds a content source (e.g., YouTube channel)
    2. Celery periodic task fetches new content
    3. Content stored in database
    4. RAG system processes and summarizes
    5. User receives digest email
    
    Database Storage:
    -----------------
    Stored as VARCHAR with CHECK constraint:
    CHECK (source_type IN ('youtube', 'reddit', 'blog'))
    
    Usage Example:
    --------------
    # Add YouTube channel
    source = ContentSource(
        user_id=user.id,
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="UCsBjURrPoezykLs9EqgamOA",  # Channel ID
        display_name="Fireship"
    )
    
    # Query by type
    youtube_sources = await db.execute(
        select(ContentSource)
        .where(ContentSource.source_type == ContentSourceType.YOUTUBE)
    )
    """
    
    YOUTUBE = "youtube"
    REDDIT = "reddit"
    BLOG = "blog"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


# ================================
# User Model
# ================================

class User(BaseModel):
    """
    User account model.
    
    This model represents a user account in the system. Users authenticate
    via Google OAuth and can customize their content preferences.
    
    Table: users
    ------------
    Inherits from BaseModel, which automatically provides:
    - id (int, primary key, auto-increment)
    - created_at (datetime, UTC, set on creation)
    - updated_at (datetime, UTC, updates automatically)
    
    Authentication Flow:
    --------------------
    1. User clicks "Sign in with Google"
    2. Google returns: email, name, profile_picture
    3. We check if user exists (by email)
    4. If new: Create User record
    5. If existing: Update last_login
    6. Generate JWT token
    7. Return token to frontend
    
    Personal Information:
    ---------------------
    We collect minimal information:
    - email: For communication and login (from Google)
    - name: Display name (from Google)
    - profile_picture: Avatar URL (from Google)
    - date_of_birth: For personalization (user provides)
    - profession: For content recommendations (user provides)
    
    Why We Ask for DOB and Profession:
    -----------------------------------
    - date_of_birth: Could be used for:
      * Age-appropriate content filtering
      * Birthday notifications/features
      * Analytics (age demographics)
    
    - profession: Useful for:
      * Content recommendations (industry-specific)
      * Better RAG responses (context-aware)
      * User segmentation
    
    Privacy Notes:
    --------------
    - All personal data is optional (except email)
    - Users can update/delete anytime
    - Never shared with third parties
    - Stored securely with encryption at rest
    
    Relationships:
    --------------
    - preferences (1-to-1): User's settings and preferences
    - content_sources (1-to-many): YouTube, Reddit, Blogs user follows
    - summaries (1-to-many): Generated digests
    - conversations (1-to-many): Chat history with RAG system
    
    Future Enhancements:
    --------------------
    - Add OAuth from other providers (GitHub, Twitter)
    - Add 2FA (two-factor authentication)
    - Add email verification
    - Add password reset (if we add password auth)
    """
    
    __tablename__ = "users"
    
    # ================================
    # Authentication Fields (from Google OAuth)
    # ================================
    
    email: Mapped[str] = mapped_column(
        String255,
        unique=True,
        index=True,
        nullable=False,
        comment="User's email address (from Google OAuth). Must be unique."
    )
    # Why unique=True?
    # - Email is our primary identifier for login
    # - Can't have two users with same email
    # - PostgreSQL creates a UNIQUE constraint
    #
    # Why index=True?
    # - We frequently query users by email (login, lookup)
    # - Index makes these queries MUCH faster
    # - Without index: Scans entire table (slow)
    # - With index: Direct lookup like a phone book (fast)
    #
    # Why nullable=False?
    # - Email is required for authentication
    # - Can't log in without an email
    # - Database enforces this (NOT NULL constraint)
    
    name: Mapped[str] = mapped_column(
        String100,
        nullable=False,
        comment="User's display name (from Google OAuth)"
    )
    # This is the name Google provides (e.g., "John Smith")
    # We use this for:
    # - Personalized greetings: "Hi John!"
    # - Display in UI
    # - Email salutations
    
    profile_picture: Mapped[str | None] = mapped_column(
        String255,
        nullable=True,
        default=None,
        comment="URL to user's profile picture (from Google OAuth)"
    )
    # Why nullable=True?
    # - User might not have a profile picture on Google
    # - Not required for functionality
    # - Can be None/NULL in database
    #
    # Type hint: str | None means:
    # - Can be a string (URL)
    # - Can be None (no picture)
    # - Python 3.10+ syntax (older: Optional[str])
    #
    # Storage:
    # - We store the URL, not the actual image
    # - Google hosts the image
    # - We just reference it
    # - Example: "https://lh3.googleusercontent.com/a/..."
    
    hashed_password: Mapped[str | None] = mapped_column(
        String255,
        nullable=True,
        default=None,
        comment="Hashed password (for password-based authentication)"
    )
    # Password-Based Authentication (Optional)
    # -----------------------------------------
    # Why nullable=True?
    # - Users who sign up via Google OAuth don't have a password
    # - Users who sign up with email/password have this set
    # - Allows both authentication methods
    #
    # Security:
    # - NEVER store plaintext passwords
    # - Always hash with bcrypt (get_password_hash())
    # - Verify with constant-time comparison (verify_password())
    # - Minimum 8 characters, max 72 bytes (bcrypt limit)
    #
    # Authentication Flow:
    # - Google OAuth users: hashed_password = None
    # - Password users: hashed_password = bcrypt hash
    # - Mixed: User starts with Google, can add password later
    #
    # Usage:
    # from app.core.security import get_password_hash, verify_password
    # 
    # # Set password
    # user.hashed_password = get_password_hash("SecurePassword123!")
    # 
    # # Verify password
    # if verify_password("SecurePassword123!", user.hashed_password):
    #     print("Password correct!")
    #
    # Check if user has password:
    # if user.hashed_password:
    #     # User can login with password
    # else:
    #     # User must use Google OAuth
    
    # ================================
    # User-Provided Personal Information
    # ================================
    
    profession: Mapped[str | None] = mapped_column(
        String100,
        nullable=True,
        default=None,
        comment="User's profession/occupation"
    )
    # YOU REQUESTED THIS FIELD! 🎯
    #
    # Use Cases:
    # - Content recommendations based on industry
    # - RAG system can provide profession-specific insights
    # - Analytics: Understand our user demographics
    # - Example values: "Software Engineer", "Product Manager", "Student"
    #
    # Why nullable?
    # - Optional field (user can skip)
    # - Can be filled in later
    # - Not required for core functionality
    
    date_of_birth: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        default=None,
        comment="User's date of birth"
    )
    # YOU REQUESTED THIS FIELD! 🎯
    #
    # Why Date type (not DateTime)?
    # - We only need the date, not the time
    # - Birthdays don't have hours/minutes
    # - Saves storage space
    # - More semantically correct
    #
    # Type: date (from datetime module)
    # - Not a string like "1990-01-15"
    # - Actual Python date object
    # - Can do date math: age = today - date_of_birth
    #
    # Example usage:
    # from datetime import date
    # user.date_of_birth = date(1990, 1, 15)
    # age = (date.today() - user.date_of_birth).days // 365
    #
    # Privacy Considerations:
    # - Sensitive information
    # - Store securely
    # - Never display publicly
    # - Use for personalization only
    
    # ================================
    # System Fields
    # ================================
    
    timezone: Mapped[str] = mapped_column(
        String50,
        nullable=False,
        default="UTC",
        comment="User's timezone for scheduling notifications"
    )
    # Why do we need timezone?
    # - Users are in different timezones
    # - Want to send digests at their preferred time
    # - 9 AM in New York ≠ 9 AM in Los Angeles
    #
    # Example values:
    # - "America/New_York"
    # - "Europe/London"
    # - "Asia/Tokyo"
    # - "UTC" (default)
    #
    # How it works:
    # 1. We store all times in UTC (created_at, updated_at)
    # 2. When scheduling: Convert UTC → User's timezone
    # 3. Send digest at user's local 9 AM
    #
    # Why default="UTC"?
    # - Safe fallback if user doesn't specify
    # - UTC is universal reference point
    # - Can be changed later by user
    #
    # Technical note:
    # - Uses IANA timezone database
    # - NOT UTC offsets like "+05:30" (those change with DST)
    # - Always use timezone names like "America/New_York"
    
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether user account is active"
    )
    # What does is_active mean?
    # - True: Normal user, can login and use system
    # - False: Account disabled (soft delete)
    #
    # Why soft delete instead of actually deleting?
    # - Preserve data integrity
    # - Keep historical records (summaries, content)
    # - Can reactivate if user comes back
    # - Comply with data retention policies
    #
    # When set to False:
    # - User can't login
    # - No new content collected
    # - No summaries generated
    # - No emails sent
    # - BUT: Data still exists
    #
    # Usage:
    # if user.is_active:
    #     allow_login()
    # else:
    #     show_account_disabled_message()
    
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Last time user logged in (UTC)"
    )
    # Track user engagement
    # - When did they last visit?
    # - Useful for analytics
    # - Detect inactive users
    # - Send re-engagement emails
    #
    # Updated on every login:
    # user.last_login = datetime.now(timezone.utc)
    # await db.commit()
    #
    # DateTime(timezone=True): Store as TIMESTAMP WITH TIME ZONE
    # - Matches created_at and updated_at
    # - Handles timezone-aware datetimes
    
    # ================================
    # Relationships
    # ================================
    
    preferences: Mapped["UserPreferences"] = relationship(
        "UserPreferences",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="joined"
    )
    # One-to-One Relationship with UserPreferences
    #
    # What's a relationship?
    # ----------------------
    # - Links two models together
    # - Allows accessing related data easily
    # - No extra column in this table (it's on the other side)
    #
    # Usage:
    # ------
    # user = await db.get(User, 1)
    # print(user.preferences.update_frequency)  # Access preferences directly
    #
    # Relationship Parameters Explained:
    # -----------------------------------
    #
    # 1. "UserPreferences" (string, not class):
    #    - Forward reference (class defined below)
    #    - Prevents circular import issues
    #    - SQLAlchemy resolves it later
    #
    # 2. back_populates="user":
    #    - Creates bi-directional relationship
    #    - UserPreferences has a 'user' field pointing back
    #    - user.preferences and preferences.user both work
    #
    # 3. cascade="all, delete-orphan":
    #    - When user is deleted → preferences are deleted too
    #    - When preferences.user = None → preferences is deleted
    #    - Maintains referential integrity
    #    - Prevents orphaned records
    #
    # 4. uselist=False:
    #    - One-to-One relationship (not One-to-Many)
    #    - user.preferences returns single object (not list)
    #    - If uselist=True: user.preferences would be a list
    #
    # 5. lazy="joined":
    #    - Load strategy - when to fetch related data
    #    - "joined": Load with a JOIN query (1 query instead of 2)
    #    - "select": Separate query when accessed (N+1 problem)
    #    - "selectin": Separate query but optimized
    #
    #    Example of N+1 problem (lazy="select"):
    #    users = await db.execute(select(User))  # 1 query
    #    for user in users:
    #        print(user.preferences.update_frequency)  # N queries!
    #
    #    With lazy="joined":
    #    users = await db.execute(select(User))  # 1 query, includes preferences
    #    for user in users:
    #        print(user.preferences.update_frequency)  # No additional query
    
    # ================================
    # One-to-Many Relationships
    # ================================
    
    subscriptions: Mapped[list["UserSubscription"]] = relationship(
        "UserSubscription",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    # One-to-Many Relationship with UserSubscription
    # -----------------------------------------------
    # One user can have many channel subscriptions
    #
    # NEW ARCHITECTURE:
    # User (Many) ←→ (Many) Channel via UserSubscription
    #
    # Usage:
    # user = await db.get(User, 1)
    # for subscription in user.subscriptions:
    #     channel = subscription.channel
    #     print(f"{channel.name} ({channel.source_type.value})")
    #     print(f"  Active: {subscription.is_active}")
    #     print(f"  Custom name: {subscription.custom_display_name}")
    #
    # Get all channels user subscribes to:
    # channels = [sub.channel for sub in user.subscriptions if sub.is_active]
    #
    # Relationship Parameters:
    # ------------------------
    # 1. back_populates="user": Bi-directional relationship
    # 2. cascade="all, delete-orphan":
    #    - Delete user → delete all their subscriptions
    #    - Remove subscription from list → delete from database
    # 3. lazy="selectin":
    #    - Load subscriptions with a separate SELECT query
    #    - More efficient than "joined" for one-to-many
    #    - Avoids cartesian product issues
    #
    # Why lazy="selectin" instead of "joined"?
    # ----------------------------------------
    # For one-to-many relationships, "selectin" is better:
    # - "joined": Creates cartesian product (duplicate rows)
    # - "selectin": Two separate queries (cleaner)
    #
    # Example with 1 user having 10 subscriptions:
    # - "joined": Returns 10 rows with duplicated user data
    # - "selectin": 2 queries total (1 for user, 1 for subscriptions)
    
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin"
        # order_by handled by query if needed
    )
    # One-to-many with Conversation
    # - One user can have many chat conversations
    # - Delete user → delete all their conversations
    # - Ordered by last_message_at (most recent first)
    
    # Future Relationships:
    # -----------------------------------------------------------
    # summaries: Mapped[list["Summary"]] = relationship(...)
    
    def __repr__(self) -> str:
        """
        String representation for debugging.
        
        Example output: User(id=1, email='alice@example.com')
        """
        return f"User(id={self.id}, email='{self.email}')"
    
    @property
    def age(self) -> int | None:
        """
        Calculate user's age from date_of_birth.
        
        What's a @property?
        -------------------
        - Makes a method look like an attribute
        - Called without parentheses: user.age (not user.age())
        - Computed on-the-fly (not stored in database)
        
        Returns:
            User's age in years, or None if date_of_birth not set
        
        Example:
            user.date_of_birth = date(1990, 1, 15)
            print(user.age)  # 34 (in 2024)
        """
        if self.date_of_birth is None:
            return None
        
        from datetime import date
        today = date.today()
        age = today.year - self.date_of_birth.year
        
        # Adjust if birthday hasn't occurred this year yet
        if (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day):
            age -= 1
        
        return age


# ================================
# UserPreferences Model
# ================================

class UserPreferences(BaseModel):
    """
    User preferences and settings model.
    
    This model stores user-configurable settings that control:
    - How often they receive content digests
    - What format/length of summaries they prefer
    - Notification preferences
    
    Table: user_preferences
    -----------------------
    One-to-one relationship with User table.
    Every user has exactly ONE preferences record.
    
    Why Separate Table?
    -------------------
    Could we just add these columns to the User table?
    Yes! But separating has benefits:
    
    Pros of Separate Table:
    1. Organization: User = identity, UserPreferences = settings
    2. Flexibility: Easy to add/remove preference fields
    3. Performance: Don't load preferences if not needed
    4. Clarity: Clear separation of concerns
    
    Cons of Separate Table:
    1. Extra JOIN when querying
    2. Slightly more complex queries
    3. One more table to manage
    
    In our case, the benefits outweigh the costs because:
    - We frequently update preferences independently
    - Preferences might grow (many fields in the future)
    - Clear separation makes code more maintainable
    
    Default Values:
    ---------------
    When a new user signs up, we create preferences with:
    - update_frequency: WEEKLY (good balance)
    - summary_length: STANDARD (medium detail)
    - email_notifications_enabled: True (they expect emails)
    
    These defaults can be customized during onboarding.
    
    Relationships:
    --------------
    - user (1-to-1): The user these preferences belong to
    """
    
    __tablename__ = "user_preferences"
    
    # ================================
    # Foreign Key (Links to User)
    # ================================
    
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        comment="Foreign key to users table"
    )
    # Foreign Key Explained:
    # ----------------------
    # - Links this preferences record to a specific user
    # - ForeignKey("users.id"): Points to User.id column
    # - unique=True: Each user can have only ONE preferences record
    # - nullable=False: Must belong to a user (can't be orphaned)
    #
    # ondelete="CASCADE":
    # - When user is deleted → this preferences record is deleted too
    # - Automatic cleanup
    # - Maintains referential integrity
    # - Alternative: ondelete="SET NULL" (sets user_id to NULL instead)
    #
    # Database Constraint:
    # - PostgreSQL creates: FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    # - Enforces relationship at database level
    # - Can't have preferences for non-existent user
    
    # ================================
    # Content Preferences
    # ================================
    
    update_frequency: Mapped[UpdateFrequency] = mapped_column(
        nullable=False,
        default=UpdateFrequency.WEEKLY,
        comment="How often user receives content digests"
    )
    # Stores one of: daily, every_3_days, weekly, every_2_weeks, monthly
    #
    # Why WEEKLY as default?
    # - Good balance: Not too frequent, not too rare
    # - Manageable content volume
    # - Most users prefer weekly updates
    # - Can be changed during onboarding
    #
    # How it works:
    # 1. Celery Beat scheduler checks this field
    # 2. Schedules next digest based on value
    # 3. User receives email at their preferred time
    #
    # Future enhancement:
    # - Allow custom day selection (e.g., "Every Monday")
    # - Multiple frequencies (daily email + weekly summary)
    # - Pause/resume subscriptions
    
    summary_length: Mapped[SummaryLength] = mapped_column(
        nullable=False,
        default=SummaryLength.STANDARD,
        comment="Preferred summary detail level"
    )
    # Stores one of: concise (~300 words), standard (~500), detailed (~800)
    #
    # How it affects summaries:
    # - CONCISE: Quick bullet points, key highlights only
    # - STANDARD: Balanced overview with context
    # - DETAILED: Comprehensive with examples and analysis
    #
    # Passed to Claude when generating summaries:
    # if summary_length == SummaryLength.CONCISE:
    #     max_words = 300
    # elif summary_length == SummaryLength.STANDARD:
    #     max_words = 500
    # else:
    #     max_words = 800
    #
    # User can change this anytime based on:
    # - How much time they have to read
    # - Level of detail they need
    # - Device (concise for mobile, detailed for desktop)
    
    email_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether to send email notifications"
    )
    # Simple on/off switch for email notifications
    #
    # When True:
    # - User receives email when digest is ready
    # - Email contains summary highlights
    # - Link to full digest in app
    #
    # When False:
    # - No emails sent
    # - User checks app manually
    # - Digest still generated and available
    #
    # Why default=True?
    # - Main value proposition is email digests
    # - Users expect notifications after signing up
    # - Easy to disable if they change their mind
    #
    # Compliance:
    # - User can disable anytime
    # - Honors opt-out immediately
    # - Complies with CAN-SPAM Act
    # - Required for GDPR compliance
    
    # Future preference fields we might add:
    # --------------------------------------
    # preferred_notification_time: time = "09:00"
    # preferred_day_of_week: int = 1  # Monday
    # content_filters: list[str] = ["technology", "ai"]
    # exclude_sources: list[int] = [1, 5, 10]  # Source IDs to exclude
    # language_preference: str = "en"
    # digest_format: str = "html" or "plaintext"
    
    # ================================
    # Relationships
    # ================================
    
    user: Mapped["User"] = relationship(
        "User",
        back_populates="preferences",
        lazy="joined"
    )
    # Back-reference to User
    #
    # Usage:
    # prefs = await db.get(UserPreferences, 1)
    # print(prefs.user.email)  # Access user directly
    #
    # lazy="joined":
    # - Always load user with preferences
    # - Makes sense because we almost always need user info
    # - Prevents extra queries
    
    def __repr__(self) -> str:
        """
        String representation for debugging.
        
        Example: UserPreferences(id=1, user_id=1, frequency=weekly)
        """
        return (
            f"UserPreferences(id={self.id}, user_id={self.user_id}, "
            f"frequency={self.update_frequency.value})"
        )
