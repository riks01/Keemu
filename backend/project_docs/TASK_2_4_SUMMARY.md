# Sub-Task 2.4 Complete: ContentItem Model ✅

## 🎉 **Major Architectural Improvement!**

This sub-task involved a **significant architectural refactoring** that greatly improves the scalability and efficiency of the system!

**OLD DESIGN (Sub-Task 2.3):**
```
User (1) ←→ (Many) ContentSource
- Each user had their own ContentSource record
- Duplicate data for same channel across users
```

**NEW DESIGN (Sub-Task 2.4):**
```
User (Many) ←→ (Many) Channel via UserSubscription (Association Object)
Channel (1) ←→ (Many) ContentItem
- One shared Channel record per content source
- User-specific settings in UserSubscription
- Actual content in ContentItem
```

### Benefits of New Architecture:

1. **✅ Efficiency** - Fetch content once, serve to all subscribers
2. **✅ No duplication** - Channel metadata stored once
3. **✅ Analytics** - Easy to count subscribers per channel
4. **✅ User customization** - UserSubscription holds user-specific settings
5. **✅ Content Management** - ContentItem stores actual fetched content
6. **✅ Processing Pipeline** - Track content processing status

---

## 📋 **What We Built**

### 1. **Channel Model**
Shared content sources (YouTube channels, Reddit subreddits, Blogs)

**Key Features:**
- Source type (YouTube, Reddit, Blog)
- Source identifier (channel_id, subreddit, feed_url)
- Name and description
- Thumbnail URL
- Subscriber count (how many users follow)
- Active status
- Last fetched timestamp
- Unique constraint on (source_type, source_identifier)

### 2. **UserSubscription Model** (Association Object)
Many-to-many relationship between User and Channel with extra data

**Key Features:**
- User-specific subscription status (active/paused)
- Custom display name (user can rename channels)
- Notification settings per channel
- Last shown timestamp (engagement tracking)
- Unique constraint on (user_id, channel_id)

### 3. **ContentItem Model**
Actual content fetched from channels (videos, posts, articles)

**Key Features:**
- External ID (video_id, post_id, article_url)
- Title and content body (TEXT for long content)
- Author/creator name
- Published timestamp (timezone-aware)
- Processing status (PENDING → PROCESSING → PROCESSED → FAILED)
- Content metadata (JSONB for platform-specific data)
- Error message (for debugging)
- Unique constraint on (channel_id, external_id)

### 4. **ProcessingStatus Enum**
Track content through the processing pipeline

**Values:**
- `PENDING` - Just collected, waiting to be processed
- `PROCESSING` - Currently being processed (chunking, embedding)
- `PROCESSED` - Ready for RAG
- `FAILED` - Processing failed (will retry)

---

## 📁 **Files Created/Modified**

### New/Modified Files:
- `app/models/content.py` (747 lines) - Channel, UserSubscription, ContentItem models
- `app/models/user.py` - Updated subscriptions relationship
- `app/models/__init__.py` - Export new models and enums
- `alembic/env.py` - Import new models for migrations
- Migration: `2025-10-04_0724-9aae404a44eb_add_channels_user_subscriptions_and_.py`

### Database Tables Created:
1. **`channels`** - Shared content sources
2. **`user_subscriptions`** - Many-to-many junction table with user-specific data
3. **`content_items`** - Actual content from channels

### Database Tables Removed:
- **`content_sources`** - Old one-to-many design (replaced by new architecture)

---

## 🗄️ **Database Schema**

### Tables Overview:

```
┌──────────────────┐
│      users       │
└─────────┬────────┘
          │
          │ One-to-Many
          ▼
┌────────────────────────┐         ┌──────────────────┐
│  user_subscriptions    │◄────────│    channels      │
│  (Association Object)  │ Many    │  (Shared Source) │
├────────────────────────┤         ├──────────────────┤
│ user_id (FK)          │         │ source_type      │
│ channel_id (FK)       │         │ source_identifier│
│ is_active             │         │ name             │
│ custom_display_name   │         │ description      │
│ notification_enabled  │         │ thumbnail_url    │
│ last_shown_at         │         │ subscriber_count │
└────────────────────────┘         │ is_active        │
                                   │ last_fetched_at  │
                                   └─────────┬────────┘
                                             │
                                             │ One-to-Many
                                             ▼
                                   ┌──────────────────┐
                                   │  content_items   │
                                   ├──────────────────┤
                                   │ channel_id (FK)  │
                                   │ external_id      │
                                   │ title            │
                                   │ content_body     │
                                   │ author           │
                                   │ published_at     │
                                   │ processing_status│
                                   │ content_metadata │
                                   │ error_message    │
                                   └──────────────────┘
```

### Detailed Schema:

#### **channels** table:
```sql
CREATE TABLE channels (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR NOT NULL,  -- youtube, reddit, blog
    source_identifier VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    thumbnail_url VARCHAR(255),
    subscriber_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_fetched_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE(source_type, source_identifier)
);

CREATE INDEX ix_channels_source_type ON channels(source_type);
```

#### **user_subscriptions** table:
```sql
CREATE TABLE user_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    custom_display_name VARCHAR(100),
    notification_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_shown_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE(user_id, channel_id)
);

CREATE INDEX ix_user_subscriptions_user_id ON user_subscriptions(user_id);
CREATE INDEX ix_user_subscriptions_channel_id ON user_subscriptions(channel_id);
```

#### **content_items** table:
```sql
CREATE TABLE content_items (
    id SERIAL PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    external_id VARCHAR(255) NOT NULL,
    title VARCHAR(500) NOT NULL,
    content_body TEXT NOT NULL,
    author VARCHAR(100) NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    processing_status VARCHAR NOT NULL DEFAULT 'pending',
    content_metadata JSONB,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE(channel_id, external_id)
);

CREATE INDEX ix_content_items_channel_id ON content_items(channel_id);
CREATE INDEX ix_content_items_processing_status ON content_items(processing_status);
CREATE INDEX ix_content_items_published_at ON content_items(published_at);
```

---

## 🎓 **Key Concepts Learned**

### 1. **Many-to-Many with Association Object**

**Simple Many-to-Many** (just a junction table):
```python
# Simple junction table with only foreign keys
user_channels = Table('user_channels', Base.metadata,
    Column('user_id', ForeignKey('users.id')),
    Column('channel_id', ForeignKey('channels.id'))
)
```

**Association Object** (junction table with extra data):
```python
# Full model with foreign keys + extra data
class UserSubscription(BaseModel):
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    custom_display_name: Mapped[str | None] = mapped_column(...)
    # ... more fields
```

**Why Use Association Object?**
- Store user-specific settings
- Track engagement metrics per user
- Allow independent customization
- Better for complex relationships

### 2. **JSONB for Flexible Metadata**

**Why JSONB?**
- Store platform-specific data without schema changes
- Queryable in PostgreSQL
- Binary format (faster than JSON)
- Supports indexes

**Example Queries:**
```python
# Query by JSON field
result = await db.execute(
    select(ContentItem).where(
        ContentItem.content_metadata['view_count'].astext.cast(Integer) > 1000000
    )
)

# Query if JSON key exists
result = await db.execute(
    select(ContentItem).where(
        ContentItem.content_metadata.has_key('duration')
    )
)
```

**Platform-Specific Metadata Examples:**

**YouTube:**
```json
{
    "video_id": "dQw4w9WgXcQ",
    "duration": 213,
    "view_count": 1000000,
    "like_count": 50000,
    "comment_count": 5000,
    "thumbnail_url": "https://...",
    "transcript_language": "en"
}
```

**Reddit:**
```json
{
    "post_id": "abc123",
    "subreddit": "programming",
    "score": 500,
    "num_comments": 50,
    "upvote_ratio": 0.95,
    "url": "https://reddit.com/r/programming/...",
    "top_comments": [
        {"author": "user1", "body": "Great post!", "score": 100}
    ]
}
```

**Blog:**
```json
{
    "url": "https://blog.example.com/article",
    "word_count": 1500,
    "tags": ["python", "tutorial"],
    "featured_image": "https://...",
    "excerpt": "A brief summary..."
}
```

### 3. **TEXT vs VARCHAR**

**VARCHAR(n)** - Variable-length string with maximum length:
- Use for: names, titles, short descriptions
- Limit: 255, 500, 1000 chars
- Fast indexing

**TEXT** - Unlimited length string:
- Use for: article content, transcripts, long descriptions
- No length limit
- Slower indexing (use only when needed)

### 4. **Processing Pipeline with Status Tracking**

Content goes through stages:
```
1. COLLECTION → Celery fetches content
   ↓
2. PENDING → Content stored, awaiting processing
   ↓
3. PROCESSING → Chunking, embedding generation
   ↓
4. PROCESSED → Ready for RAG system
   ↓ (error path)
5. FAILED → Retry logic
```

Query patterns:
```python
# Get pending content for processing
pending = await db.execute(
    select(ContentItem)
    .where(ContentItem.processing_status == ProcessingStatus.PENDING)
    .order_by(ContentItem.created_at)
    .limit(100)
)

# Get failed content for retry
failed = await db.execute(
    select(ContentItem)
    .where(ContentItem.processing_status == ProcessingStatus.FAILED)
)

# Get processed content ready for RAG
processed = await db.execute(
    select(ContentItem)
    .where(
        ContentItem.processing_status == ProcessingStatus.PROCESSED,
        ContentItem.published_at >= datetime.now() - timedelta(days=30)
    )
)
```

### 5. **Timezone-Aware Timestamps**

Always use `DateTime(timezone=True)`:
```python
published_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),  # ← CRITICAL!
    nullable=False
)
```

Benefits:
- Correct ordering across timezones
- No DST bugs
- Consistent UTC storage
- Automatic timezone conversion

### 6. **Reserved Names in SQLAlchemy**

**DO NOT USE** these column names:
- `metadata` - Reserved by SQLAlchemy
- `query` - Reserved by session
- `id` - OK but inherited from BaseModel

**Solution:**
```python
# ❌ Bad
metadata: Mapped[dict] = mapped_column(JSONB)

# ✅ Good
content_metadata: Mapped[dict] = mapped_column(JSONB)
```

---

## 💡 **Common Usage Patterns**

### 1. **User Subscribes to a Channel**

```python
from app.models import Channel, UserSubscription, ContentSourceType

# Check if channel exists
result = await db.execute(
    select(Channel).where(
        Channel.source_type == ContentSourceType.YOUTUBE,
        Channel.source_identifier == "UCsBjURrPoezykLs9EqgamOA"
    )
)
channel = result.scalar_one_or_none()

if not channel:
    # Create channel if it doesn't exist
    channel = Channel(
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="UCsBjURrPoezykLs9EqgamOA",
        name="Fireship",
        description="High-intensity code tutorials",
        thumbnail_url="https://..."
    )
    db.add(channel)
    await db.flush()  # Get channel.id

# Create subscription
subscription = UserSubscription(
    user_id=user.id,
    channel_id=channel.id,
    is_active=True,
    notification_enabled=True
)
db.add(subscription)

# Update subscriber count
channel.subscriber_count += 1

await db.commit()
```

### 2. **Get User's Active Subscriptions**

```python
# Load user with subscriptions
user = await db.get(User, user_id)

# Get active channels
active_channels = [
    sub.channel 
    for sub in user.subscriptions 
    if sub.is_active
]

# Or with query
result = await db.execute(
    select(Channel)
    .join(UserSubscription)
    .where(
        UserSubscription.user_id == user_id,
        UserSubscription.is_active == True
    )
)
channels = result.scalars().all()
```

### 3. **Fetch and Store Content**

```python
from datetime import datetime, timezone
from app.models import ContentItem, ProcessingStatus

# Fetch YouTube video (example)
video_data = await youtube_api.get_video(video_id)

# Create content item
content = ContentItem(
    channel_id=channel.id,
    external_id=video_data['id'],
    title=video_data['title'],
    content_body=video_data['transcript'],
    author=video_data['channel_name'],
    published_at=video_data['published_at'],
    processing_status=ProcessingStatus.PENDING,
    content_metadata={
        "video_id": video_data['id'],
        "duration": video_data['duration'],
        "view_count": video_data['view_count'],
        "like_count": video_data['like_count'],
    }
)
db.add(content)
await db.commit()

# Update channel's last_fetched_at
channel.last_fetched_at = datetime.now(timezone.utc)
await db.commit()
```

### 4. **Process Content Pipeline**

```python
# Get pending content
result = await db.execute(
    select(ContentItem)
    .where(ContentItem.processing_status == ProcessingStatus.PENDING)
    .limit(10)
)
pending_items = result.scalars().all()

for item in pending_items:
    try:
        # Update status to processing
        item.processing_status = ProcessingStatus.PROCESSING
        await db.commit()
        
        # Process content (chunk, embed)
        await process_content(item)
        
        # Mark as processed
        item.processing_status = ProcessingStatus.PROCESSED
        await db.commit()
        
    except Exception as e:
        # Mark as failed with error message
        item.processing_status = ProcessingStatus.FAILED
        item.error_message = str(e)
        await db.commit()
```

### 5. **Get Recent Content for User**

```python
from datetime import timedelta

# Get content from user's active subscriptions
result = await db.execute(
    select(ContentItem)
    .join(Channel)
    .join(UserSubscription)
    .where(
        UserSubscription.user_id == user_id,
        UserSubscription.is_active == True,
        ContentItem.processing_status == ProcessingStatus.PROCESSED,
        ContentItem.published_at >= datetime.now() - timedelta(days=7)
    )
    .order_by(ContentItem.published_at.desc())
)
recent_content = result.scalars().all()
```

---

## 🔧 **Migration Notes**

### What Changed:

1. **Removed:**
   - `content_sources` table
   - Old `ContentSourceType` enum

2. **Added:**
   - `channels` table with unique constraint
   - `user_subscriptions` table with unique constraint
   - `content_items` table with unique constraint
   - New `ContentSourceType` enum (same values, recreated)
   - New `ProcessingStatus` enum

### Migration Process:

```bash
# 1. Drop old table and enum
docker compose exec postgres psql -U keemu_user -d keemu_db \
  -c "DROP TABLE IF EXISTS content_sources CASCADE;"
docker compose exec postgres psql -U keemu_user -d keemu_db \
  -c "DROP TYPE IF EXISTS contentsourcetype CASCADE;"

# 2. Generate migration
docker compose exec api alembic revision --autogenerate \
  -m "add channels, user_subscriptions, and content_items tables"

# 3. Apply migration
docker compose exec api alembic upgrade head

# 4. Verify tables
docker compose exec postgres psql -U keemu_user -d keemu_db -c "\dt"
```

---

## ✅ **Next Steps**

**Sub-Task 2.5: Summary Model** (Pending)
- Store AI-generated summaries
- Link to users
- Period-based summaries
- Email tracking

**Sub-Task 2.6: Conversation Model** (Pending)
- Store RAG chat history
- Messages table
- Retrieved chunks tracking
- Conversation context

---

## 🎊 **Milestone Achieved!**

**Database Models Progress:** ✅✅✅✅ (4/6 complete)

Completed:
- ✅ Sub-Task 2.1: Database Foundation
- ✅ Sub-Task 2.2: User & UserPreferences
- ✅ Sub-Task 2.3: ContentSource (replaced with new architecture)
- ✅ Sub-Task 2.4: Channel + UserSubscription + ContentItem

**Key Achievement:**
- Refactored from simple one-to-many to sophisticated many-to-many with association object
- Added content storage and processing pipeline
- Ready for content collection and RAG system!

**Database now has:**
- 6 tables (users, user_preferences, channels, user_subscriptions, content_items, alembic_version)
- Multiple relationship types (1-to-1, 1-to-many, many-to-many)
- JSONB for flexible metadata
- Processing pipeline status tracking
- Comprehensive indexes

**Your architecture is production-ready!** 🚀
