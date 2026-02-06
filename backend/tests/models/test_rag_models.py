"""
Tests for RAG models (ContentChunk, Conversation, Message).

This test module verifies:
1. Model creation and basic fields
2. Relationships between models
3. Unique constraints
4. Cascade deletes
5. Property methods
6. Edge cases
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.content import Channel, ContentItem, ContentChunk, ContentSourceType, ProcessingStatus
from app.models.conversation import Conversation, Message, MessageRole
from app.models.user import User


@pytest.mark.asyncio
class TestContentChunkModel:
    """Test ContentChunk model functionality."""
    
    async def test_create_content_chunk(self, db_session):
        """Test creating a content chunk with all fields."""
        # Create dependencies
        user = User(
            email="test_content_chunk@example.com",
            name="Test User",
            timezone="UTC",
            is_active=True
        )
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test_channel",
            name="Test Channel",
            subscriber_count=0,
            is_active=True
        )
        db_session.add(channel)
        await db_session.flush()
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="test_video_123",
            title="Test Video",
            content_body="This is a test transcript.",
            author="Test Author",
            published_at=datetime.now(timezone.utc),
            processing_status=ProcessingStatus.PROCESSED
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Create content chunk
        chunk = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=0,
            chunk_text="This is the first chunk of content.",
            chunk_metadata={"start_time": 0, "end_time": 120},
            processing_status="pending"
        )
        db_session.add(chunk)
        await db_session.commit()
        
        # Verify
        assert chunk.id is not None
        assert chunk.content_item_id == content_item.id
        assert chunk.chunk_index == 0
        assert chunk.chunk_text == "This is the first chunk of content."
        assert chunk.chunk_metadata["start_time"] == 0
        assert chunk.processing_status == "pending"
        assert chunk.created_at is not None
        assert chunk.updated_at is not None
    
    async def test_content_chunk_relationship_to_content_item(self, db_session):
        """Test relationship between ContentChunk and ContentItem."""
        # Create dependencies
        user = User(email="test_content_chunk_relationship@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test"
        )
        db_session.add(channel)
        await db_session.flush()
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="test_123",
            title="Test",
            content_body="Content",
            author="Author",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        chunk1 = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=0,
            chunk_text="Chunk 1"
        )
        chunk2 = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=1,
            chunk_text="Chunk 2"
        )
        db_session.add_all([chunk1, chunk2])
        await db_session.commit()
        
        # Verify forward relationship (chunk → content_item)
        assert chunk1.content_item.id == content_item.id
        assert chunk1.content_item.title == "Test"
        
        # Verify reverse relationship (content_item → chunks)
        await db_session.refresh(content_item, ['chunks'])
        assert len(content_item.chunks) == 2
        assert content_item.chunks[0].chunk_index == 0
        assert content_item.chunks[1].chunk_index == 1
    
    async def test_content_chunk_unique_constraint(self, db_session):
        """Test that duplicate (content_item_id, chunk_index) is prevented."""
        user = User(email="test_content_chunk_unique_constraint@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test"
        )
        db_session.add(channel)
        await db_session.flush()
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="test_123",
            title="Test",
            content_body="Content",
            author="Author",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        chunk1 = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=0,
            chunk_text="First chunk"
        )
        db_session.add(chunk1)
        await db_session.commit()
        
        # Try to create duplicate
        chunk2 = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=0,  # Same index!
            chunk_text="Another chunk"
        )
        db_session.add(chunk2)
        
        with pytest.raises(IntegrityError):
            await db_session.commit()
    
    async def test_content_chunk_cascade_delete(self, db_session):
        """Test that deleting content item deletes its chunks."""
        user = User(email="test_content_chunk_cascade_delete@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test"
        )
        db_session.add(channel)
        await db_session.flush()
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="test_123",
            title="Test",
            content_body="Content",
            author="Author",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        chunk = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=0,
            chunk_text="Test chunk"
        )
        db_session.add(chunk)
        await db_session.commit()
        
        chunk_id = chunk.id
        
        # Delete content item
        await db_session.delete(content_item)
        await db_session.commit()
        
        # Verify chunk is also deleted
        result = await db_session.execute(
            select(ContentChunk).where(ContentChunk.id == chunk_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_content_chunk_properties(self, db_session):
        """Test ContentChunk property methods."""
        user = User(email="test_content_chunk_properties@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test"
        )
        db_session.add(channel)
        await db_session.flush()
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="test_123",
            title="Test",
            content_body="Content",
            author="Author",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Test pending chunk
        pending_chunk = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=0,
            chunk_text="Pending",
            processing_status="pending"
        )
        assert pending_chunk.needs_processing is True
        assert pending_chunk.is_processed is False
        
        # Test processed chunk
        processed_chunk = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=1,
            chunk_text="Processed",
            processing_status="processed"
        )
        assert processed_chunk.needs_processing is False
        assert processed_chunk.is_processed is True


@pytest.mark.asyncio
class TestConversationModel:
    """Test Conversation model functionality."""
    
    async def test_create_conversation(self, db_session):
        """Test creating a conversation with all fields."""
        user = User(
            email="test_conversation_create@example.com",
            name="Test User",
            timezone="UTC",
            is_active=True
        )
        db_session.add(user)
        await db_session.flush()
        
        conversation = Conversation(
            user_id=user.id,
            title="Test Conversation",
            is_active=True,
            archived=False,
            conversation_metadata={"filters": {"content_types": ["youtube"]}},
            message_count=0,
            total_tokens_used=0
        )
        db_session.add(conversation)
        await db_session.commit()
        
        # Verify
        assert conversation.id is not None
        assert conversation.user_id == user.id
        assert conversation.title == "Test Conversation"
        assert conversation.is_active is True
        assert conversation.archived is False
        assert conversation.conversation_metadata["filters"]["content_types"] == ["youtube"]
        assert conversation.message_count == 0
        assert conversation.total_tokens_used == 0
        assert conversation.created_at is not None
    
    async def test_conversation_relationship_to_user(self, db_session):
        """Test relationship between Conversation and User."""
        user = User(email="test_conversation_relationship_to_user@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        conv1 = Conversation(user_id=user.id, title="Conv 1")
        conv2 = Conversation(user_id=user.id, title="Conv 2")
        db_session.add_all([conv1, conv2])
        await db_session.commit()
        
        # Verify forward relationship
        assert conv1.user.id == user.id
        assert conv1.user.email == "test_conversation_relationship_to_user@example.com"
        
        # Verify reverse relationship
        await db_session.refresh(user, ['conversations'])
        assert len(user.conversations) == 2
    
    async def test_conversation_cascade_delete_from_user(self, db_session):
        """Test that deleting user deletes their conversations."""
        user = User(email="test_conversation_cascade_delete_from_user@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        conversation = Conversation(user_id=user.id, title="Test")
        db_session.add(conversation)
        await db_session.commit()
        
        conv_id = conversation.id
        
        # Delete user
        await db_session.delete(user)
        await db_session.commit()
        
        # Verify conversation is deleted
        result = await db_session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_conversation_properties(self, db_session):
        """Test Conversation property methods."""
        user = User(email="test_conversation_properties@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        # Empty conversation
        empty_conv = Conversation(
            user_id=user.id,
            title="Empty",
            message_count=0
        )
        assert empty_conv.is_empty is True
        assert empty_conv.is_ongoing is True  # Active and not archived
        
        # Conversation with messages
        conv_with_messages = Conversation(
            user_id=user.id,
            title="With Messages",
            message_count=5
        )
        assert conv_with_messages.is_empty is False
        
        # Archived conversation
        archived_conv = Conversation(
            user_id=user.id,
            title="Archived",
            is_active=True,
            archived=True
        )
        assert archived_conv.is_ongoing is False  # Archived


@pytest.mark.asyncio
class TestMessageModel:
    """Test Message model functionality."""
    
    async def test_create_message(self, db_session):
        """Test creating a message with all fields."""
        user = User(email="test_message_create@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        conversation = Conversation(user_id=user.id, title="Test")
        db_session.add(conversation)
        await db_session.flush()
        
        message = Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="What are React hooks?",
            prompt_tokens=5,
            completion_tokens=0,
            total_tokens=5,
            message_metadata={"query_type": "factual"}
        )
        db_session.add(message)
        await db_session.commit()
        
        # Verify
        assert message.id is not None
        assert message.conversation_id == conversation.id
        assert message.role == MessageRole.USER
        assert message.content == "What are React hooks?"
        assert message.prompt_tokens == 5
        assert message.total_tokens == 5
        assert message.message_metadata["query_type"] == "factual"
    
    async def test_message_relationship_to_conversation(self, db_session):
        """Test relationship between Message and Conversation."""
        user = User(email="test_message_relationship_to_conversation@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        conversation = Conversation(user_id=user.id, title="Test")
        db_session.add(conversation)
        await db_session.flush()
        
        msg1 = Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="Question 1"
        )
        msg2 = Message(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content="Answer 1"
        )
        db_session.add_all([msg1, msg2])
        await db_session.commit()
        
        # Verify forward relationship
        assert msg1.conversation.id == conversation.id
        assert msg1.conversation.title == "Test"
        
        # Verify reverse relationship
        await db_session.refresh(conversation, ['messages'])
        assert len(conversation.messages) == 2
        assert conversation.messages[0].role == MessageRole.USER
        assert conversation.messages[1].role == MessageRole.ASSISTANT
    
    async def test_message_cascade_delete_from_conversation(self, db_session):
        """Test that deleting conversation deletes its messages."""
        user = User(email="test_message_cascade_delete_from_conversation@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        conversation = Conversation(user_id=user.id, title="Test")
        db_session.add(conversation)
        await db_session.flush()
        
        message = Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="Test message"
        )
        db_session.add(message)
        await db_session.commit()
        
        msg_id = message.id
        
        # Delete conversation
        await db_session.delete(conversation)
        await db_session.commit()
        
        # Verify message is deleted
        result = await db_session.execute(
            select(Message).where(Message.id == msg_id)
        )
        assert result.scalar_one_or_none() is None
    
    async def test_message_properties(self, db_session):
        """Test Message property methods."""
        user = User(email="test_message_properties@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        conversation = Conversation(user_id=user.id, title="Test")
        db_session.add(conversation)
        await db_session.flush()
        
        # User message
        user_msg = Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="Question"
        )
        assert user_msg.is_user_message is True
        assert user_msg.is_assistant_message is False
        assert user_msg.has_citations is False
        
        # Assistant message
        assistant_msg = Message(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content="Answer"
        )
        assert assistant_msg.is_user_message is False
        assert assistant_msg.is_assistant_message is True
    
    async def test_message_chunk_relationship(self, db_session):
        """Test many-to-many relationship between Message and ContentChunk."""
        # Create dependencies
        user = User(email="test_message_chunk_relationship@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test"
        )
        db_session.add(channel)
        await db_session.flush()
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="test_123",
            title="Test",
            content_body="Content",
            author="Author",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        chunk1 = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=0,
            chunk_text="Chunk 1"
        )
        chunk2 = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=1,
            chunk_text="Chunk 2"
        )
        db_session.add_all([chunk1, chunk2])
        await db_session.flush()
        
        conversation = Conversation(user_id=user.id, title="Test")
        db_session.add(conversation)
        await db_session.flush()
        
        # Create assistant message with retrieved chunks
        message = Message(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content="Based on the retrieved content...",
            retrieved_chunks=[chunk1, chunk2]
        )
        db_session.add(message)
        await db_session.commit()
        
        # Verify relationship
        await db_session.refresh(message, ['retrieved_chunks'])
        assert len(message.retrieved_chunks) == 2
        assert message.has_citations is True
        assert message.retrieved_chunks[0].chunk_text == "Chunk 1"
        assert message.retrieved_chunks[1].chunk_text == "Chunk 2"



class TestMessageRole:
    """Test MessageRole enum."""
    
    def test_message_role_values(self):
        """Test MessageRole enum values."""
        assert MessageRole.USER.value == "user"
        assert MessageRole.ASSISTANT.value == "assistant"
        assert MessageRole.SYSTEM.value == "system"
    
    def test_message_role_string_conversion(self):
        """Test MessageRole __str__ method."""
        assert str(MessageRole.USER) == "user"
        assert str(MessageRole.ASSISTANT) == "assistant"
        assert str(MessageRole.SYSTEM) == "system"

