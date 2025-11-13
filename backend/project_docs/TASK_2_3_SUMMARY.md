# Sub-Task 2.3 Complete: ContentSource Model ✅

## What We Built

We created the **ContentSource** model which represents content sources users follow (YouTube channels, Reddit subreddits, Blogs/RSS feeds).

### Models Created:

1. **`ContentSource`** - Content sources model
   - YouTube channels (channel IDs)
   - Reddit communities (subreddit names)
   - Blogs/RSS feeds (feed URLs)
   - Active/inactive status tracking
   - Last fetch timestamps
   - User-customizable display names

2. **`ContentSourceType`** (Enum) - Platform types
   - YOUTUBE
   - REDDIT
   - BLOG

3. **Relationship:** `User (1) ←→ (Many) ContentSource`
   - One user can follow many sources
   - Each source belongs to one user
   - Cascade delete

---

## Files Created/Modified

### New Files:
- `test_content_source_model.py` (373 lines) - Comprehensive model tests

### Modified Files:
- `app/models/user.py` - Added ContentSource model and ContentSourceType enum
- `app/models/__init__.py` - Export ContentSource and ContentSourceType
- `alembic/env.py` - Import ContentSource for migrations
- `Makefile` - Added `make test-content-sources` command

### Database Table Created:
```sql
CREATE TABLE content_sources (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type VARCHAR NOT NULL,  -- CHECK: 'youtube', 'reddit', 'blog'
    source_identifier VARCHAR(255) NOT NULL,  -- Platform-specific ID/URL
    display_name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_fetched_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX ix_content_sources_user_id ON content_sources(user_id);
CREATE INDEX ix_content_sources_source_type ON content_sources(source_type);
```

---

## Key Concepts Learned

### 1. **One-to-Many Relationships**

**What's Different from One-to-One?**

**One-to-One** (User ←→ UserPreferences):
```python
# User side
preferences: Mapped["UserPreferences"] = relationship(uselist=False)
# Returns single object

# Usage
user.preferences.update_frequency  # Single object
```

**One-to-Many** (User ←→ ContentSource):
```python
# User side
content_sources: Mapped[list["ContentSource"]] = relationship()
# Returns list of objects

# Usage
for source in user.content_sources:  # List of objects
    print(source.display_name)
```

### 2. **Lazy Loading Strategies**

**Different strategies for different relationships:**

**`lazy="joined"`** - For One-to-One:
```python
# Good for: One-to-one relationships
preferences: Mapped["UserPreferences"] = relationship(lazy="joined")

# What happens:
user = await db.get(User, 1)  # 1 query with JOIN
# SELECT users.*, user_preferences.* FROM users 
# LEFT JOIN user_preferences ON ...

# Result: Everything in one query ✅
```

**`lazy="selectin"`** - For One-to-Many:
```python
# Good for: One-to-many relationships
content_sources: Mapped[list["ContentSource"]] = relationship(lazy="selectin")

# What happens:
user = await db.get(User, 1)  # 2 separate queries
# Query 1: SELECT * FROM users WHERE id = 1
# Query 2: SELECT * FROM content_sources WHERE user_id IN (1)

# Result: Clean, separate queries ✅
```

**Why not `lazy="joined"` for one-to-many?**
```python
# Problem: Cartesian product!
# If user has 10 sources:
# Returns 10 rows with DUPLICATED user data
# Wastes memory and bandwidth ❌
```

### 3. **Indexes for Query Performance**

**Why index `user_id`?**
```python
user_id: Mapped[int] = mapped_column(
    ForeignKey("users.id"),
    index=True  # ← Makes queries FAST
)

# Fast query:
sources = await db.execute(
    select(ContentSource).where(ContentSource.user_id == 123)
)
# With index: 2ms ✅
# Without index: 500ms ❌
```

**Why index `source_type`?**
```python
source_type: Mapped[ContentSourceType] = mapped_column(
    index=True  # ← Fast filtering by type
)

# Fast query:
youtube_sources = await db.execute(
    select(ContentSource)
    .where(ContentSource.source_type == ContentSourceType.YOUTUBE)
)
# Index makes this query fast even with 1000s of sources
```

### 4. **Cascade Delete**

**How Cascade Works:**
```python
# In ContentSource:
user_id: Mapped[int] = mapped_column(
    ForeignKey("users.id", ondelete="CASCADE")
)

# In User:
content_sources: Mapped[list["ContentSource"]] = relationship(
    cascade="all, delete-orphan"
)

# What happens:
await db.delete(user)
await db.commit()
# ✓ User deleted from users table
# ✓ All user's sources deleted from content_sources table
# ✓ No orphaned records
```

**Two levels of cascade:**
1. **Database level** (`ondelete="CASCADE"` in ForeignKey)
2. **ORM level** (`cascade="all, delete-orphan"` in relationship)

Both work together for data integrity.

### 5. **Enum for Type Safety**

**ContentSourceType Enum:**
```python
class ContentSourceType(str, enum.Enum):
    YOUTUBE = "youtube"
    REDDIT = "reddit"
    BLOG = "blog"

# Benefits:
source.source_type = ContentSourceType.YOUTUBE  # ✅ Valid
source.source_type = "youtube"  # ✅ Valid (auto-converts)
source.source_type = "twitter"  # ❌ Error!
```

**Database Constraint:**
```sql
CREATE TABLE content_sources (
    ...
    source_type VARCHAR CHECK (source_type IN ('youtube', 'reddit', 'blog'))
);
```

Both Python AND database enforce valid values!

---

## Database Schema Visualization

```
┌─────────────────────────────────┐
│           users                  │
├─────────────────────────────────┤
│ id (PK)          SERIAL          │
│ email            VARCHAR UNIQUE  │
│ name             VARCHAR         │
│ ...                              │
└─────────────────────────────────┘
         │
         │ One-to-Many
         │
         ▼
┌─────────────────────────────────┐
│      content_sources             │
├─────────────────────────────────┤
│ id (PK)          SERIAL          │
│ user_id (FK)     INTEGER         │◄─── Links to users.id
│ source_type      ENUM            │◄─── youtube, reddit, blog
│ source_identifier VARCHAR        │◄─── Platform-specific ID
│ display_name     VARCHAR         │◄─── "Fireship", "r/programming"
│ is_active        BOOLEAN         │◄─── Can pause sources
│ last_fetched_at  TIMESTAMP       │◄─── Track fetch times
│ created_at       TIMESTAMP       │
│ updated_at       TIMESTAMP       │
└─────────────────────────────────┘
```

**Indexes:**
- `ix_content_sources_user_id` - Fast queries by user
- `ix_content_sources_source_type` - Fast queries by type

---

## Common Usage Patterns

### Add Content Sources

```python
from app.models import ContentSource, ContentSourceType

# Add YouTube channel
youtube = ContentSource(
    user_id=user.id,
    source_type=ContentSourceType.YOUTUBE,
    source_identifier="UCsBjURrPoezykLs9EqgamOA",  # Channel ID
    display_name="Fireship"
)
db.add(youtube)

# Add Reddit subreddit
reddit = ContentSource(
    user_id=user.id,
    source_type=ContentSourceType.REDDIT,
    source_identifier="programming",  # Subreddit name (no r/)
    display_name="r/programming"
)
db.add(reddit)

# Add Blog/RSS feed
blog = ContentSource(
    user_id=user.id,
    source_type=ContentSourceType.BLOG,
    source_identifier="https://blog.example.com/feed.xml",  # Feed URL
    display_name="Example Tech Blog"
)
db.add(blog)

await db.commit()
```

### Query User's Sources

```python
# Get all user's sources
user = await db.get(User, user_id)
for source in user.content_sources:
    print(f"{source.display_name} ({source.source_type.value})")

# Get only active sources
active_sources = [s for s in user.content_sources if s.is_active]

# Get by type
youtube_sources = [
    s for s in user.content_sources 
    if s.source_type == ContentSourceType.YOUTUBE
]
```

### Query by Source Type

```python
# All YouTube sources for a user
result = await db.execute(
    select(ContentSource)
    .where(
        ContentSource.user_id == user_id,
        ContentSource.source_type == ContentSourceType.YOUTUBE
    )
)
youtube_sources = result.scalars().all()

# All active Reddit sources
result = await db.execute(
    select(ContentSource)
    .where(
        ContentSource.source_type == ContentSourceType.REDDIT,
        ContentSource.is_active == True
    )
)
reddit_sources = result.scalars().all()
```

### Update Source

```python
from datetime import datetime, timezone

# Update last fetched time
source.last_fetched_at = datetime.now(timezone.utc)
await db.commit()

# Deactivate source (pause)
source.is_active = False
await db.commit()

# Reactivate source
source.is_active = True
await db.commit()
```

---

## Testing

### Run the Test Suite

```bash
# Test ContentSource model
make test-content-sources

# Or directly:
docker compose exec api python test_content_source_model.py

# Expected output:
# ✓ Created user with 3 content sources
# ✓ Queried sources via relationship
# ✓ Queried by source type
# ✓ Updated source data
# ✓ Deactivated source
# ✓ Cascade delete worked
# ✅ All Tests Passed!
```

### What the Tests Verify

1. ✓ Create user with multiple sources (YouTube, Reddit, Blog)
2. ✓ Query sources via relationship (`user.content_sources`)
3. ✓ Query by source type (using index)
4. ✓ Update source (last_fetched_at, display_name)
5. ✓ Activate/deactivate sources
6. ✓ Cascade delete (user → sources)
7. ✓ Enum validation (only valid types)

---

## Migration Management

### Current Migration History

```bash
docker compose exec api alembic history

# Output:
# <base> -> b599d122034a, add users and user_preferences tables
# b599d122034a -> 0ea0f3dafa56, update timestamps to timezone-aware
# 0ea0f3dafa56 -> 91a2e5c46f1c, update last_login to timezone-aware
# 91a2e5c46f1c -> 0b0b03ab19f5, add content_sources table (current)
```

---

## Platform-Specific Identifiers

### YouTube

**What we store:**
- **Channel ID**: `"UCsBjURrPoezykLs9EqgamOA"`

**How to get it:**
1. Use YouTube Data API: `channels.list()`
2. Or extract from channel URL
3. Channel ID is unique per channel

**Example:**
```python
source_identifier = "UCsBjURrPoezykLs9EqgamOA"  # Fireship channel
```

### Reddit

**What we store:**
- **Subreddit name**: `"programming"` (without `r/`)

**Rules:**
- Case-insensitive
- No spaces
- Letters, numbers, underscores only
- No `r/` prefix in database

**Example:**
```python
source_identifier = "programming"  # r/programming subreddit
```

### Blog/RSS

**What we store:**
- **Feed URL**: `"https://blog.example.com/feed.xml"`

**Formats supported:**
- RSS 2.0
- Atom
- RSS 1.0 (RDF)

**Example:**
```python
source_identifier = "https://blog.example.com/feed.xml"
```

---

## Next Steps

**Sub-Task 2.4: Add Unique Constraint** (Optional Enhancement)

We could add a unique constraint to prevent duplicate sources:
```python
__table_args__ = (
    UniqueConstraint('user_id', 'source_type', 'source_identifier', 
                     name='uq_user_source'),
)
```

This would prevent a user from adding the same YouTube channel twice.

**Future Sub-Tasks:**

- **ContentItem Model** - Store actual content (videos, posts, articles)
- **Summary Model** - Store generated summaries
- **Conversation Model** - Store RAG chat history

---

## Key Takeaways

✅ **ContentSource model** supports three platform types

✅ **One-to-many relationship** with User works perfectly

✅ **Indexes** on `user_id` and `source_type` for fast queries

✅ **`lazy="selectin"`** for efficient one-to-many loading

✅ **Cascade delete** keeps database clean

✅ **Enum validation** ensures only valid source types

✅ **Timezone-aware timestamps** for `last_fetched_at`

✅ **Active/inactive status** allows pausing sources

✅ **Platform-specific identifiers** handle different platforms

---

## Troubleshooting

### Issue: "duplicate key value violates unique constraint"

**Problem:** Trying to add the same source twice

**Solution:** Check if source exists first:
```python
result = await db.execute(
    select(ContentSource).where(
        ContentSource.user_id == user_id,
        ContentSource.source_type == ContentSourceType.YOUTUBE,
        ContentSource.source_identifier == channel_id
    )
)
existing = result.scalar_one_or_none()

if existing:
    print("Source already exists")
else:
    # Create new source
    source = ContentSource(...)
```

### Issue: "foreign key constraint violation"

**Problem:** Trying to create source for non-existent user

**Solution:** Always verify user exists:
```python
user = await db.get(User, user_id)
if not user:
    raise ValueError("User not found")

# Now create source
source = ContentSource(user_id=user.id, ...)
```

---

## Database Commands

### View Sources

```bash
docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT id, user_id, source_type, display_name, is_active FROM content_sources;"
```

### Count Sources by Type

```bash
docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT source_type, COUNT(*) FROM content_sources GROUP BY source_type;"
```

### View User's Sources

```bash
docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT display_name, source_type FROM content_sources WHERE user_id = 1;"
```

---

## Questions & Answers

**Q: Why use `lazy="selectin"` instead of `lazy="joined"`?**

**A:** For one-to-many relationships, `selectin` is better:
- **`joined`**: Creates cartesian product (duplicate rows)
- **`selectin`**: Two clean queries
- **Result**: Better performance, cleaner data

**Q: Can a user have multiple sources of the same type?**

**A:** Yes! A user can follow:
- Multiple YouTube channels
- Multiple Reddit subreddits
- Multiple blogs

Each is a separate ContentSource record.

**Q: What happens if I delete a source?**

**A:** 
1. **Soft delete**: Set `is_active = False` (recommended)
2. **Hard delete**: `await db.delete(source)` (permanent)

Soft delete preserves history and allows reactivation.

**Q: How do I prevent duplicate sources?**

**A:** Check before adding:
```python
existing = await db.execute(
    select(ContentSource).where(
        ContentSource.user_id == user_id,
        ContentSource.source_identifier == identifier
    )
)
if existing.scalar_one_or_none():
    raise ValueError("Source already exists")
```

**Q: Can I change source_type after creation?**

**A:** Technically yes, but **not recommended**:
- Changes the meaning of `source_identifier`
- Better to delete and create new source

---

**Status:** ✅ Sub-Task 2.3 Complete

**Next:** Sub-Task 2.4 or Stage 2 Task 3 (Authentication)

**Your Learning:** You now understand:
- One-to-many relationships vs one-to-one
- Lazy loading strategies (`joined` vs `selectin`)
- Indexes for query performance
- Cascade delete at multiple levels
- Platform-specific data modeling
- Enum validation for type safety

**Excellent progress! Your database foundation is solid!** 🎉
