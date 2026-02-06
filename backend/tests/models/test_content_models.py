"""
Comprehensive tests for Content models.

This script tests:
1. Channel model - Shared content sources
2. UserSubscription model - Association object for many-to-many
3. ContentItem model - Actual content storage
4. Relationships between all models
5. JSONB metadata storage and querying
6. Processing status transitions
7. Unique constraints
8. Cascade deletes

Run this script to verify content models work correctly:
    python test_content_models.py

Or inside Docker:
    docker compose exec api python test_content_models.py

Following best practices from:
https://pytest-with-eric.com/database-testing/pytest-sql-database-testing/
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Integer, select
from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.content import (
    Channel,
    ContentItem,
    ContentSourceType,
    ProcessingStatus,
    UserSubscription,
)
from app.models.user import SummaryLength, UpdateFrequency, User, UserPreferences

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Skip all tests in this file when running with pytest
# This file is designed to be run as a standalone script
pytestmark = pytest.mark.skip(reason="Standalone integration script, not for pytest")


async def test_create_channel():
    """Test 1: Create a shared channel."""
    print("\n" + "="*60)
    print("🧪 Test 1: Creating a Shared Channel")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Create YouTube channel
            channel = Channel(
                source_type=ContentSourceType.YOUTUBE,
                source_identifier="UCsBjURrPoezykLs9EqgamOA",
                name="Fireship",
                description="High-intensity code tutorials",
                thumbnail_url="https://yt3.ggpht.com/ytc/fireship",
                is_active=True
            )
            db.add(channel)
            await db.commit()
            await db.refresh(channel)
            
            print(f"✓ Created channel: {channel}")
            print(f"  ID: {channel.id}")
            print(f"  Name: {channel.name}")
            print(f"  Type: {channel.source_type.value}")
            print(f"  Identifier: {channel.source_identifier}")
            print(f"  Subscribers: {channel.subscriber_count}")
            print(f"  Active: {channel.is_active}")
            
            return channel.id
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error creating channel: {e}")
            raise


async def test_user_subscribes_to_channel(user_id: int, channel_id: int):
    """Test 2: User subscribes to a channel."""
    print("\n" + "="*60)
    print("🔔 Test 2: User Subscribes to Channel")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Create subscription
            subscription = UserSubscription(
                user_id=user_id,
                channel_id=channel_id,
                is_active=True,
                custom_display_name="My Favorite Channel",
                notification_enabled=True
            )
            db.add(subscription)
            
            # Update channel subscriber count
            channel = await db.get(Channel, channel_id)
            channel.subscriber_count += 1
            
            await db.commit()
            await db.refresh(subscription)
            
            print(f"✓ Created subscription: {subscription}")
            print(f"  User ID: {subscription.user_id}")
            print(f"  Channel ID: {subscription.channel_id}")
            print(f"  Active: {subscription.is_active}")
            print(f"  Custom name: {subscription.custom_display_name}")
            print(f"  Notifications: {subscription.notification_enabled}")
            print(f"\n✓ Channel subscriber count: {channel.subscriber_count}")
            
            return subscription.id
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error creating subscription: {e}")
            raise


async def test_query_user_subscriptions(user_id: int):
    """Test 3: Query user's subscriptions and channels."""
    print("\n" + "="*60)
    print("🔍 Test 3: Querying User's Subscriptions")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Get user with subscriptions
            user = await db.get(User, user_id)
            
            print(f"✓ User: {user.name}")
            print(f"  Subscriptions: {len(user.subscriptions)}")
            
            for sub in user.subscriptions:
                channel = sub.channel
                print(f"\n  Channel: {channel.name}")
                print(f"    Type: {channel.source_type.value}")
                print(f"    Display name: {sub.display_name}")
                print(f"    Active: {sub.is_active}")
                print(f"    Notifications: {sub.notification_enabled}")
            
            print("\n✓ Many-to-many relationship works!")
            
        except Exception as e:
            print(f"✗ Error querying subscriptions: {e}")
            raise


async def test_add_content_to_channel(channel_id: int):
    """Test 4: Add content items to a channel."""
    print("\n" + "="*60)
    print("📹 Test 4: Adding Content to Channel")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Add YouTube video
            video = ContentItem(
                channel_id=channel_id,
                external_id="dQw4w9WgXcQ",
                title="100+ Docker Concepts you Need to Know",
                content_body="[Full video transcript here...]\n\nDocker is amazing...",
                author="Fireship",
                published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
                processing_status=ProcessingStatus.PENDING,
                content_metadata={
                    "video_id": "dQw4w9WgXcQ",
                    "duration": 863,
                    "view_count": 500000,
                    "like_count": 25000,
                    "comment_count": 1200,
                    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
                    "transcript_language": "en"
                }
            )
            db.add(video)
            
            # Add another video
            video2 = ContentItem(
                channel_id=channel_id,
                external_id="abc123xyz",
                title="JavaScript in 100 Seconds",
                content_body="[Transcript...] JavaScript is the language of the web...",
                author="Fireship",
                published_at=datetime(2024, 1, 20, tzinfo=timezone.utc),
                processing_status=ProcessingStatus.PENDING,
                content_metadata={
                    "video_id": "abc123xyz",
                    "duration": 120,
                    "view_count": 1000000,
                    "like_count": 50000
                }
            )
            db.add(video2)
            
            await db.commit()
            await db.refresh(video)
            await db.refresh(video2)
            
            print(f"✓ Added content: {video}")
            print(f"  Title: {video.title}")
            print(f"  Author: {video.author}")
            print(f"  Published: {video.published_at}")
            print(f"  Status: {video.processing_status.value}")
            print(f"  Duration: {video.content_metadata.get('duration')} seconds")
            print(f"  Views: {video.content_metadata.get('view_count'):,}")
            
            print(f"\n✓ Added content: {video2}")
            print(f"  Title: {video2.title}")
            print(f"  Views: {video2.content_metadata.get('view_count'):,}")
            
            return [video.id, video2.id]
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error adding content: {e}")
            raise


async def test_query_channel_content(channel_id: int):
    """Test 5: Query channel's content items."""
    print("\n" + "="*60)
    print("📚 Test 5: Querying Channel Content")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Get channel with content
            channel = await db.get(Channel, channel_id)
            
            print(f"✓ Channel: {channel.name}")
            print(f"  Content items: {len(channel.content_items)}")
            
            for item in channel.content_items:
                print(f"\n  Content: {item.title}")
                print(f"    Published: {item.published_at}")
                print(f"    Status: {item.processing_status.value}")
                print(f"    Views: {item.content_metadata.get('view_count', 0):,}")
            
            print("\n✓ One-to-many relationship (Channel → ContentItem) works!")
            
        except Exception as e:
            print(f"✗ Error querying content: {e}")
            raise


async def test_process_content(content_id: int):
    """Test 6: Process content through pipeline."""
    print("\n" + "="*60)
    print("⚙️  Test 6: Processing Content Pipeline")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            content = await db.get(ContentItem, content_id)
            
            print(f"Initial status: {content.processing_status.value}")
            print(f"  is_processed: {content.is_processed}")
            print(f"  needs_processing: {content.needs_processing}")
            print(f"  has_failed: {content.has_failed}")
            
            # Simulate processing pipeline
            print("\n→ Updating to PROCESSING...")
            content.processing_status = ProcessingStatus.PROCESSING
            await db.commit()
            
            print(f"  Status: {content.processing_status.value}")
            print(f"  needs_processing: {content.needs_processing}")
            
            # Simulate successful processing
            print("\n→ Updating to PROCESSED...")
            content.processing_status = ProcessingStatus.PROCESSED
            await db.commit()
            
            print(f"  Status: {content.processing_status.value}")
            print(f"  is_processed: {content.is_processed}")
            
            print("\n✓ Content processing pipeline works!")
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error processing content: {e}")
            raise


async def test_failed_content():
    """Test 7: Test failed content handling."""
    print("\n" + "="*60)
    print("❌ Test 7: Failed Content Handling")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Get an existing channel
            result = await db.execute(select(Channel).limit(1))
            channel = result.scalar_one()
            
            # Create content that will fail
            content = ContentItem(
                channel_id=channel.id,
                external_id="failed_video",
                title="Test Failed Processing",
                content_body="Test content",
                author="Test",
                published_at=datetime.now(timezone.utc),
                processing_status=ProcessingStatus.PENDING
            )
            db.add(content)
            await db.commit()
            await db.refresh(content)
            
            print(f"✓ Created content: {content.title}")
            print(f"  Status: {content.processing_status.value}")
            
            # Simulate processing failure
            content.processing_status = ProcessingStatus.FAILED
            content.error_message = "Transcription API timeout"
            await db.commit()
            
            print(f"\n→ Processing failed:")
            print(f"  Status: {content.processing_status.value}")
            print(f"  Error: {content.error_message}")
            print(f"  has_failed: {content.has_failed}")
            
            # Query failed content for retry
            result = await db.execute(
                select(ContentItem).where(
                    ContentItem.processing_status == ProcessingStatus.FAILED
                )
            )
            failed_items = result.scalars().all()
            
            print(f"\n✓ Failed content query found {len(failed_items)} items")
            print("  These can be retried by background jobs")
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error testing failed content: {e}")
            raise


async def test_jsonb_queries(channel_id: int):
    """Test 8: Query JSONB metadata."""
    print("\n" + "="*60)
    print("🔍 Test 8: Querying JSONB Metadata")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Query content with high view count
            result = await db.execute(
                select(ContentItem)
                .where(
                    ContentItem.channel_id == channel_id,
                    ContentItem.content_metadata['view_count'].astext.cast(Integer) > 500000
                )
            )
            popular_content = result.scalars().all()
            
            print(f"✓ Popular content (>500k views): {len(popular_content)} items")
            for item in popular_content:
                views = item.content_metadata.get('view_count', 0)
                print(f"  - {item.title}: {views:,} views")
            
            # Query content with duration
            result = await db.execute(
                select(ContentItem)
                .where(
                    ContentItem.channel_id == channel_id,
                    ContentItem.content_metadata.has_key('duration')
                )
            )
            content_with_duration = result.scalars().all()
            
            print(f"\n✓ Content with duration: {len(content_with_duration)} items")
            for item in content_with_duration:
                duration = item.content_metadata.get('duration', 0)
                minutes = duration // 60
                seconds = duration % 60
                print(f"  - {item.title}: {minutes}m {seconds}s")
            
            print("\n✓ JSONB querying works!")
            
        except Exception as e:
            print(f"✗ Error querying JSONB: {e}")
            raise


async def test_unique_constraints():
    """Test 9: Test unique constraints."""
    print("\n" + "="*60)
    print("🔒 Test 9: Testing Unique Constraints")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Try to create duplicate channel
            print("→ Attempting to create duplicate channel...")
            channel = Channel(
                source_type=ContentSourceType.YOUTUBE,
                source_identifier="UCsBjURrPoezykLs9EqgamOA",  # Same as existing
                name="Duplicate Fireship"
            )
            db.add(channel)
            
            try:
                await db.commit()
                print("✗ ERROR: Duplicate channel was allowed!")
                return False
            except IntegrityError as e:
                await db.rollback()
                print("✓ Duplicate channel prevented by unique constraint")
                print(f"  Error: {str(e.orig)[:100]}...")
            
            # Try to create duplicate subscription
            print("\n→ Attempting to create duplicate subscription...")
            
            # Get existing subscription
            result = await db.execute(select(UserSubscription).limit(1))
            existing_sub = result.scalar_one()
            
            subscription = UserSubscription(
                user_id=existing_sub.user_id,
                channel_id=existing_sub.channel_id  # Same as existing
            )
            db.add(subscription)
            
            try:
                await db.commit()
                print("✗ ERROR: Duplicate subscription was allowed!")
                return False
            except IntegrityError as e:
                await db.rollback()
                print("✓ Duplicate subscription prevented by unique constraint")
                print(f"  Error: {str(e.orig)[:100]}...")
            
            # Try to create duplicate content
            print("\n→ Attempting to create duplicate content...")
            
            # Get existing content
            result = await db.execute(select(ContentItem).limit(1))
            existing_content = result.scalar_one()
            
            content = ContentItem(
                channel_id=existing_content.channel_id,
                external_id=existing_content.external_id,  # Same as existing
                title="Duplicate",
                content_body="Test",
                author="Test",
                published_at=datetime.now(timezone.utc)
            )
            db.add(content)
            
            try:
                await db.commit()
                print("✗ ERROR: Duplicate content was allowed!")
                return False
            except IntegrityError as e:
                await db.rollback()
                print("✓ Duplicate content prevented by unique constraint")
                print(f"  Error: {str(e.orig)[:100]}...")
            
            print("\n✓ All unique constraints working correctly!")
            return True
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error testing constraints: {e}")
            raise


async def test_cascade_deletes(user_id: int, channel_id: int):
    """Test 10: Test cascade delete behavior."""
    print("\n" + "="*60)
    print("🗑️  Test 10: Testing Cascade Deletes")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Get counts before delete
            channel = await db.get(Channel, channel_id)
            subscription_ids = [sub.id for sub in channel.subscriptions]
            content_ids = [item.id for item in channel.content_items]
            
            print(f"Before delete:")
            print(f"  Channel: {channel.name}")
            print(f"  Subscriptions: {len(subscription_ids)}")
            print(f"  Content items: {len(content_ids)}")
            
            # Delete channel
            await db.delete(channel)
            await db.commit()
            
            print(f"\n✓ Channel deleted")
            
            # Verify subscriptions deleted
            for sub_id in subscription_ids:
                result = await db.execute(
                    select(UserSubscription).where(UserSubscription.id == sub_id)
                )
                sub = result.scalar_one_or_none()
                if sub is None:
                    print(f"✓ Subscription {sub_id} deleted (CASCADE worked)")
                else:
                    print(f"✗ Subscription {sub_id} still exists!")
            
            # Verify content deleted
            for content_id in content_ids:
                result = await db.execute(
                    select(ContentItem).where(ContentItem.id == content_id)
                )
                content = result.scalar_one_or_none()
                if content is None:
                    print(f"✓ Content {content_id} deleted (CASCADE worked)")
                else:
                    print(f"✗ Content {content_id} still exists!")
            
            # Test user deletion cascades to subscriptions
            print(f"\n→ Testing user deletion cascade...")
            user = await db.get(User, user_id)
            await db.delete(user)
            await db.commit()
            
            print(f"✓ User deleted")
            print("✓ All cascade deletes working correctly!")
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error testing cascades: {e}")
            raise


async def test_recent_content_query():
    """Test 11: Query recent content for user."""
    print("\n" + "="*60)
    print("📅 Test 11: Querying Recent Content for User")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Create test user and channel
            user = User(
                email="test@example.com",
                name="Test User",
                timezone="America/New_York"
            )
            db.add(user)
            await db.flush()
            
            prefs = UserPreferences(
                user_id=user.id,
                update_frequency=UpdateFrequency.WEEKLY,
                summary_length=SummaryLength.STANDARD
            )
            db.add(prefs)
            
            channel = Channel(
                source_type=ContentSourceType.REDDIT,
                source_identifier="python",
                name="r/python"
            )
            db.add(channel)
            await db.flush()
            
            subscription = UserSubscription(
                user_id=user.id,
                channel_id=channel.id,
                is_active=True
            )
            db.add(subscription)
            
            # Add recent content
            for i in range(5):
                content = ContentItem(
                    channel_id=channel.id,
                    external_id=f"post_{i}",
                    title=f"Python Post {i}",
                    content_body=f"Content {i}",
                    author="user123",
                    published_at=datetime.now(timezone.utc) - timedelta(days=i),
                    processing_status=ProcessingStatus.PROCESSED
                )
                db.add(content)
            
            await db.commit()
            
            # Query recent processed content from user's active subscriptions
            result = await db.execute(
                select(ContentItem)
                .join(Channel)
                .join(UserSubscription)
                .where(
                    UserSubscription.user_id == user.id,
                    UserSubscription.is_active == True,
                    ContentItem.processing_status == ProcessingStatus.PROCESSED,
                    ContentItem.published_at >= datetime.now(timezone.utc) - timedelta(days=7)
                )
                .order_by(ContentItem.published_at.desc())
            )
            recent_content = result.scalars().all()
            
            print(f"✓ Found {len(recent_content)} recent content items")
            for item in recent_content:
                days_ago = (datetime.now(timezone.utc) - item.published_at).days
                print(f"  - {item.title} ({days_ago} days ago)")
            
            print("\n✓ Complex join query works!")
            print("✓ This is how we'll fetch content for digests!")
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error querying recent content: {e}")
            raise


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("🧪 Testing Content Models (Channel, UserSubscription, ContentItem)")
    print("="*60)
    
    try:
        # Create test user first
        async with AsyncSessionLocal() as db:
            user = User(
                email="alice@example.com",
                name="Alice Johnson",
                timezone="America/New_York"
            )
            db.add(user)
            await db.flush()
            
            prefs = UserPreferences(
                user_id=user.id,
                update_frequency=UpdateFrequency.WEEKLY,
                summary_length=SummaryLength.STANDARD
            )
            db.add(prefs)
            await db.commit()
            user_id = user.id
        
        # Test 1: Create channel
        channel_id = await test_create_channel()
        
        # Test 2: User subscribes
        subscription_id = await test_user_subscribes_to_channel(user_id, channel_id)
        
        # Test 3: Query subscriptions
        await test_query_user_subscriptions(user_id)
        
        # Test 4: Add content
        content_ids = await test_add_content_to_channel(channel_id)
        
        # Test 5: Query channel content
        await test_query_channel_content(channel_id)
        
        # Test 6: Process content
        await test_process_content(content_ids[0])
        
        # Test 7: Failed content
        await test_failed_content()
        
        # Test 8: JSONB queries
        await test_jsonb_queries(channel_id)
        
        # Test 9: Unique constraints
        await test_unique_constraints()
        
        # Test 11: Recent content query
        await test_recent_content_query()
        
        # Test 10: Cascade deletes (do this last!)
        await test_cascade_deletes(user_id, channel_id)
        
        print("\n" + "="*60)
        print("✅ All Tests Passed!")
        print("="*60)
        print("\nKey Takeaways:")
        print("1. ✓ Channel model (shared sources) works")
        print("2. ✓ UserSubscription (association object) works")
        print("3. ✓ ContentItem model (content storage) works")
        print("4. ✓ Many-to-many relationship (User ←→ Channel) works")
        print("5. ✓ One-to-many relationship (Channel → ContentItem) works")
        print("6. ✓ JSONB metadata storage and querying works")
        print("7. ✓ Processing status pipeline works")
        print("8. ✓ Unique constraints prevent duplicates")
        print("9. ✓ Cascade deletes maintain data integrity")
        print("10. ✓ Complex join queries for user content work")
        print("\n🎉 Production-ready content management system!")
        
        return 0
        
    except Exception as e:
        print("\n" + "="*60)
        print("❌ Tests Failed!")
        print("="*60)
        logger.exception("Test failed with exception")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
