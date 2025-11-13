# Task 4.3: Celery Tasks for YouTube Content Fetching

## Overview

This document describes the implementation of background tasks for automatically fetching and processing YouTube content. The Celery task system enables asynchronous, scheduled content updates from subscribed YouTube channels.

## Architecture

### Task Flow

```
User Subscribes → fetch_youtube_channel_content
                    ↓
            ContentItems Created (PENDING)
                    ↓
        process_youtube_video (foreach video)
                    ↓
        Fetch Details + Extract Transcript
                    ↓
            Update ContentItem (PROCESSED/FAILED)
```

### Periodic Updates

```
Celery Beat (every 6 hours)
    ↓
fetch_all_active_channels
    ↓
Finds channels needing update
    ↓
Queue fetch_youtube_channel_content tasks
    ↓
Individual channel processing
```

## Tasks

### 1. `fetch_youtube_channel_content`

**Purpose:** Fetch latest videos from a YouTube channel and create ContentItem records.

**Trigger:**
- Immediately after user subscribes (10 second delay)
- Manual refresh via API endpoint (5 second delay)
- Scheduled periodic updates (via `fetch_all_active_channels`)

**Task ID:** `youtube.fetch_channel_content`

**Parameters:**
- `channel_id` (int): Database ID of the Channel

**Returns:**
```python
{
    'success': True,
    'channel_id': 123,
    'channel_name': 'Example Channel',
    'videos_found': 50,  # Total videos from YouTube
    'new_videos': 5,     # New videos we didn't have
    'processing_tasks': ['task-id-1', 'task-id-2', ...],
    'last_fetched_at': '2024-01-15T10:00:00+00:00'
}
```

**Behavior:**
1. Fetches channel from database
2. Calls YouTube API to get recent videos (published after `last_fetched_at`)
3. Filters out videos that already exist in database
4. Creates ContentItem records with `status=PENDING`
5. Queues `process_youtube_video` task for each new video
6. Updates channel's `last_fetched_at` timestamp

**Error Handling:**
- Returns error if channel not found
- Raises `YouTubeAPIError` for API failures (triggers retry)
- Raises `YouTubeQuotaExceededError` for quota issues (triggers retry)
- Max 3 retries with exponential backoff

**Example Usage:**
```python
# Queue immediate fetch
from app.tasks.youtube_tasks import fetch_youtube_channel_content

result = fetch_youtube_channel_content.apply_async(
    args=[channel_id],
    countdown=10  # Wait 10 seconds
)
```

---

### 2. `process_youtube_video`

**Purpose:** Process a single video - fetch full details and extract transcript.

**Trigger:**
- Automatically queued by `fetch_youtube_channel_content` for new videos

**Task ID:** `youtube.process_video`

**Parameters:**
- `content_item_id` (int): Database ID of the ContentItem

**Returns:**
```python
{
    'success': True,
    'content_item_id': 456,
    'video_id': 'dQw4w9WgXcQ',
    'title': 'Example Video',
    'transcript_length': 5432,
    'transcript_language': 'en',
    'transcript_type': 'auto'
}
```

**Behavior:**
1. Updates ContentItem status to `PROCESSING`
2. Fetches video details from YouTube (views, likes, duration, etc.)
3. Extracts transcript using `TranscriptService`
4. Updates ContentItem with:
   - Full transcript text in `content_body`
   - Video metadata in `content_metadata` (duration, views, likes, etc.)
   - Transcript quality score
   - Processing timestamp
5. Sets status to `PROCESSED` on success or `FAILED` on error

**Error Handling:**
- Sets status to `FAILED` if no transcript available
- Sets status to `FAILED` on YouTube API errors
- Stores error message in ContentItem for debugging
- Max 3 retries with exponential backoff

**Example ContentItem After Processing:**
```python
ContentItem(
    id=456,
    channel_id=123,
    external_id='dQw4w9WgXcQ',
    title='Example Video',
    content_body='Full transcript text here...',
    processing_status=ProcessingStatus.PROCESSED,
    content_metadata={
        'video_id': 'dQw4w9WgXcQ',
        'duration_seconds': 600,
        'duration_formatted': '10:00',
        'view_count': 1000000,
        'like_count': 50000,
        'comment_count': 2000,
        'thumbnail_url': 'https://...',
        'tags': ['music', 'dance'],
        'definition': 'hd',
        'has_captions': True,
        'transcript_language': 'en',
        'transcript_type': 'auto',
        'transcript_quality': 0.85,
        'processed_at': '2024-01-15T10:05:00Z'
    }
)
```

---

### 3. `fetch_all_active_channels`

**Purpose:** Periodic task that fetches content from all active YouTube channels.

**Trigger:**
- Scheduled by Celery Beat every 6 hours (configurable via `YOUTUBE_CHECK_INTERVAL_HOURS`)

**Task ID:** `youtube.fetch_all_active_channels`

**Parameters:** None

**Returns:**
```python
{
    'success': True,
    'total_channels': 50,      # Total active YouTube channels
    'channels_queued': 12,     # Channels that needed updating
    'task_ids': ['task-1', 'task-2', ...],
    'cutoff_time': '2024-01-15T04:00:00+00:00'
}
```

**Behavior:**
1. Queries all Channel records where:
   - `source_type = YOUTUBE`
   - `is_active = True`
2. Filters channels where:
   - `last_fetched_at` is NULL, OR
   - `last_fetched_at < (now - YOUTUBE_CHECK_INTERVAL_HOURS)`
3. Queues `fetch_youtube_channel_content` for each channel (with 5 second stagger)

**Celery Beat Schedule:**
```python
'fetch-youtube-content': {
    'task': 'youtube.fetch_all_active_channels',
    'schedule': crontab(minute='0', hour='*/6'),  # Every 6 hours
    'options': {'queue': 'youtube'},
}
```

---

### 4. `refresh_channel_metadata`

**Purpose:** Refresh channel information from YouTube (name, description, thumbnail).

**Trigger:**
- Called manually via admin tools or automated maintenance tasks

**Task ID:** `youtube.refresh_channel_metadata`

**Parameters:**
- `channel_id` (int): Database ID of the Channel

**Returns:**
```python
{
    'success': True,
    'channel_id': 123,
    'channel_name': 'Updated Channel Name',
    'youtube_subscriber_count': 1000000
}
```

**Behavior:**
1. Fetches channel from database
2. Calls YouTube API for channel metadata
3. Updates:
   - `name` (channel title)
   - `description`
   - `thumbnail_url`
4. Does NOT update `subscriber_count` (we track our own internal subscribers)

---

### 5. `get_processing_stats`

**Purpose:** Monitoring task to get statistics about content processing.

**Trigger:**
- Scheduled by Celery Beat every 15 minutes

**Task ID:** `youtube.get_processing_stats`

**Parameters:** None

**Returns:**
```python
{
    'pending': 10,
    'processing': 5,
    'processed': 1000,
    'failed': 15,
    'total': 1030
}
```

**Celery Beat Schedule:**
```python
'get-processing-stats': {
    'task': 'youtube.get_processing_stats',
    'schedule': crontab(minute='*/15'),  # Every 15 minutes
    'options': {'queue': 'monitoring'},
}
```

## Configuration

### Environment Variables

```bash
# How often to check for new content (hours)
YOUTUBE_CHECK_INTERVAL_HOURS=6

# Maximum videos to fetch per channel update
YOUTUBE_MAX_VIDEOS_PER_FETCH=50

# YouTube API settings
YOUTUBE_API_KEY=your_api_key_here
YOUTUBE_REQUEST_TIMEOUT=30
YOUTUBE_RETRY_ATTEMPTS=3
```

### Celery Configuration

**Task Routes:**
```python
{
    'youtube.*': {'queue': 'youtube'},
    'reddit.*': {'queue': 'reddit'},
    'blog.*': {'queue': 'blog'},
}
```

**Task Time Limits:**
- Hard limit: 30 minutes
- Soft limit: 25 minutes

**Retry Configuration:**
- Max retries: 3
- Backoff: Exponential with jitter
- Max backoff: 10 minutes

## Database Schema

### ContentItem Processing Status

```python
class ProcessingStatus(str, Enum):
    PENDING = "pending"         # Created, awaiting processing
    PROCESSING = "processing"   # Currently being processed
    PROCESSED = "processed"     # Successfully processed
    FAILED = "failed"           # Processing failed
```

### Tracking Fields

```python
class Channel(Base):
    last_fetched_at: datetime  # When we last fetched videos
    
class ContentItem(Base):
    processing_status: ProcessingStatus
    error_message: Optional[str]  # If FAILED, why?
    content_metadata: dict  # Video details, transcript metadata
```

## Monitoring

### Celery Flower

Access the Flower web UI at `http://localhost:5555` to monitor:
- Active tasks
- Task history
- Success/failure rates
- Task execution times
- Worker status

### Logs

```bash
# View Celery worker logs
docker compose logs -f celery_worker

# View Celery beat logs
docker compose logs -f celery_beat

# Search for specific task
docker compose logs celery_worker | grep "youtube.fetch_channel_content"
```

### Task Status Queries

```python
# Count by processing status
from app.models.content import ContentItem, ProcessingStatus
from sqlalchemy import func

stats = await db.execute(
    select(
        ContentItem.processing_status,
        func.count(ContentItem.id)
    )
    .group_by(ContentItem.processing_status)
)
```

## Quota Management

### YouTube API Quota

The YouTube Data API has a daily quota limit (default: 10,000 units/day).

**Cost per operation:**
- `search.list`: 100 units
- `videos.list`: 1 unit
- `channels.list`: 1 unit

**Estimated usage:**
```
For 50 channels with 50 videos each:
- 50 × 1 (channel details) = 50 units
- 50 × 50 (video details) = 2,500 units
Total: ~2,550 units per full fetch cycle
```

**Best practices:**
- Monitor quota usage via YouTube API Console
- Increase `YOUTUBE_CHECK_INTERVAL_HOURS` if approaching limits
- Reduce `YOUTUBE_MAX_VIDEOS_PER_FETCH` for high-volume channels
- Implement quota exceeded retry with longer backoff

## Testing

### Unit Tests

```bash
# Run YouTube task tests
docker compose exec api pytest tests/tasks/test_youtube_tasks.py -v

# Run with coverage
docker compose exec api pytest tests/tasks/ --cov=app.tasks --cov-report=html
```

### Manual Testing

```bash
# Trigger a channel fetch
docker compose exec api python -c "
from app.tasks.youtube_tasks import fetch_youtube_channel_content
result = fetch_youtube_channel_content.apply_async(args=[1])
print(f'Task ID: {result.id}')
"

# Check task result
docker compose exec api python -c "
from app.workers.celery_app import celery_app
result = celery_app.AsyncResult('task-id-here')
print(result.status)
print(result.result)
"
```

### Integration Testing

Test the full flow:
1. Subscribe to a channel via API
2. Verify `fetch_youtube_channel_content` task was queued
3. Wait for ContentItems to be created
4. Verify `process_youtube_video` tasks were queued
5. Check ContentItems are marked as PROCESSED
6. Verify content_body contains transcript

## Error Scenarios

### No Transcript Available

**Symptom:** ContentItem marked as FAILED with error "No transcript available"

**Cause:**
- Video has no captions/subtitles
- Transcripts disabled by uploader
- Very recent video (transcripts not yet generated)

**Resolution:**
- Expected behavior - not all videos have transcripts
- Consider filtering these out or marking differently
- Could retry after 24 hours for very recent videos

### YouTube Quota Exceeded

**Symptom:** Tasks failing with "YouTube API quota exceeded"

**Cause:**
- Daily API quota limit reached
- Too many channels or high fetch frequency

**Resolution:**
- Wait for quota to reset (midnight Pacific Time)
- Increase `YOUTUBE_CHECK_INTERVAL_HOURS`
- Reduce `YOUTUBE_MAX_VIDEOS_PER_FETCH`
- Consider upgrading API quota

### Channel Not Found

**Symptom:** Task returns error "Channel {id} not found"

**Cause:**
- Channel was deleted from database
- Race condition during deletion

**Resolution:**
- Check if Channel still exists before queuing tasks
- Add defensive checks in tasks
- Clean up orphaned subscriptions

## Performance Optimization

### Batch Processing

Current implementation processes videos sequentially. For high-volume channels:

```python
# Instead of queuing 50 individual tasks
for video in videos:
    process_youtube_video.apply_async(args=[video.id])

# Consider batching:
from celery import group
tasks = group(
    process_youtube_video.s(video.id) for video in videos
)
tasks.apply_async()
```

### Prioritization

Priority queue for high-value channels:

```python
# High priority for verified/popular channels
priority = 0 if channel.is_verified else 5
fetch_youtube_channel_content.apply_async(
    args=[channel.id],
    priority=priority
)
```

### Caching

Consider caching channel metadata to reduce API calls:

```python
# Cache channel info for 24 hours
cache_key = f"channel:{channel_id}:metadata"
cached_info = redis.get(cache_key)
if cached_info:
    return cached_info
```

## Future Enhancements

1. **Smart Scheduling:**
   - Fetch more frequently for active channels
   - Reduce frequency for inactive channels
   - Learn optimal fetch times based on upload patterns

2. **Webhook Support:**
   - Use YouTube PubSubHubbub for real-time updates
   - Eliminate polling delay
   - Reduce API quota usage

3. **Advanced Transcript Processing:**
   - Extract timestamps for key moments
   - Generate summaries using LLM
   - Identify topics/themes

4. **Better Failure Handling:**
   - Automatic retry for transient errors
   - Separate retry queues for different error types
   - Alert on persistent failures

5. **Content Deduplication:**
   - Detect duplicate content across channels
   - Handle re-uploads/reposts

## Dependencies

### Python Packages
- `celery>=5.0`: Task queue
- `redis>=5.0`: Message broker
- `google-api-python-client`: YouTube Data API
- `youtube-transcript-api`: Transcript extraction
- `isodate`: Duration parsing

### Services
- Redis: Message broker and result backend
- PostgreSQL: Data storage
- YouTube Data API: Content source

## API Integration

The Celery tasks are integrated with API endpoints:

### Subscribe Endpoint
```python
POST /api/v1/youtube/subscribe
# Triggers: fetch_youtube_channel_content (10s delay)
```

### Refresh Endpoint
```python
POST /api/v1/youtube/subscriptions/{id}/refresh
# Triggers: fetch_youtube_channel_content (5s delay)
# Returns: task_id for tracking
```

## Troubleshooting

### Tasks Not Running

```bash
# Check Celery worker is running
docker compose ps celery_worker

# Check worker logs
docker compose logs celery_worker

# Check if tasks are registered
docker compose exec api celery -A app.workers.celery_app inspect registered
```

### Tasks Stuck in PENDING

```bash
# Check Redis connection
docker compose exec redis redis-cli ping

# Check queue length
docker compose exec redis redis-cli llen celery

# Purge queue if needed
docker compose exec api celery -A app.workers.celery_app purge
```

### High Memory Usage

```bash
# Check worker memory
docker compose exec celery_worker ps aux

# Restart worker
docker compose restart celery_worker

# Adjust worker concurrency
# In docker-compose.yml:
# command: celery -A app.workers.celery_app worker -c 2 --loglevel=info
```

## Summary

The Celery task system provides:
- ✅ Automatic content fetching every 6 hours
- ✅ Immediate fetching on subscription
- ✅ Parallel video processing
- ✅ Robust error handling with retries
- ✅ Comprehensive monitoring via Flower
- ✅ Efficient quota management
- ✅ Scalable architecture

Next steps: Task 4.4 - Content Metadata & JSONB Storage
