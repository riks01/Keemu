"""
Tests for RAG Generation Services

This module tests:
- RAG Generator (Claude integration)
- Conversation Service
- Context assembly and citations
"""

import pytest
import pytest_asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timezone
import numpy as np

from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.rag.generator import RAGGenerator, get_generator, create_generator
from app.services.rag.conversation_service import ConversationService, create_conversation_service


# ========================================
# Fixtures
# ========================================

@pytest_asyncio.fixture
async def test_user(db_session):
    """Create a test user."""
    from app.core.security import get_password_hash
    from app.models.user import UserPreferences, UpdateFrequency, SummaryLength
    
    user = User(
        email="test_chat@example.com",
        name="Test User",
        hashed_password=get_password_hash("testpass123"),
        timezone="UTC",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()
    
    # Create preferences (required)
    preferences = UserPreferences(
        user_id=user.id,
        update_frequency=UpdateFrequency.WEEKLY,
        summary_length=SummaryLength.STANDARD,
        email_notifications_enabled=True
    )
    db_session.add(preferences)
    await db_session.commit()
    await db_session.refresh(user)
    
    return user


@pytest.fixture
def sample_chunks():
    """Sample retrieved chunks for testing."""
    return [
        {
            'chunk_id': 1,
            'chunk_text': 'React hooks are functions that let you use state and other React features.',
            'content_item_id': 1,
            'content_title': 'Introduction to React Hooks',
            'content_author': 'Dan Abramov',
            'source_type': 'youtube',
            'channel_name': 'React Channel',
            'published_at': datetime.now(timezone.utc),
            'chunk_metadata': {'start_time': 120},
            'rerank_score': 0.95
        },
        {
            'chunk_id': 2,
            'chunk_text': 'useState is the most commonly used hook for managing state in function components.',
            'content_item_id': 1,
            'content_title': 'Introduction to React Hooks',
            'content_author': 'Dan Abramov',
            'source_type': 'youtube',
            'channel_name': 'React Channel',
            'published_at': datetime.now(timezone.utc),
            'chunk_metadata': {'start_time': 240},
            'rerank_score': 0.88
        },
        {
            'chunk_id': 3,
            'chunk_text': 'useEffect is used for side effects like data fetching and subscriptions.',
            'content_item_id': 2,
            'content_title': 'React Hooks Deep Dive',
            'content_author': 'Kent C. Dodds',
            'source_type': 'blog',
            'channel_name': 'Kent Blog',
            'published_at': datetime.now(timezone.utc),
            'chunk_metadata': {},
            'rerank_score': 0.82
        }
    ]


# ========================================
# Test RAGGenerator
# ========================================

@pytest.mark.asyncio
async def test_generator_initialization():
    """Test generator initialization."""
    # Mock API key in settings
    with patch('app.services.rag.generator.settings.ANTHROPIC_API_KEY', 'test-api-key'):
        generator = RAGGenerator(api_key='test-api-key')
        
        assert generator.api_key == 'test-api-key'
        assert generator.model == 'claude-3-5-sonnet-20241022'
        assert generator.max_tokens == 2048
        assert generator.temperature == 0.7


@pytest.mark.asyncio
async def test_generator_requires_api_key():
    """Test that generator requires API key."""
    with patch('app.services.rag.generator.settings.ANTHROPIC_API_KEY', None):
        with pytest.raises(ValueError, match="API key is required"):
            RAGGenerator()


@pytest.mark.asyncio
async def test_context_assembly(sample_chunks):
    """Test context assembly from chunks."""
    with patch('app.services.rag.generator.settings.ANTHROPIC_API_KEY', 'test-key'):
        generator = RAGGenerator(api_key='test-key')
        
        context = generator._assemble_context(sample_chunks, max_tokens=5000)
        
        assert isinstance(context, str)
        assert len(context) > 0
        assert '[Source 1]' in context
        assert '[Source 2]' in context
        assert '[Source 3]' in context
        assert 'React hooks are functions' in context


@pytest.mark.asyncio
async def test_context_truncation(sample_chunks):
    """Test context truncation when exceeding token limit."""
    with patch('app.services.rag.generator.settings.ANTHROPIC_API_KEY', 'test-key'):
        generator = RAGGenerator(api_key='test-key')
        
        # Use very small token limit
        context = generator._assemble_context(sample_chunks, max_tokens=100)
        
        # Should only include first chunk
        assert '[Source 1]' in context
        # May not include all chunks
        assert len(context) < 1000  # Reasonable upper bound


@pytest.mark.asyncio
async def test_build_system_prompt():
    """Test system prompt building."""
    with patch('app.services.rag.generator.settings.ANTHROPIC_API_KEY', 'test-key'):
        generator = RAGGenerator(api_key='test-key')
        
        # With citations
        prompt_with_citations = generator._build_system_prompt(include_citations=True)
        assert 'KeeMU' in prompt_with_citations
        assert 'cite your sources' in prompt_with_citations
        
        # Without citations
        prompt_without_citations = generator._build_system_prompt(include_citations=False)
        assert 'KeeMU' in prompt_without_citations
        assert 'cite your sources' not in prompt_without_citations


@pytest.mark.asyncio
async def test_build_user_message(sample_chunks):
    """Test user message building."""
    with patch('app.services.rag.generator.settings.ANTHROPIC_API_KEY', 'test-key'):
        generator = RAGGenerator(api_key='test-key')
        
        context = generator._assemble_context(sample_chunks)
        message = generator._build_user_message(
            query="What are React hooks?",
            context=context,
            chunks=sample_chunks
        )
        
        assert 'What are React hooks?' in message
        assert 'Context from your knowledge base' in message
        assert len(message) > 0


@pytest.mark.asyncio
async def test_extract_citations(sample_chunks):
    """Test citation extraction from answer."""
    with patch('app.services.rag.generator.settings.ANTHROPIC_API_KEY', 'test-key'):
        generator = RAGGenerator(api_key='test-key')
        
        answer = "React hooks [Source 1] are functions that let you use state [Source 2] and effects [Source 3]."
        citations = generator._extract_citations(answer, sample_chunks)
        
        assert 0 in citations  # Source 1 -> index 0
        assert 1 in citations  # Source 2 -> index 1
        assert 2 in citations  # Source 3 -> index 2


@pytest.mark.asyncio
async def test_build_sources_list(sample_chunks):
    """Test building sources list."""
    with patch('app.services.rag.generator.settings.ANTHROPIC_API_KEY', 'test-key'):
        generator = RAGGenerator(api_key='test-key')
        
        citation_indices = [0, 2]  # Cited chunks 0 and 2
        sources = generator._build_sources_list(sample_chunks, citation_indices)
        
        assert len(sources) == 2
        assert sources[0]['source_number'] == 1
        assert sources[0]['title'] == 'Introduction to React Hooks'
        assert sources[1]['source_number'] == 3
        assert sources[1]['title'] == 'React Hooks Deep Dive'


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires Anthropic API key and network access")
async def test_generate_response(sample_chunks):
    """Test full response generation.
    
    Note: This is an integration test that requires:
    - Valid Anthropic API key
    - Network access
    - Real API call
    """
    generator = RAGGenerator()  # Uses real API key from settings
    
    response = await generator.generate(
        query="What are React hooks?",
        chunks=sample_chunks,
        conversation_history=None,
        include_citations=True
    )
    
    assert 'answer' in response
    assert 'sources' in response
    assert 'model' in response
    assert 'tokens_used' in response
    assert len(response['answer']) > 0


# ========================================
# Test ConversationService
# ========================================

@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_conversation(db_session, test_user):
    """Test creating a conversation.
    
    Note: This is an integration test requiring full database setup.
    """
    service = ConversationService(db_session)
    
    conversation = await service.create_conversation(
        user_id=test_user.id,
        title="Test Conversation"
    )
    
    assert conversation.id is not None
    assert conversation.user_id == test_user.id
    assert conversation.title == "Test Conversation"
    assert conversation.created_at is not None


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_conversation_default_title(db_session, test_user):
    """Test creating conversation with default title."""
    service = ConversationService(db_session)
    
    conversation = await service.create_conversation(user_id=test_user.id)
    
    assert conversation.title == "New Conversation"


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_conversation(db_session, test_user):
    """Test getting a conversation."""
    service = ConversationService(db_session)
    
    # Create conversation
    created = await service.create_conversation(
        user_id=test_user.id,
        title="Test"
    )
    
    # Get conversation
    retrieved = await service.get_conversation(created.id, user_id=test_user.id)
    
    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.title == "Test"


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_conversation_wrong_user(db_session, test_user):
    """Test getting conversation with wrong user ID."""
    service = ConversationService(db_session)
    
    # Create conversation
    conversation = await service.create_conversation(user_id=test_user.id)
    
    # Try to get with wrong user ID
    retrieved = await service.get_conversation(conversation.id, user_id=999)
    
    assert retrieved is None


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_user_conversations(db_session, test_user):
    """Test listing user conversations."""
    service = ConversationService(db_session)
    
    # Create multiple conversations
    await service.create_conversation(user_id=test_user.id, title="Conv 1")
    await service.create_conversation(user_id=test_user.id, title="Conv 2")
    await service.create_conversation(user_id=test_user.id, title="Conv 3")
    
    # List conversations
    conversations = await service.list_user_conversations(user_id=test_user.id)
    
    assert len(conversations) == 3
    # Should be ordered by updated_at descending
    assert conversations[0].title == "Conv 3"


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_conversation(db_session, test_user):
    """Test deleting a conversation."""
    service = ConversationService(db_session)
    
    # Create conversation
    conversation = await service.create_conversation(user_id=test_user.id)
    
    # Delete conversation
    deleted = await service.delete_conversation(conversation.id, user_id=test_user.id)
    
    assert deleted is True
    
    # Verify it's gone
    retrieved = await service.get_conversation(conversation.id)
    assert retrieved is None


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_user_message(db_session, test_user):
    """Test adding a user message."""
    service = ConversationService(db_session)
    
    # Create conversation
    conversation = await service.create_conversation(user_id=test_user.id)
    
    # Add message
    message = await service.add_user_message(
        conversation_id=conversation.id,
        content="What are React hooks?"
    )
    
    assert message.id is not None
    assert message.conversation_id == conversation.id
    assert message.role == "user"
    assert message.content == "What are React hooks?"


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_assistant_message(db_session, test_user):
    """Test adding an assistant message."""
    service = ConversationService(db_session)
    
    # Create conversation
    conversation = await service.create_conversation(user_id=test_user.id)
    
    # Add assistant message
    sources = [{'title': 'Test Source'}]
    message = await service.add_assistant_message(
        conversation_id=conversation.id,
        content="React hooks are...",
        sources=sources,
        model="claude-3-5-sonnet",
        tokens_used=100
    )
    
    assert message.id is not None
    assert message.role == "assistant"
    assert message.content == "React hooks are..."
    assert message.metadata['sources'] == sources
    assert message.metadata['model'] == "claude-3-5-sonnet"
    assert message.metadata['tokens_used'] == 100


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_auto_generate_conversation_title(db_session, test_user):
    """Test auto-generating conversation title from first message."""
    service = ConversationService(db_session)
    
    # Create conversation with default title
    conversation = await service.create_conversation(user_id=test_user.id)
    assert conversation.title == "New Conversation"
    
    # Add first user message
    await service.add_user_message(
        conversation_id=conversation.id,
        content="What are React hooks and how do they work?"
    )
    
    # Add assistant response (this triggers title generation)
    await service.add_assistant_message(
        conversation_id=conversation.id,
        content="React hooks are..."
    )
    
    # Check title was updated
    updated_conv = await service.get_conversation(conversation.id)
    assert updated_conv.title != "New Conversation"
    assert "React hooks" in updated_conv.title


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_conversation_history(db_session, test_user):
    """Test getting conversation history."""
    service = ConversationService(db_session)
    
    # Create conversation with messages
    conversation = await service.create_conversation(user_id=test_user.id)
    
    await service.add_user_message(conversation.id, "Question 1")
    await service.add_assistant_message(conversation.id, "Answer 1")
    await service.add_user_message(conversation.id, "Question 2")
    await service.add_assistant_message(conversation.id, "Answer 2")
    
    # Get history
    history = await service.get_conversation_history(conversation.id)
    
    assert len(history) == 4
    assert history[0]['role'] == "user"
    assert history[0]['content'] == "Question 1"
    assert history[1]['role'] == "assistant"
    assert history[1]['content'] == "Answer 1"


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_conversation_history_for_llm(db_session, test_user):
    """Test getting conversation history formatted for LLM."""
    service = ConversationService(db_session)
    
    conversation = await service.create_conversation(user_id=test_user.id)
    
    await service.add_user_message(conversation.id, "Question")
    await service.add_assistant_message(conversation.id, "Answer", sources=[{'title': 'Test'}])
    
    # Get history for LLM (only role + content)
    history = await service.get_conversation_history(conversation.id, for_llm=True)
    
    assert len(history) == 2
    assert 'role' in history[0]
    assert 'content' in history[0]
    assert 'id' not in history[0]
    assert 'metadata' not in history[0]


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_conversation_title(db_session, test_user):
    """Test updating conversation title."""
    service = ConversationService(db_session)
    
    conversation = await service.create_conversation(user_id=test_user.id, title="Old Title")
    
    updated = await service.update_conversation_title(
        conversation_id=conversation.id,
        title="New Title",
        user_id=test_user.id
    )
    
    assert updated is True
    
    retrieved = await service.get_conversation(conversation.id)
    assert retrieved.title == "New Title"


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_conversation_count(db_session, test_user):
    """Test getting conversation count."""
    service = ConversationService(db_session)
    
    # Create conversations
    await service.create_conversation(user_id=test_user.id)
    await service.create_conversation(user_id=test_user.id)
    await service.create_conversation(user_id=test_user.id)
    
    count = await service.get_conversation_count(user_id=test_user.id)
    
    assert count == 3

