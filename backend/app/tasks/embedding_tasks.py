"""
Celery tasks for RAG content processing (chunking and embedding).

This module contains background tasks for:
- Chunking content items into smaller pieces
- Generating embeddings for chunks
- Processing existing content for RAG
- Retrying failed embeddings
- Monitoring processing status
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from celery import Task
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.content import ContentItem, ContentChunk, ProcessingStatus, ContentSourceType
from app.services.processors.chunker import ContentChunker
from app.services.processors.embedder import get_embedding_service, EmbeddingService
from app.services.processors.text_search import TextSearchService
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# ========================================
# Async Helper
# ========================================

def run_async(coro):
    """
    Run async coroutine, handling both event loop and no event loop scenarios.
    
    This helper allows tasks to work in both:
    - Production (Celery worker with no event loop) - uses asyncio.run()
    - Tests (pytest with existing event loop) - runs in thread pool
    """
    try:
        # Try to get the current event loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running - we're in production Celery worker
        return asyncio.run(coro)
    else:
        # Event loop is running - we're probably in tests
        # Run in a new thread to avoid "loop already running" error
        import concurrent.futures
        import threading
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()


# ========================================
# Helper Functions
# ========================================

async def get_db() -> AsyncSession:
    """Get database session for async tasks."""
    async with AsyncSessionLocal() as session:
        return session


async def get_content_item_by_id(db: AsyncSession, content_item_id: int) -> Optional[ContentItem]:
    """Get content item by database ID."""
    result = await db.execute(
        select(ContentItem).where(ContentItem.id == content_item_id)
    )
    return result.scalar_one_or_none()


async def get_chunk_by_id(db: AsyncSession, chunk_id: int) -> Optional[ContentChunk]:
    """Get content chunk by database ID."""
    result = await db.execute(
        select(ContentChunk).where(ContentChunk.id == chunk_id)
    )
    return result.scalar_one_or_none()


async def count_chunks_by_status(db: AsyncSession, status: ProcessingStatus) -> int:
    """Count content chunks by processing status."""
    from sqlalchemy import func
    
    result = await db.execute(
        select(func.count(ContentChunk.id)).where(
            ContentChunk.processing_status == status
        )
    )
    return result.scalar() or 0


# ========================================
# Base Task Class
# ========================================

class EmbeddingTask(Task):
    """Base task class with retry logic and error handling."""
    
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes
    retry_jitter = True


# ========================================
# Main Tasks
# ========================================

@celery_app.task(
    base=EmbeddingTask,
    name='embedding.process_content_item',
    bind=True,
    max_retries=3
)
def process_content_item(self, content_item_id: int) -> dict:
    """
    Process a content item: chunk and embed for RAG.
    
    This task:
    1. Gets the ContentItem from database
    2. Chunks the content using appropriate strategy
    3. Generates embeddings for each chunk
    4. Generates text search vectors (tsvector)
    5. Stores ContentChunk records in database
    6. Updates ContentItem processing status
    
    Args:
        content_item_id: Database ID of the ContentItem
        
    Returns:
        Dictionary with processing results:
        {
            'success': bool,
            'content_item_id': int,
            'title': str,
            'chunks_created': int,
            'chunks_embedded': int,
            'processing_time_seconds': float
        }
    """
    import asyncio
    import time
    
    async def _process():
        start_time = time.time()
        
        async with AsyncSessionLocal() as db:
            try:
                # Get content item
                content_item = await get_content_item_by_id(db, content_item_id)
                if not content_item:
                    logger.error(f"ContentItem {content_item_id} not found")
                    return {
                        'success': False,
                        'error': f'ContentItem {content_item_id} not found'
                    }
                
                # Skip if already processed for embeddings
                # Check if chunks already exist
                existing_chunks = await db.execute(
                    select(ContentChunk).where(
                        ContentChunk.content_item_id == content_item_id
                    )
                )
                if existing_chunks.scalar_one_or_none():
                    logger.info(f"ContentItem {content_item_id} already has chunks, skipping")
                    return {
                        'success': True,
                        'content_item_id': content_item_id,
                        'message': 'Content already chunked',
                        'skipped': True
                    }
                
                logger.info(f"Processing content item: {content_item.title} (ID: {content_item_id})")
                
                # Check if content has body
                if not content_item.content_body or len(content_item.content_body.strip()) < 100:
                    logger.warning(f"ContentItem {content_item_id} has insufficient content body")
                    return {
                        'success': False,
                        'error': 'Insufficient content body (< 100 chars)',
                        'content_item_id': content_item_id
                    }
                
                # Step 1: Chunk the content
                chunker = ContentChunker()
                chunk_dicts = await chunker.chunk_content(content_item)
                
                logger.info(f"Created {len(chunk_dicts)} chunks for {content_item.title}")
                
                if not chunk_dicts:
                    logger.warning(f"No chunks created for ContentItem {content_item_id}")
                    return {
                        'success': False,
                        'error': 'No chunks created',
                        'content_item_id': content_item_id
                    }
                
                # Step 2: Initialize services
                embedder = await get_embedding_service()
                text_search = TextSearchService()
                
                # Step 3: Generate embeddings for all chunks
                chunk_texts = [chunk_dict['text'] for chunk_dict in chunk_dicts]
                embeddings = await embedder.embed_texts_batch(chunk_texts)
                
                logger.info(f"Generated {len(embeddings)} embeddings")
                
                # Step 4: Create ContentChunk records
                chunks_created = 0
                chunks_embedded = 0
                
                for i, chunk_dict in enumerate(chunk_dicts):
                    try:
                        # Create chunk record
                        chunk = ContentChunk(
                            content_item_id=content_item_id,
                            chunk_index=chunk_dict['index'],
                            chunk_text=chunk_dict['text'],
                            chunk_metadata=chunk_dict['metadata'],
                            embedding=embeddings[i].tolist() if embeddings[i] is not None else None,
                            processing_status=ProcessingStatus.PROCESSED if embeddings[i] is not None else ProcessingStatus.FAILED
                        )
                        
                        db.add(chunk)
                        chunks_created += 1
                        
                        if embeddings[i] is not None:
                            chunks_embedded += 1
                        
                    except Exception as e:
                        logger.error(f"Error creating chunk {i} for ContentItem {content_item_id}: {e}")
                        continue
                
                # Commit chunks
                await db.commit()
                
                logger.info(
                    f"Successfully processed ContentItem {content_item_id}: "
                    f"{chunks_created} chunks created, {chunks_embedded} embedded"
                )
                
                processing_time = time.time() - start_time
                
                return {
                    'success': True,
                    'content_item_id': content_item_id,
                    'title': content_item.title,
                    'chunks_created': chunks_created,
                    'chunks_embedded': chunks_embedded,
                    'processing_time_seconds': round(processing_time, 2)
                }
                
            except Exception as e:
                logger.error(f"Error processing ContentItem {content_item_id}: {e}", exc_info=True)
                await db.rollback()
                raise
    
    # Run async function
    return run_async(_process())


@celery_app.task(
    base=EmbeddingTask,
    name='embedding.batch_embed_pending',
    bind=True,
    max_retries=3
)
def batch_embed_pending(self, batch_size: int = 10, content_type: Optional[str] = None) -> dict:
    """
    Process pending content chunks in batches.
    
    This task:
    1. Finds chunks with status=PENDING (no embedding yet)
    2. Generates embeddings in batches
    3. Updates chunks with embeddings
    4. Updates processing status
    
    Args:
        batch_size: Number of chunks to process per batch (default: 10)
        content_type: Optional content type filter (youtube, reddit, blog)
        
    Returns:
        Dictionary with processing results
    """
    import asyncio
    
    async def _batch_process():
        async with AsyncSessionLocal() as db:
            try:
                # Build query for pending chunks
                query = select(ContentChunk).where(
                    ContentChunk.processing_status == ProcessingStatus.PENDING
                ).limit(batch_size)
                
                # Apply content type filter if specified
                if content_type:
                    query = query.join(ContentItem).where(
                        ContentItem.channel_id.in_(
                            select(ContentItem.channel_id).join(
                                ContentItem.channel
                            ).where(
                                ContentItem.channel.has(source_type=content_type)
                            )
                        )
                    )
                
                result = await db.execute(query)
                chunks = result.scalars().all()
                
                if not chunks:
                    logger.info("No pending chunks to process")
                    return {
                        'success': True,
                        'message': 'No pending chunks',
                        'chunks_processed': 0
                    }
                
                logger.info(f"Processing {len(chunks)} pending chunks")
                
                # Get embedding service
                embedder = await get_embedding_service()
                
                # Extract texts
                chunk_texts = [chunk.chunk_text for chunk in chunks]
                
                # Generate embeddings
                embeddings = await embedder.embed_texts_batch(chunk_texts)
                
                # Update chunks
                chunks_updated = 0
                for i, chunk in enumerate(chunks):
                    try:
                        if embeddings[i] is not None:
                            chunk.embedding = embeddings[i].tolist()
                            chunk.processing_status = ProcessingStatus.PROCESSED
                            chunks_updated += 1
                        else:
                            chunk.processing_status = ProcessingStatus.FAILED
                            logger.warning(f"Failed to embed chunk {chunk.id}")
                    except Exception as e:
                        logger.error(f"Error updating chunk {chunk.id}: {e}")
                        chunk.processing_status = ProcessingStatus.FAILED
                
                await db.commit()
                
                logger.info(f"Successfully processed {chunks_updated}/{len(chunks)} chunks")
                
                return {
                    'success': True,
                    'chunks_processed': chunks_updated,
                    'chunks_failed': len(chunks) - chunks_updated,
                    'total_chunks': len(chunks)
                }
                
            except Exception as e:
                logger.error(f"Error in batch_embed_pending: {e}", exc_info=True)
                await db.rollback()
                raise
    
    return run_async(_batch_process())


@celery_app.task(
    base=EmbeddingTask,
    name='embedding.reprocess_failed_chunks',
    bind=True,
    max_retries=2
)
def reprocess_failed_chunks(self, limit: int = 50) -> dict:
    """
    Retry embedding generation for failed chunks.
    
    This task:
    1. Finds chunks with status=FAILED
    2. Attempts to re-generate embeddings
    3. Updates chunk status
    
    Args:
        limit: Maximum number of failed chunks to retry (default: 50)
        
    Returns:
        Dictionary with retry results
    """
    import asyncio
    
    async def _reprocess():
        async with AsyncSessionLocal() as db:
            try:
                # Get failed chunks
                result = await db.execute(
                    select(ContentChunk)
                    .where(ContentChunk.processing_status == ProcessingStatus.FAILED)
                    .limit(limit)
                )
                chunks = result.scalars().all()
                
                if not chunks:
                    logger.info("No failed chunks to reprocess")
                    return {
                        'success': True,
                        'message': 'No failed chunks',
                        'chunks_reprocessed': 0
                    }
                
                logger.info(f"Reprocessing {len(chunks)} failed chunks")
                
                # Get embedding service
                embedder = await get_embedding_service()
                
                # Extract texts
                chunk_texts = [chunk.chunk_text for chunk in chunks]
                
                # Regenerate embeddings
                embeddings = await embedder.embed_texts_batch(chunk_texts)
                
                # Update chunks
                chunks_fixed = 0
                chunks_still_failed = 0
                
                for i, chunk in enumerate(chunks):
                    try:
                        if embeddings[i] is not None:
                            chunk.embedding = embeddings[i].tolist()
                            chunk.processing_status = ProcessingStatus.PROCESSED
                            chunks_fixed += 1
                            logger.info(f"Fixed chunk {chunk.id}")
                        else:
                            chunks_still_failed += 1
                            logger.warning(f"Chunk {chunk.id} still failed after retry")
                    except Exception as e:
                        logger.error(f"Error reprocessing chunk {chunk.id}: {e}")
                        chunks_still_failed += 1
                
                await db.commit()
                
                logger.info(
                    f"Reprocessing complete: {chunks_fixed} fixed, "
                    f"{chunks_still_failed} still failed"
                )
                
                return {
                    'success': True,
                    'chunks_reprocessed': len(chunks),
                    'chunks_fixed': chunks_fixed,
                    'chunks_still_failed': chunks_still_failed
                }
                
            except Exception as e:
                logger.error(f"Error in reprocess_failed_chunks: {e}", exc_info=True)
                await db.rollback()
                raise
    
    return run_async(_reprocess())


@celery_app.task(
    name='embedding.process_all_unprocessed_content',
    bind=True
)
def process_all_unprocessed_content(self) -> dict:
    """
    Periodic task to process all unprocessed content items.
    
    This task:
    1. Finds all ContentItems with status=PROCESSED (ready for chunking)
    2. Filters out items that already have chunks
    3. Queues process_content_item task for each
    
    Scheduled to run every 5 minutes via Celery Beat.
    
    Returns:
        Dictionary with task results
    """
    import asyncio
    
    async def _process_all():
        async with AsyncSessionLocal() as db:
            try:
                # Get all processed content items without chunks
                # Using a subquery to find content items that don't have chunks
                from sqlalchemy import exists
                
                # Subquery to check if content item has chunks
                has_chunks_subquery = select(ContentChunk.id).where(
                    ContentChunk.content_item_id == ContentItem.id
                ).exists()
                
                result = await db.execute(
                    select(ContentItem).where(
                        and_(
                            ContentItem.processing_status == ProcessingStatus.PROCESSED,
                            ~has_chunks_subquery
                        )
                    )
                )
                content_items = result.scalars().all()
                
                if not content_items:
                    logger.info("No unprocessed content items found")
                    return {
                        'success': True,
                        'message': 'No unprocessed content items',
                        'items_queued': 0
                    }
                
                logger.info(f"Found {len(content_items)} unprocessed content items")
                
                # Queue processing tasks
                task_ids = []
                items_queued = 0
                
                for content_item in content_items:
                    try:
                        # Verify content has sufficient body
                        if not content_item.content_body or len(content_item.content_body.strip()) < 100:
                            logger.debug(f"Skipping ContentItem {content_item.id} - insufficient content")
                            continue
                        
                        # Queue processing task
                        task = process_content_item.apply_async(
                            args=[content_item.id],
                            countdown=5  # Stagger tasks
                        )
                        task_ids.append(task.id)
                        items_queued += 1
                        
                        logger.info(
                            f"Queued processing for: {content_item.title} "
                            f"(ID: {content_item.id}, task: {task.id})"
                        )
                        
                    except Exception as e:
                        logger.error(
                            f"Error queuing ContentItem {content_item.id}: {e}",
                            exc_info=True
                        )
                        continue
                
                logger.info(f"Queued {items_queued}/{len(content_items)} content items for processing")
                
                return {
                    'success': True,
                    'total_items': len(content_items),
                    'items_queued': items_queued,
                    'task_ids': task_ids
                }
                
            except Exception as e:
                logger.error(f"Error in process_all_unprocessed_content: {e}", exc_info=True)
                raise
    
    return run_async(_process_all())


@celery_app.task(
    name='embedding.cleanup_orphaned_chunks',
    bind=True
)
def cleanup_orphaned_chunks(self) -> dict:
    """
    Clean up orphaned chunks (chunks whose content items were deleted).
    
    This is a maintenance task that should run periodically (e.g., daily).
    
    Returns:
        Dictionary with cleanup results
    """
    import asyncio
    
    async def _cleanup():
        async with AsyncSessionLocal() as db:
            try:
                # Find chunks with non-existent content items
                # Using a subquery to find orphaned chunks
                from sqlalchemy import exists
                
                content_item_exists = select(ContentItem.id).where(
                    ContentItem.id == ContentChunk.content_item_id
                ).exists()
                
                result = await db.execute(
                    select(ContentChunk).where(~content_item_exists)
                )
                orphaned_chunks = result.scalars().all()
                
                if not orphaned_chunks:
                    logger.info("No orphaned chunks found")
                    return {
                        'success': True,
                        'message': 'No orphaned chunks',
                        'chunks_deleted': 0
                    }
                
                logger.info(f"Found {len(orphaned_chunks)} orphaned chunks")
                
                # Delete orphaned chunks
                for chunk in orphaned_chunks:
                    await db.delete(chunk)
                
                await db.commit()
                
                logger.info(f"Deleted {len(orphaned_chunks)} orphaned chunks")
                
                return {
                    'success': True,
                    'chunks_deleted': len(orphaned_chunks)
                }
                
            except Exception as e:
                logger.error(f"Error in cleanup_orphaned_chunks: {e}", exc_info=True)
                await db.rollback()
                raise
    
    return run_async(_cleanup())


# ========================================
# Task Monitoring
# ========================================

@celery_app.task(name='embedding.get_processing_stats')
def get_processing_stats() -> dict:
    """
    Get statistics about RAG content processing.
    
    Returns counts of:
    - Content items with/without chunks
    - Chunks by status (pending, processing, processed, failed)
    - Chunks by content type
    
    Returns:
        Dictionary with processing statistics
    """
    import asyncio
    from sqlalchemy import func
    
    async def _get_stats():
        async with AsyncSessionLocal() as db:
            try:
                # Count content items
                total_content_items = await db.execute(
                    select(func.count(ContentItem.id))
                )
                total_content = total_content_items.scalar() or 0
                
                # Count content items with chunks
                content_with_chunks = await db.execute(
                    select(func.count(func.distinct(ContentChunk.content_item_id)))
                )
                items_with_chunks = content_with_chunks.scalar() or 0
                
                # Count chunks by status
                chunk_status_counts = await db.execute(
                    select(
                        ContentChunk.processing_status,
                        func.count(ContentChunk.id)
                    ).group_by(ContentChunk.processing_status)
                )
                status_counts = {row[0].value: row[1] for row in chunk_status_counts.all()}
                
                # Count chunks by content type
                chunk_type_counts = await db.execute(
                    select(
                        ContentItem.channel.has(source_type=ContentSourceType.YOUTUBE).label('is_youtube'),
                        func.count(ContentChunk.id)
                    )
                    .join(ContentItem)
                    .group_by('is_youtube')
                )
                
                # Total chunks
                total_chunks = await db.execute(
                    select(func.count(ContentChunk.id))
                )
                
                return {
                    'content_items': {
                        'total': total_content,
                        'with_chunks': items_with_chunks,
                        'without_chunks': total_content - items_with_chunks
                    },
                    'chunks': {
                        'total': total_chunks.scalar() or 0,
                        'pending': status_counts.get('pending', 0),
                        'processing': status_counts.get('processing', 0),
                        'processed': status_counts.get('processed', 0),
                        'failed': status_counts.get('failed', 0)
                    }
                }
                
            except Exception as e:
                logger.error(f"Error getting processing stats: {e}", exc_info=True)
                raise
    
    return run_async(_get_stats())

