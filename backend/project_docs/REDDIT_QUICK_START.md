# Reddit Integration - Quick Start Guide

## Overview

The Reddit integration allows users to subscribe to subreddits and automatically fetch high-quality posts with mature discussions using a smart two-stage fetching strategy.

## Key Features

- **Smart Fetching**: Two-stage strategy ensures posts have developed discussions
- **Engagement Filters**: Configurable thresholds (min_score, min_comments, min_age)
- **Quota Management**: Redis-based tracking prevents API rate limiting
- **JSONB Queries**: Advanced content filtering using PostgreSQL
- **RESTful API**: 10 endpoints for complete subscription management

## Quick Start

### 1. Environment Setup

Add to `.env`:
```bash
REDDIT_CLIENT_ID=your-reddit-client-id
REDDIT_CLIENT_SECRET=your-reddit-client-secret
REDDIT_USER_AGENT=KeeMU:v1.0 (by /u/your_username)
```

### 2. API Endpoints

#### Search for a Subreddit
```bash
curl -X POST "http://localhost:8000/api/v1/reddit/search" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "python"}'
```

#### Subscribe to a Subreddit
```bash
curl -X POST "http://localhost:8000/api/v1/reddit/subscribe" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "subreddit_name": "python",
    "comment_limit": 20,
    "min_score": 10,
    "min_comments": 3,
    "notification_enabled": true
  }'
```

#### List Subscriptions
```bash
curl -X GET "http://localhost:8000/api/v1/reddit/subscriptions" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### Trigger Manual Refresh
```bash
curl -X POST "http://localhost:8000/api/v1/reddit/subscriptions/{id}/refresh" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 3. Configuration Options

**Per-Subscription Settings:**
- `comment_limit`: 5-50 comments per post (default: 20)
- `min_score`: Minimum upvotes (default: 10)
- `min_comments`: Minimum comment count (default: 3)
- `notification_enabled`: Enable/disable notifications

**System Settings (config.py):**
- Fetch frequency: Every 3 hours (smart strategy)
- Stage 2 delay: 6-12 hours (random)
- Quota limits: 55/min, 580/10min (with buffer)

## How It Works

### Smart Fetching Strategy

**Stage 1 - Discovery Fetch** (Every 3 hours):
1. Fetch hot + top posts from subreddit
2. Filter by:
   - Age ≥ 2 hours (mature posts)
   - Score ≥ min_score
   - Comments ≥ min_comments
3. Create ContentItem with PENDING status
4. Schedule Stage 2 processing (6-12 hour delay)

**Stage 2 - Comment Fetch** (After delay):
1. Re-fetch post (get updated scores)
2. Re-check engagement thresholds
3. Fetch top comments
4. Format post + comments
5. Calculate engagement score
6. Update ContentItem with PROCESSED status

### Engagement Score

Formula: `(upvotes × 0.6) + (comments × 0.3) + (awards × 0.1)`

Example:
- Post with 100 upvotes, 50 comments, 10 awards
- Score = (100 × 0.6) + (50 × 0.3) + (10 × 0.1) = 76

## Content Storage

### Content Body Format
```
Title: Understanding Python Decorators
Subreddit: r/python
Author: u/pythonista
Posted: 2025-10-25 12:00:00 UTC
Score: 156 | Comments: 42

[Post content here...]

--- Top Comments ---

[Comment 1 - Score: 45]
Author: u/commenter1
This is a great explanation...

[Comment 2 - Score: 32]
Author: u/commenter2
I would add that...
```

### Metadata (JSONB)
```json
{
  "post_id": "abc123",
  "subreddit": "python",
  "score": 156,
  "num_comments": 42,
  "upvote_ratio": 0.95,
  "engagement_score": 103.7,
  "is_self": true,
  "permalink": "/r/python/comments/abc123/...",
  "comments_fetched": 20,
  "top_comments": [...]
}
```

## JSONB Queries

### Get Popular Posts
```python
from app.services.content_query import ContentQueryService

query_service = ContentQueryService(db)
popular_posts = await query_service.get_popular_reddit_posts(
    user_id=user.id,
    min_score=100,
    days=7,
    limit=50
)
```

### Get Controversial Posts
```python
controversial = await query_service.get_controversial_posts(
    user_id=user.id,
    max_upvote_ratio=0.6,  # 60% or less upvoted
    min_score=20,
    days=7
)
```

### Get Posts by Subreddit
```python
python_posts = await query_service.get_posts_by_subreddit(
    user_id=user.id,
    subreddit_name="python",
    days=30
)
```

## Quota Monitoring

### Check Current Usage
```bash
curl -X GET "http://localhost:8000/api/v1/reddit/quota" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Response:
```json
{
  "minute_usage": 12,
  "minute_limit": 55,
  "minute_percentage": 21.8,
  "ten_min_usage": 85,
  "ten_min_limit": 580,
  "ten_min_percentage": 14.7,
  "can_make_request": true,
  "today_total": 1247,
  "today_by_operation": {
    "subreddit_fetch": 42,
    "posts_fetch": 756,
    "post_details": 124,
    "comments_fetch": 325
  }
}
```

### Get Quota History
```bash
curl -X GET "http://localhost:8000/api/v1/reddit/quota/history?days=7" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Celery Tasks

### Manual Trigger (Python)
```python
from app.tasks.reddit_tasks import fetch_reddit_subreddit_content

# Trigger fetch for a channel
task = fetch_reddit_subreddit_content.delay(channel_id=123)
print(f"Task ID: {task.id}")
```

### Monitor Task Status
```python
from celery.result import AsyncResult

result = AsyncResult(task_id)
print(f"Status: {result.status}")
print(f"Result: {result.result}")
```

## Troubleshooting

### Issue: Posts not being fetched

**Check:**
1. Subreddit exists and is public
2. Posts meet engagement thresholds
3. Celery Beat is running: `celery -A app.workers.celery_app beat --loglevel=info`
4. Celery worker is running: `celery -A app.workers.celery_app worker --loglevel=info -Q reddit`

**Debug:**
```bash
# Check last fetch time
SELECT last_checked_at FROM channels WHERE id = 123;

# Check pending posts
SELECT COUNT(*) FROM content_items 
WHERE channel_id = 123 AND processing_status = 'pending';
```

### Issue: Quota exceeded

**Check quota usage:**
```bash
# Via API
curl http://localhost:8000/api/v1/reddit/quota

# Via Redis
redis-cli GET reddit:quota:minute:2025-10-25-12-30
```

**Reset quota (admin only):**
```python
from app.services.reddit_quota_tracker import get_reddit_quota_tracker

tracker = get_reddit_quota_tracker()
await tracker.reset_quota()
```

### Issue: Comments not included

**Check:**
1. `comment_limit` setting in subscription
2. Post age (comments fetched in Stage 2, after 6-12 hours)
3. Post status (should be PROCESSED, not PENDING)

**Debug:**
```bash
# Check content item
SELECT processing_status, content_metadata->>'comments_fetched' 
FROM content_items WHERE id = 456;
```

## Performance Tips

1. **Adjust Thresholds**: Higher thresholds = fewer posts, better quality
2. **Monitor Quota**: Keep usage below 80% consistently
3. **Tune Delays**: Adjust 6-12 hour window based on subreddit activity
4. **Add Indexes**: Create JSONB GIN indexes for frequently queried fields

## Next Steps

1. **Test Integration**: Subscribe to a subreddit and wait for content
2. **Monitor Quota**: Check `/quota` endpoint regularly
3. **Adjust Settings**: Fine-tune thresholds based on results
4. **Review Content**: Verify post quality and comment depth
5. **Integrate with RAG**: Use formatted content for retrieval

## Support

- **Documentation**: `project_docs/TASK_5_COMPLETE.md`
- **Code Examples**: Unit tests in `tests/test_services/test_reddit.py`
- **API Docs**: http://localhost:8000/docs (when running)

---

**Quick Start Complete!** 🎉

For detailed implementation information, see `TASK_5_COMPLETE.md`.





