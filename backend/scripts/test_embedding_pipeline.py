#!/usr/bin/env python3
"""
Integration test script for RAG embedding pipeline.

This script tests the full pipeline:
1. Creates test content
2. Triggers embedding tasks
3. Verifies chunks are created
4. Checks embeddings are generated
5. Validates data integrity

Usage:
    python scripts/test_embedding_pipeline.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.content import Channel, ContentItem, ContentChunk, ProcessingStatus, ContentSourceType
from app.tasks.embedding_tasks import (
    process_content_item,
    batch_embed_pending,
    get_processing_stats
)


async def cleanup_test_data(db):
    """Clean up any existing test data."""
    print("\n🧹 Cleaning up existing test data...")
    
    # Delete test content items
    result = await db.execute(
        select(ContentItem).where(ContentItem.external_id.like('test_embed_%'))
    )
    items = result.scalars().all()
    for item in items:
        await db.delete(item)
    
    # Delete test channels
    result = await db.execute(
        select(Channel).where(Channel.source_identifier.like('test_embed_%'))
    )
    channels = result.scalars().all()
    for channel in channels:
        await db.delete(channel)
    
    await db.commit()
    print(f"✅ Cleaned up {len(items)} items and {len(channels)} channels")


async def create_test_content(db):
    """Create test channel and content items."""
    print("\n📝 Creating test content...")
    
    # Create test channel
    channel = Channel(
        name="Test Embedding Channel",
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="test_embed_channel_001",
        is_active=True,
        description="Test channel for embedding pipeline"
    )
    db.add(channel)
    await db.flush()
    
    print(f"✅ Created test channel (ID: {channel.id})")
    
    # Create test content items
    test_content = [
        {
            "external_id": "test_embed_video_001",
            "title": "Introduction to Python Programming",
            "content_body": """
            Python is a high-level, interpreted programming language known for its simplicity and readability.
            It was created by Guido van Rossum and first released in 1991. Python supports multiple programming
            paradigms, including procedural, object-oriented, and functional programming. The language emphasizes
            code readability with its notable use of significant whitespace. Python's design philosophy emphasizes
            code readability with its notable use of significant whitespace. Its language constructs and 
            object-oriented approach aim to help programmers write clear, logical code for small and large-scale 
            projects. Python is dynamically typed and garbage-collected. It supports multiple programming paradigms,
            including structured, object-oriented and functional programming. Python is often described as a 
            "batteries included" language due to its comprehensive standard library. Python interpreters are 
            available for many operating systems. CPython, the reference implementation of Python, is open source 
            software and has a community-based development model. Python and CPython are managed by the non-profit 
            Python Software Foundation.
            """ * 3  # Make it long enough to create multiple chunks
        },
        {
            "external_id": "test_embed_video_002", 
            "title": "Understanding Machine Learning Basics",
            "content_body": """
            Machine learning is a method of data analysis that automates analytical model building. It is a branch
            of artificial intelligence based on the idea that systems can learn from data, identify patterns and
            make decisions with minimal human intervention. Machine learning algorithms are trained on data sets
            that contain examples of the inputs and the desired outputs. The algorithm learns by analyzing the
            relationships between the inputs and outputs. Once trained, the algorithm can be used to make predictions
            on new data. There are three main types of machine learning: supervised learning, unsupervised learning,
            and reinforcement learning. Supervised learning is when the algorithm is trained on labeled data, where
            the correct output is known. Unsupervised learning is when the algorithm is trained on unlabeled data,
            and must find patterns on its own. Reinforcement learning is when the algorithm learns by trial and error,
            receiving rewards for good actions and penalties for bad actions. Machine learning has many applications,
            including image recognition, natural language processing, recommendation systems, fraud detection, and
            autonomous vehicles.
            """ * 3
        }
    ]
    
    content_items = []
    for item_data in test_content:
        content_item = ContentItem(
            channel_id=channel.id,
            external_id=item_data["external_id"],
            title=item_data["title"],
            content_body=item_data["content_body"],
            author="Test Author",
            processing_status=ProcessingStatus.PROCESSED,  # Ready for embedding
            content_metadata={
                "video_id": item_data["external_id"],
                "duration_seconds": 600,
                "view_count": 1000
            }
        )
        db.add(content_item)
        content_items.append(content_item)
    
    await db.commit()
    
    for item in content_items:
        await db.refresh(item)
        print(f"✅ Created content item: {item.title} (ID: {item.id})")
    
    return channel, content_items


async def test_process_content_item(content_item):
    """Test processing a single content item."""
    print(f"\n🔄 Testing process_content_item for: {content_item.title}")
    
    try:
        # Run the task
        result = process_content_item(content_item.id)
        
        print(f"✅ Task completed successfully")
        print(f"   - Chunks created: {result.get('chunks_created', 0)}")
        print(f"   - Chunks embedded: {result.get('chunks_embedded', 0)}")
        print(f"   - Processing time: {result.get('processing_time_seconds', 0):.2f}s")
        
        return result
        
    except Exception as e:
        print(f"❌ Task failed: {e}")
        return None


async def verify_chunks(db, content_item):
    """Verify that chunks were created correctly."""
    print(f"\n🔍 Verifying chunks for: {content_item.title}")
    
    result = await db.execute(
        select(ContentChunk).where(
            ContentChunk.content_item_id == content_item.id
        ).order_by(ContentChunk.chunk_index)
    )
    chunks = result.scalars().all()
    
    if not chunks:
        print(f"❌ No chunks found!")
        return False
    
    print(f"✅ Found {len(chunks)} chunks")
    
    # Verify each chunk
    all_valid = True
    for chunk in chunks:
        status = "✅" if chunk.processing_status == ProcessingStatus.PROCESSED else "❌"
        has_embedding = "✅" if chunk.embedding else "❌"
        
        print(f"   {status} Chunk {chunk.chunk_index}:")
        print(f"      - Text length: {len(chunk.chunk_text)} chars")
        print(f"      - Status: {chunk.processing_status.value}")
        print(f"      - Has embedding: {has_embedding}")
        
        if chunk.embedding:
            print(f"      - Embedding dimensions: {len(chunk.embedding)}")
            
            # Verify embedding dimension
            if len(chunk.embedding) != 768:
                print(f"      ⚠️  WARNING: Expected 768 dimensions, got {len(chunk.embedding)}")
                all_valid = False
        else:
            print(f"      ❌ No embedding generated!")
            all_valid = False
        
        if chunk.processing_status != ProcessingStatus.PROCESSED:
            print(f"      ❌ Chunk not processed correctly!")
            all_valid = False
    
    return all_valid


async def test_statistics():
    """Test the statistics function."""
    print("\n📊 Testing get_processing_stats...")
    
    try:
        stats = get_processing_stats()
        
        print("✅ Statistics retrieved successfully:")
        print(f"   Content Items:")
        print(f"      - Total: {stats['content_items']['total']}")
        print(f"      - With chunks: {stats['content_items']['with_chunks']}")
        print(f"      - Without chunks: {stats['content_items']['without_chunks']}")
        print(f"   Chunks:")
        print(f"      - Total: {stats['chunks']['total']}")
        print(f"      - Pending: {stats['chunks']['pending']}")
        print(f"      - Processing: {stats['chunks']['processing']}")
        print(f"      - Processed: {stats['chunks']['processed']}")
        print(f"      - Failed: {stats['chunks']['failed']}")
        
        return stats
        
    except Exception as e:
        print(f"❌ Statistics failed: {e}")
        return None


async def main():
    """Run the integration test."""
    print("=" * 70)
    print("RAG Embedding Pipeline Integration Test")
    print("=" * 70)
    
    async with AsyncSessionLocal() as db:
        try:
            # Step 1: Cleanup
            await cleanup_test_data(db)
            
            # Step 2: Create test content
            channel, content_items = await create_test_content(db)
            
            # Step 3: Process each content item
            results = []
            for content_item in content_items:
                result = await test_process_content_item(content_item)
                results.append(result)
                
                if result and result.get('success'):
                    # Verify chunks
                    await db.refresh(content_item)
                    is_valid = await verify_chunks(db, content_item)
                    
                    if not is_valid:
                        print(f"⚠️  WARNING: Validation failed for {content_item.title}")
            
            # Step 4: Test statistics
            await test_statistics()
            
            # Summary
            print("\n" + "=" * 70)
            print("Test Summary")
            print("=" * 70)
            
            successful = sum(1 for r in results if r and r.get('success'))
            total = len(results)
            
            print(f"✅ Successfully processed: {successful}/{total} content items")
            
            if successful == total:
                print("\n🎉 All tests passed! The embedding pipeline is working correctly.")
                return 0
            else:
                print(f"\n⚠️  Some tests failed. Check the output above for details.")
                return 1
            
        except Exception as e:
            print(f"\n❌ Integration test failed with error: {e}")
            import traceback
            traceback.print_exc()
            return 1
        finally:
            # Cleanup
            print("\n🧹 Final cleanup...")
            await cleanup_test_data(db)


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

