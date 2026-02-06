"""
Integration tests for database operations.

Tests complex database queries, transactions, and relationships.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

from app.models.user import User, UserPreferences, UpdateFrequency, SummaryLength
from app.models.content import Channel, ContentItem, ContentChunk, UserSubscription, ContentSourceType, ProcessingStatus
from app.models.conversation import Conversation, Message, MessageRole
from app.core.security import get_password_hash


pytestmark = pytest.mark.integration


# ================================
# User & Preferences Tests
# ================================

@pytest.mark.asyncio
async def test_user_with_preferences_relationship(db_session: AsyncSession):
    """Test user and preferences one-to-one relationship."""
    # Create user
    user = User(
        email="dbtest@example.com",
        name="DB Test User",
        hashed_password=get_password_hash("testpass123"),
        timezone="UTC",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()
    
    # Create preferences
    preferences = UserPreferences(
        user_id=user.id,
        update_frequency=UpdateFrequency.WEEKLY,
        summary_length=SummaryLength.STANDARD,
        email_notifications_enabled=True
    )
    db_session.add(preferences)
    await db_session.commit()
    
    # Verify relationship
    await db_session.refresh(user)
    assert user.preferences is not None
    assert user.preferences.update_frequency == UpdateFrequency.WEEKLY
    assert user.preferences.email_notifications_enabled is True


@pytest.mark.asyncio
async def test_cascade_delete_user_preferences(db_session: AsyncSession):
    """Test that deleting user cascades to preferences."""
    # Create user with preferences
    user = User(
        email="cascade@example.com",
        name="Cascade Test",
        hashed_password=get_password_hash("testpass123"),
        timezone="UTC",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()
    
    preferences = UserPreferences(
        user_id=user.id,
        update_frequency=UpdateFrequency.DAILY,
        summary_length=SummaryLength.CONCISE,
        email_notifications_enabled=False
    )
    db_session.add(preferences)
    await db_session.commit()
    
    user_id = user.id
    
    # Delete user
    await db_session.delete(user)
    await db_session.commit()
    
    # Verify preferences are also deleted
    result = await db_session.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    assert result.scalar_one_or_none() is None


# ================================
# Content & Subscription Tests
# ================================

@pytest.mark.asyncio
async def test_user_subscription_to_channel(db_session: AsyncSession):
    """Test user can subscribe to channels."""
    # Create user
    user = User(
        email="subscriber@example.com",
        name="Subscriber",
        hashed_password=get_password_hash("testpass123"),
        timezone="UTC",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()
    
    preferences = UserPreferences(
        user_id=user.id,
        update_frequency=UpdateFrequency.WEEKLY,
        summary_length=SummaryLength.STANDARD,
        email_notifications_enabled=True
    )
    db_session.add(preferences)
    await db_session.flush()
    
    # Create channel
    channel = Channel(
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="test_channel_123",
        name="Test Channel",
        description="Test Channel Description",
        thumbnail_url="https://youtube.com/test",
        subscriber_count=0,
        is_active=True
    )
    db_session.add(channel)
    await db_session.flush()
    
    # Create subscription
    subscription = UserSubscription(
        user_id=user.id,
        channel_id=channel.id,
        is_active=True
    )
    db_session.add(subscription)
    await db_session.commit()
    
    # Verify relationships
    await db_session.refresh(user)
    await db_session.refresh(channel)
    
    assert len(user.subscriptions) == 1
    assert user.subscriptions[0].channel.name == "Test Channel"


@pytest.mark.asyncio
async def test_content_with_chunks_relationship(db_session: AsyncSession):
    """Test content item to chunks one-to-many relationship."""
    # Create channel
    channel = Channel(
        source_type=ContentSourceType.BLOG,
        source_identifier="blog_test",
        name="Test Blog",
        thumbnail_url="https://example.com/blog",
        is_active=True
    )
    db_session.add(channel)
    await db_session.flush()
    
    # Create content
    content = ContentItem(
        channel_id=channel.id,
        external_id="test_article_123",
        title="Test Article",
        author="Test Author",
        published_at=datetime.now(timezone.utc),
        content_body="This is a test article about React.",
        processing_status=ProcessingStatus.PROCESSED
    )
    db_session.add(content)
    await db_session.flush()
    
    # Create chunks
    import numpy as np
    chunk1 = ContentChunk(
        content_item_id=content.id,
        chunk_index=0,
        chunk_text="This is a test article",
        embedding=np.random.rand(384).tolist(),
        processing_status=ProcessingStatus.PROCESSED
    )
    chunk2 = ContentChunk(
        content_item_id=content.id,
        chunk_index=1,
        chunk_text="about React",
        embedding=np.random.rand(384).tolist(),
        processing_status=ProcessingStatus.PROCESSED
    )
    db_session.add_all([chunk1, chunk2])
    await db_session.commit()
    
    # Verify relationship
    await db_session.refresh(content)
    assert len(content.chunks) == 2
    assert content.chunks[0].chunk_index == 0
    assert content.chunks[1].chunk_index == 1


# ================================
# Conversation & Message Tests
# ================================

@pytest.mark.asyncio
async def test_conversation_with_messages(db_session: AsyncSession):
    """Test conversation to messages one-to-many relationship."""
    # Create user
    user = User(
        email="chat@example.com",
        name="Chat User",
        hashed_password=get_password_hash("testpass123"),
        timezone="UTC",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()
    
    preferences = UserPreferences(
        user_id=user.id,
        update_frequency=UpdateFrequency.WEEKLY,
        summary_length=SummaryLength.STANDARD,
        email_notifications_enabled=True
    )
    db_session.add(preferences)
    await db_session.flush()
    
    # Create conversation
    conversation = Conversation(
        user_id=user.id,
        title="Test Chat"
    )
    db_session.add(conversation)
    await db_session.flush()
    
    # Add messages
    messages = [
        Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="Hello"
        ),
        Message(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content="Hi there!"
        ),
        Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="How are you?"
        )
    ]
    db_session.add_all(messages)
    await db_session.commit()
    
    # Verify relationship
    await db_session.refresh(conversation)
    assert len(conversation.messages) == 3
    assert conversation.messages[0].role == MessageRole.USER
    assert conversation.messages[1].role == MessageRole.ASSISTANT


@pytest.mark.asyncio
async def test_message_with_chunks_many_to_many(db_session: AsyncSession):
    """Test message to chunks many-to-many relationship (citations)."""
    # Create minimal setup
    user = User(
        email="citations@example.com",
        name="Citations User",
        hashed_password=get_password_hash("testpass123"),
        timezone="UTC",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()
    
    preferences = UserPreferences(
        user_id=user.id,
        update_frequency=UpdateFrequency.WEEKLY,
        summary_length=SummaryLength.STANDARD,
        email_notifications_enabled=True
    )
    db_session.add(preferences)
    await db_session.flush()
    
    channel = Channel(
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="citations_test",
        name="Test Channel",
        thumbnail_url="https://youtube.com/test",
        is_active=True
    )
    db_session.add(channel)
    await db_session.flush()
    
    content = ContentItem(
        channel_id=channel.id,
        external_id="test_video_123",
        title="Test Video",
        author="Test Author",
        published_at=datetime.now(timezone.utc),
        content_body="Test content",
        processing_status=ProcessingStatus.PROCESSED
    )
    db_session.add(content)
    await db_session.flush()
    
    # Create chunks
    import numpy as np
    chunks = [
        ContentChunk(
            content_item_id=content.id,
            chunk_index=i,
            chunk_text=f"Chunk {i}",
            embedding=np.random.rand(384).tolist(),
            processing_status=ProcessingStatus.PROCESSED
        )
        for i in range(3)
    ]
    db_session.add_all(chunks)
    await db_session.flush()
    
    # Create conversation and message
    conversation = Conversation(user_id=user.id, title="Test")
    db_session.add(conversation)
    await db_session.flush()
    
    message = Message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content="Answer with citations",
        retrieved_chunks=chunks
    )
    db_session.add(message)
    await db_session.commit()
    
    # Verify relationship
    await db_session.refresh(message)
    assert len(message.retrieved_chunks) == 3


# ================================
# Complex Query Tests
# ================================

@pytest.mark.asyncio
async def test_count_users_by_update_frequency(db_session: AsyncSession):
    """Test aggregation query."""
    # Create multiple users with different preferences
    users_data = [
        ("user1@test.com", UpdateFrequency.DAILY),
        ("user2@test.com", UpdateFrequency.DAILY),
        ("user3@test.com", UpdateFrequency.WEEKLY),
    ]
    
    for email, freq in users_data:
        user = User(
            email=email,
            name="Test User",
            hashed_password=get_password_hash("testpass123"),
            timezone="UTC",
            is_active=True
        )
        db_session.add(user)
        await db_session.flush()
        
        prefs = UserPreferences(
            user_id=user.id,
            update_frequency=freq,
            summary_length=SummaryLength.STANDARD,
            email_notifications_enabled=True
        )
        db_session.add(prefs)
    
    await db_session.commit()
    
    # Count by frequency
    result = await db_session.execute(
        select(
            UserPreferences.update_frequency,
            func.count(UserPreferences.id)
        )
        .group_by(UserPreferences.update_frequency)
    )
    counts = dict(result.all())
    
    assert counts[UpdateFrequency.DAILY] >= 2
    assert counts[UpdateFrequency.WEEKLY] >= 1


@pytest.mark.asyncio
async def test_content_items_with_chunks_count(db_session: AsyncSession):
    """Test content items with chunk counts."""
    # Create channel
    channel = Channel(
        source_type=ContentSourceType.REDDIT,
        source_identifier="test_sub",
        name="Test Subreddit",
        thumbnail_url="https://reddit.com/r/test",
        is_active=True
    )
    db_session.add(channel)
    await db_session.flush()
    
    # Create content items with varying chunk counts
    import numpy as np
    
    for i in range(3):
        content = ContentItem(
            channel_id=channel.id,
            external_id=f"test_post_{i}",
            title=f"Post {i}",
            author="Test Author",
            published_at=datetime.now(timezone.utc),
            content_body=f"Content {i}",
            processing_status=ProcessingStatus.PROCESSED
        )
        db_session.add(content)
        await db_session.flush()
        
        # Add chunks
        for j in range(i + 1):  # 1, 2, 3 chunks respectively
            chunk = ContentChunk(
                content_item_id=content.id,
                chunk_index=j,
                chunk_text=f"Chunk {j}",
                embedding=np.random.rand(384).tolist(),
                processing_status=ProcessingStatus.PROCESSED
            )
            db_session.add(chunk)
    
    await db_session.commit()
    
    # Query items with chunk counts
    result = await db_session.execute(
        select(
            ContentItem.id,
            ContentItem.title,
            func.count(ContentChunk.id).label("chunk_count")
        )
        .join(ContentChunk)
        .group_by(ContentItem.id, ContentItem.title)
        .order_by(ContentItem.id)
    )
    
    items = result.all()
    assert len(items) == 3
    assert items[0].chunk_count == 1
    assert items[1].chunk_count == 2
    assert items[2].chunk_count == 3


# ================================
# Transaction Tests
# ================================

@pytest.mark.asyncio
async def test_transaction_rollback(db_session: AsyncSession):
    """Test transaction rollback on error."""
    try:
        # Create user
        user = User(
            email="rollback@test.com",
            name="Rollback Test",
            hashed_password=get_password_hash("testpass123"),
            timezone="UTC",
            is_active=True
        )
        db_session.add(user)
        await db_session.flush()
        
        # Try to create duplicate
        duplicate = User(
            email="rollback@test.com",  # Same email
            name="Duplicate",
            hashed_password=get_password_hash("testpass123"),
            timezone="UTC",
            is_active=True
        )
        db_session.add(duplicate)
        await db_session.commit()
        
        assert False, "Should have raised error"
    except Exception:
        await db_session.rollback()
        
        # Verify nothing was committed
        result = await db_session.execute(
            select(func.count(User.id)).where(User.email == "rollback@test.com")
        )
        count = result.scalar()
        assert count == 0


# ================================
# Performance Tests
# ================================

@pytest.mark.asyncio
async def test_bulk_insert_performance(db_session: AsyncSession):
    """Test bulk insert performance."""
    import time
    
    # Create channel
    channel = Channel(
        source_type=ContentSourceType.BLOG,
        source_identifier="bulk_test",
        name="Bulk Test",
        thumbnail_url="https://example.com/bulk",
        is_active=True
    )
    db_session.add(channel)
    await db_session.flush()
    
    # Bulk insert content items
    items = [
        ContentItem(
            channel_id=channel.id,
            external_id=f"test_article_{i}",
            title=f"Article {i}",
            author="Test Author",
            published_at=datetime.now(timezone.utc),
            content_body=f"Content {i}",
            processing_status=ProcessingStatus.PENDING
        )
        for i in range(100)
    ]
    
    start = time.time()
    db_session.add_all(items)
    await db_session.commit()
    duration = time.time() - start
    
    # Should be reasonably fast (< 1 second for 100 items)
    assert duration < 1.0, f"Bulk insert took {duration:.2f}s (too slow)"

