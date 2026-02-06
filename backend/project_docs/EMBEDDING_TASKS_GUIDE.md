# RAG Embedding Tasks - Usage Guide

**Date:** November 19, 2025  
**Purpose:** Guide for using and monitoring RAG embedding Celery tasks

---

## 📋 Overview

This guide explains how to work with the RAG embedding pipeline that automatically processes content for semantic search and retrieval.

## 🔄 Automated Processing Flow

### 1. Content Collection (Existing)
```
YouTube/Reddit/Blog Tasks → ContentItem (status: PROCESSED)
```

### 2. Automatic Chunking & Embedding (New)
```
process_all_unprocessed_content (every 5 min)
    ↓
Finds ContentItems without chunks
    ↓
Queues process_content_item for each
    ↓
Chunks content + Generates embeddings
    ↓
Creates ContentChunk records (status: PROCESSED)
```

### 3. Retry & Maintenance
```
batch_embed_pending (every 10 min) → Process pending chunks
reprocess_failed_chunks (every 2 hours) → Retry failed embeddings
cleanup_orphaned_chunks (daily at 3 AM) → Remove orphans
```

---

## 🎯 Manual Task Execution

### Process a Single Content Item

```python
from app.tasks.embedding_tasks import process_content_item

# Process content item by ID
result = process_content_item.apply_async(args=[123])

# Wait for result
task_result = result.get(timeout=300)  # 5 minute timeout
print(task_result)
```

**Expected Output:**
```python
{
    'success': True,
    'content_item_id': 123,
    'title': 'Introduction to Python',
    'chunks_created': 5,
    'chunks_embedded': 5,
    'processing_time_seconds': 12.34
}
```

### Batch Process Pending Chunks

```python
from app.tasks.embedding_tasks import batch_embed_pending

# Process up to 20 pending chunks
result = batch_embed_pending.apply_async(args=[20])

# With content type filter
result = batch_embed_pending.apply_async(
    kwargs={'batch_size': 20, 'content_type': 'youtube'}
)
```

### Retry Failed Chunks

```python
from app.tasks.embedding_tasks import reprocess_failed_chunks

# Retry up to 50 failed chunks
result = reprocess_failed_chunks.apply_async(args=[50])
```

### Process All Unprocessed Content

```python
from app.tasks.embedding_tasks import process_all_unprocessed_content

# Find and queue all unprocessed content
result = process_all_unprocessed_content.apply_async()
```

### Get Processing Statistics

```python
from app.tasks.embedding_tasks import get_processing_stats

# Get current stats
result = get_processing_stats.apply_async()
stats = result.get()

print(f"Content items: {stats['content_items']}")
print(f"Chunks: {stats['chunks']}")
```

---

## 🔍 Monitoring

### Check Task Status

```bash
# Using Flower (Celery monitoring tool)
# Access: http://localhost:5555

# Or via Celery CLI
celery -A app.workers.celery_app inspect active
celery -A app.workers.celery_app inspect scheduled
```

### Check Processing Stats

```python
# In Python shell or Jupyter notebook
from app.tasks.embedding_tasks import get_processing_stats
import asyncio

stats = asyncio.run(get_processing_stats())
print(stats)
```

**Example Output:**
```python
{
    'content_items': {
        'total': 150,
        'with_chunks': 120,
        'without_chunks': 30
    },
    'chunks': {
        'total': 850,
        'pending': 15,
        'processing': 2,
        'processed': 820,
        'failed': 13
    }
}
```

### Database Queries

```sql
-- Count content items without chunks
SELECT COUNT(*) 
FROM content_items ci
WHERE NOT EXISTS (
    SELECT 1 FROM content_chunks cc 
    WHERE cc.content_item_id = ci.id
)
AND ci.processing_status = 'processed';

-- Count chunks by status
SELECT processing_status, COUNT(*) 
FROM content_chunks 
GROUP BY processing_status;

-- Find failed chunks
SELECT cc.*, ci.title
FROM content_chunks cc
JOIN content_items ci ON cc.content_item_id = ci.id
WHERE cc.processing_status = 'failed'
ORDER BY cc.created_at DESC
LIMIT 10;

-- Check embedding quality
SELECT 
    ci.title,
    COUNT(cc.id) as chunk_count,
    AVG(array_length(cc.embedding, 1)) as avg_embedding_dim
FROM content_chunks cc
JOIN content_items ci ON cc.content_item_id = ci.id
WHERE cc.embedding IS NOT NULL
GROUP BY ci.id, ci.title
ORDER BY chunk_count DESC
LIMIT 10;
```

---

## ⚙️ Configuration

### Environment Variables

```bash
# Chunking Configuration
CHUNK_SIZE_TOKENS=800
CHUNK_OVERLAP_TOKENS=100
MAX_CHUNKS_PER_CONTENT=50

# Embedding Configuration
EMBEDDING_MODEL="ibm-granite/granite-embedding-107m-multilingual"
EMBEDDING_DIMENSION=384
EMBEDDING_BATCH_SIZE=32
EMBEDDING_DEVICE="cpu"  # or "cuda" or "mps"
```

### Celery Beat Schedule

**File:** `app/workers/celery_app.py`

```python
# Current schedules
'process-unprocessed-content': Every 5 minutes
'batch-embed-pending': Every 10 minutes
'reprocess-failed-chunks': Every 2 hours
'cleanup-orphaned-chunks': Daily at 3 AM
'get-embedding-stats': Every 15 minutes
```

**To Adjust Frequency:**
```python
# In celery_app.py
'process-unprocessed-content': {
    'task': 'embedding.process_all_unprocessed_content',
    'schedule': crontab(minute='*/2'),  # Change to every 2 minutes
    'options': {'queue': 'embedding'},
}
```

---

## 🐛 Troubleshooting

### Issue: Chunks Not Being Created

**Check:**
1. Is content item status PROCESSED?
   ```sql
   SELECT id, title, processing_status FROM content_items WHERE id = 123;
   ```

2. Does content have sufficient body?
   ```sql
   SELECT length(content_body) FROM content_items WHERE id = 123;
   -- Should be > 100 characters
   ```

3. Are there existing chunks?
   ```sql
   SELECT COUNT(*) FROM content_chunks WHERE content_item_id = 123;
   ```

**Fix:**
```python
# Manually trigger processing
from app.tasks.embedding_tasks import process_content_item
process_content_item.apply_async(args=[123])
```

### Issue: Embeddings Failing

**Check:**
1. Is embedding service initialized?
   ```python
   from app.services.processors.embedder import get_embedding_service
   import asyncio
   
   async def test():
       embedder = await get_embedding_service()
       result = await embedder.embed_text("test")
       print(f"Embedding shape: {result.shape}")
   
   asyncio.run(test())
   ```

2. Check Celery logs:
   ```bash
   docker-compose logs -f celery-worker
   ```

3. Check for failed chunks:
   ```sql
   SELECT id, chunk_text, created_at 
   FROM content_chunks 
   WHERE processing_status = 'failed' 
   ORDER BY created_at DESC 
   LIMIT 5;
   ```

**Fix:**
```python
# Retry specific chunk
from app.tasks.embedding_tasks import reprocess_failed_chunks
reprocess_failed_chunks.apply_async(args=[10])
```

### Issue: Memory Issues with Embeddings

**Symptoms:**
- OOM errors in Celery worker
- Worker crashes during embedding

**Solutions:**

1. **Reduce Batch Size**
   ```python
   # In config.py
   EMBEDDING_BATCH_SIZE = 16  # Reduced from 32
   ```

2. **Use CPU Instead of GPU**
   ```python
   # In config.py
   EMBEDDING_DEVICE = "cpu"
   ```

3. **Process Smaller Batches in Tasks**
   ```python
   batch_embed_pending.apply_async(kwargs={'batch_size': 5})
   ```

4. **Increase Worker Memory**
   ```yaml
   # In docker-compose.yml
   celery-worker:
     deploy:
       resources:
         limits:
           memory: 4G
   ```

### Issue: Tasks Not Running Automatically

**Check:**
1. Is Celery Beat running?
   ```bash
   docker-compose ps celery-beat
   ```

2. Check Beat logs:
   ```bash
   docker-compose logs celery-beat
   ```

3. Verify schedule:
   ```python
   from app.workers.celery_app import celery_app
   print(celery_app.conf.beat_schedule)
   ```

**Fix:**
```bash
# Restart Celery Beat
docker-compose restart celery-beat
```

---

## 📊 Performance Optimization

### Parallel Processing

For large backlogs, process multiple content items in parallel:

```python
from app.tasks.embedding_tasks import process_content_item
from celery import group

# Get list of unprocessed content IDs
content_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

# Create parallel task group
job = group(
    process_content_item.s(content_id) 
    for content_id in content_ids
)

# Execute in parallel
result = job.apply_async()
```

### Monitoring Performance

```python
from app.tasks.embedding_tasks import get_processing_stats
import time

def monitor_processing(duration_minutes=10, interval_seconds=30):
    """Monitor processing for specified duration."""
    end_time = time.time() + (duration_minutes * 60)
    
    while time.time() < end_time:
        stats = get_processing_stats()
        
        print(f"\n--- Processing Stats ---")
        print(f"Items without chunks: {stats['content_items']['without_chunks']}")
        print(f"Pending chunks: {stats['chunks']['pending']}")
        print(f"Failed chunks: {stats['chunks']['failed']}")
        print(f"Processed chunks: {stats['chunks']['processed']}")
        
        time.sleep(interval_seconds)

# Run monitoring
monitor_processing(duration_minutes=10, interval_seconds=30)
```

---

## 🧪 Testing

### Run Embedding Task Tests

```bash
# Run all embedding task tests
pytest tests/tasks/test_embedding_tasks.py -v

# Run specific test
pytest tests/tasks/test_embedding_tasks.py::test_process_content_item_success -v

# Run with coverage
pytest tests/tasks/test_embedding_tasks.py --cov=app.tasks.embedding_tasks
```

### Integration Test

```python
"""
Integration test: Full pipeline from content to chunks
"""
import asyncio
from app.db.session import AsyncSessionLocal
from app.models.content import ContentItem, ContentChunk, ProcessingStatus
from app.tasks.embedding_tasks import process_content_item

async def test_full_pipeline():
    async with AsyncSessionLocal() as db:
        # Create test content
        content = ContentItem(
            channel_id=1,  # Assumes channel exists
            external_id="test_integration",
            title="Integration Test Video",
            content_body="This is a test video about integration testing. " * 50,
            processing_status=ProcessingStatus.PROCESSED
        )
        db.add(content)
        await db.commit()
        await db.refresh(content)
        
        print(f"Created content item: {content.id}")
        
        # Process it
        result = process_content_item(content.id)
        print(f"Processing result: {result}")
        
        # Verify chunks
        chunks = await db.execute(
            select(ContentChunk).where(
                ContentChunk.content_item_id == content.id
            )
        )
        chunks = chunks.scalars().all()
        
        print(f"Created {len(chunks)} chunks")
        for chunk in chunks:
            print(f"  - Chunk {chunk.chunk_index}: {len(chunk.chunk_text)} chars, "
                  f"status={chunk.processing_status}, "
                  f"has_embedding={chunk.embedding is not None}")
        
        assert len(chunks) > 0
        assert all(c.processing_status == ProcessingStatus.PROCESSED for c in chunks)
        assert all(c.embedding is not None for c in chunks)
        
        print("✅ Integration test passed!")

# Run test
asyncio.run(test_full_pipeline())
```

---

## 📚 Additional Resources

- **RAG Progress Doc:** `TASK_7_RAG_PROGRESS.md`
- **RAG Plan:** `.cursor/plans/rag-system-implementation-cc76b8c8.plan.md`
- **Embedding Service:** `app/services/processors/embedder.py`
- **Chunker Service:** `app/services/processors/chunker.py`
- **Task Implementation:** `app/tasks/embedding_tasks.py`

---

## 🎯 Quick Reference

```bash
# Monitor tasks
docker-compose logs -f celery-worker

# Check Flower
open http://localhost:5555

# Run tests
pytest tests/tasks/test_embedding_tasks.py -v

# Database stats
psql -U keemu -d keemu -c "SELECT processing_status, COUNT(*) FROM content_chunks GROUP BY processing_status;"

# Process specific content
python -c "from app.tasks.embedding_tasks import process_content_item; process_content_item.apply_async(args=[123])"

# Get stats
python -c "from app.tasks.embedding_tasks import get_processing_stats; import asyncio; print(asyncio.run(get_processing_stats()))"
```

