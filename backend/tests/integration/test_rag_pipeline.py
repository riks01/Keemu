"""
Integration tests for complete RAG pipeline.

Tests the full end-to-end RAG system:
- Content → Chunking → Embedding → Storage
- Query → Retrieval → Reranking → Generation → Response
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.models.user import User, UserPreferences, UpdateFrequency, SummaryLength
from app.models.content import Channel, ContentItem, ContentChunk, ProcessingStatus, ContentSourceType
from app.models.conversation import Conversation, Message, MessageRole
from app.core.security import get_password_hash, create_access_token
from datetime import timedelta, datetime, timezone


pytestmark = pytest.mark.integration


# ================================
# Fixtures
# ================================

@pytest_asyncio.fixture
async def test_user_with_content(db_session: AsyncSession):
    """Create test user with content and chunks."""
    # Create user
    user = User(
        email="rag_test@example.com",
        name="RAG Test User",
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
        source_identifier="test_channel",
        name="Test Channel",
        thumbnail_url="https://youtube.com/test",
        subscriber_count=0,
        is_active=True
    )
    db_session.add(channel)
    await db_session.flush()
    
    # Create content item
    content = ContentItem(
        channel_id=channel.id,
        title="React Hooks Tutorial",
        external_id="react_hooks_tutorial_video",
        author="Test Author",
        published_at=datetime.now(timezone.utc),
        content_body="React hooks are functions that let you use state and lifecycle features in functional components. The most common hooks are useState and useEffect.",
        processing_status=ProcessingStatus.PROCESSED,
        content_metadata={
            "duration": 600,
            "views": 10000,
            "language": "en"
        }
    )
    db_session.add(content)
    await db_session.flush()
    
    # Create chunks with embeddings (mock embeddings)
    import numpy as np
    chunk1 = ContentChunk(
        content_item_id=content.id,
        chunk_index=0,
        chunk_text="React hooks are functions that let you use state and lifecycle features in functional components.",
        embedding=np.random.rand(384).tolist(),
        processing_status=ProcessingStatus.PROCESSED,
        chunk_metadata={"start_time": 0, "end_time": 30}
    )
    chunk2 = ContentChunk(
        content_item_id=content.id,
        chunk_index=1,
        chunk_text="The most common hooks are useState and useEffect. useState lets you add state to functional components.",
        embedding=np.random.rand(384).tolist(),
        processing_status=ProcessingStatus.PROCESSED,
        chunk_metadata={"start_time": 30, "end_time": 60}
    )
    db_session.add_all([chunk1, chunk2])
    await db_session.commit()
    await db_session.refresh(user)
    
    # Create auth token
    token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=30)
    )
    
    return {
        "user": user,
        "headers": {"Authorization": f"Bearer {token}"},
        "channel": channel,
        "content": content,
        "chunks": [chunk1, chunk2]
    }


# ================================
# Content Processing Pipeline Tests
# ================================

@pytest.mark.asyncio
async def test_content_chunking_pipeline(db_session: AsyncSession):
    """Test content is properly chunked."""
    from app.services.processors.chunker import ContentChunker
    from app.models.content import ContentItem, Channel, ContentSourceType

    # Mock channel and content item
    class MockChannel:
        source_type = ContentSourceType.BLOG

    class MockContentItem:
        def __init__(self, content_body, channel):
            self.content_body = content_body
            self.channel = channel
            self.content_metadata = {}

    # Create mock content item with .channel.source_type property
    content_text = """
    React is a JavaScript library for building user interfaces.
    It was created by Facebook and is now maintained by Meta and a community of developers.
    React uses a component-based architecture where UIs are broken into reusable pieces.
    """
    content_item = MockContentItem(content_body=content_text, channel=MockChannel())

    chunker = ContentChunker()
    chunks = await chunker.chunk_content(content_item)

    assert len(chunks) > 0
    assert all("text" in chunk for chunk in chunks)
    assert all("index" in chunk for chunk in chunks)
    assert all("metadata" in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_content_embedding_pipeline(db_session: AsyncSession):
    """Test content chunks are properly embedded."""
    from app.services.processors.embedder import get_embedding_service
    
    # Initialize embedding service
    embedder = await get_embedding_service()
    
    # Embed some text
    test_texts = [
        "React hooks are powerful",
        "Vue.js is a progressive framework"
    ]
    
    embeddings = await embedder.embed_texts_batch(test_texts)
    
    assert len(embeddings) == 2
    assert all(len(emb) == 384 for emb in embeddings)  # 384 dimensions
    
    # Shutdown
    from app.services.processors.embedder import shutdown_embedding_service
    await shutdown_embedding_service()


# ================================
# RAG Chat API Tests
# ================================

@pytest.mark.asyncio
async def test_create_conversation(client: AsyncClient, test_user_with_content: dict):
    """Test creating a new conversation."""
    headers = test_user_with_content["headers"]
    
    response = await client.post(
        "/api/v1/chat/conversations",
        headers=headers,
        json={"title": "Test Conversation"}
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Conversation"
    assert data["user_id"] == test_user_with_content["user"].id


@pytest.mark.asyncio
async def test_list_conversations(client: AsyncClient, test_user_with_content: dict):
    """Test listing user conversations."""
    headers = test_user_with_content["headers"]
    
    # Create a conversation first
    await client.post(
        "/api/v1/chat/conversations",
        headers=headers,
        json={"title": "Test Conversation"}
    )
    
    # List conversations
    response = await client.get(
        "/api/v1/chat/conversations",
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert len(data["conversations"]) >= 1
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_conversation_messages(client: AsyncClient, test_user_with_content: dict, db_session: AsyncSession):
    """Test getting conversation messages."""
    headers = test_user_with_content["headers"]
    user = test_user_with_content["user"]
    
    # Create conversation
    conversation = Conversation(
        user_id=user.id,
        title="Test Chat"
    )
    db_session.add(conversation)
    await db_session.flush()
    
    # Add messages
    message1 = Message(
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content="What are React hooks?"
    )
    message2 = Message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content="React hooks are functions that let you use state."
    )
    db_session.add_all([message1, message2])
    await db_session.commit()
    
    # Get messages
    response = await client.get(
        f"/api/v1/chat/conversations/{conversation.id}/messages",
        headers=headers
    )
    
    assert response.status_code == 200
    messages = response.json()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_delete_conversation(client: AsyncClient, test_user_with_content: dict, db_session: AsyncSession):
    """Test deleting a conversation."""
    headers = test_user_with_content["headers"]
    user = test_user_with_content["user"]
    
    # Create conversation
    conversation = Conversation(
        user_id=user.id,
        title="Test Chat to Delete"
    )
    db_session.add(conversation)
    await db_session.commit()
    
    # Delete it
    response = await client.delete(
        f"/api/v1/chat/conversations/{conversation.id}",
        headers=headers
    )
    
    assert response.status_code == 204


# ================================
# Query Processing Tests
# ================================

@pytest.mark.asyncio
async def test_query_processing():
    """Test query processing service."""
    from app.services.rag.query_service import QueryService
    
    query_service = QueryService()
    await query_service.initialize()
    
    # Process a query
    result = await query_service.process_query("What are React hooks?")
    
    assert result["original"] == "What are React hooks?"
    assert result["cleaned"]
    assert result["embedding"] is not None
    assert len(result["embedding"]) == 384
    assert result["intent"] in ["factual", "exploratory", "comparison", "troubleshooting"]
    assert isinstance(result["expanded_queries"], list)
    
    # QueryService doesn't require explicit shutdown
    # await query_service.shutdown()


# ================================
# Retrieval Tests
# ================================

@pytest.mark.asyncio
async def test_hybrid_retrieval(db_session: AsyncSession, test_user_with_content: dict):
    """Test hybrid retrieval system."""
    from app.services.rag.retriever import HybridRetriever
    from app.services.rag.query_service import QueryService
    
    # Initialize services
    query_service = QueryService()
    await query_service.initialize()
    
    retriever = HybridRetriever(db_session)
    
    # Process query
    query_result = await query_service.process_query("What are React hooks?")
    
    # Retrieve
    results = await retriever.retrieve(
        query_embedding=query_result["embedding"],
        query_text=query_result["cleaned"],
        top_k=10
    )
    
    assert isinstance(results, list)
    # Results might be empty if embeddings aren't similar enough
    # That's OK for this test - we're testing the pipeline works
    
    # QueryService doesn't require explicit shutdown
    # await query_service.shutdown()


# ================================
# End-to-End RAG Tests (requires API keys)
# ================================

@pytest.mark.asyncio
@pytest.mark.skipif(
    True,  # Skip by default as it requires Anthropic API key
    reason="Requires Anthropic API key and will consume API credits"
)
async def test_full_rag_pipeline_with_generation(client: AsyncClient, test_user_with_content: dict, db_session: AsyncSession):
    """
    Test complete RAG pipeline with actual generation.
    
    This test is skipped by default as it:
    - Requires ANTHROPIC_API_KEY
    - Consumes API credits
    - Takes longer to run
    
    To run: pytest tests/integration/test_rag_pipeline.py::test_full_rag_pipeline_with_generation -v
    """
    headers = test_user_with_content["headers"]
    user = test_user_with_content["user"]
    
    # Create conversation
    conversation = Conversation(
        user_id=user.id,
        title="RAG Test"
    )
    db_session.add(conversation)
    await db_session.commit()
    
    # Send message (triggers full RAG pipeline)
    response = await client.post(
        f"/api/v1/chat/conversations/{conversation.id}/messages",
        headers=headers,
        json={
            "content": "What are React hooks?",
            "top_k_retrieval": 10,
            "top_k_rerank": 3
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert "content" in data
    assert "sources" in data
    assert data["role"] == "assistant"
    assert len(data["content"]) > 0


# ================================
# Performance Tests
# ================================

@pytest.mark.asyncio
async def test_query_performance():
    """Test query processing performance."""
    import time
    from app.services.rag.query_service import QueryService
    
    query_service = QueryService()
    await query_service.initialize()
    
    # Measure query processing time
    start = time.time()
    await query_service.process_query("What are React hooks?")
    duration = time.time() - start
    
    # Should be reasonably fast (< 2 seconds for embedding)
    assert duration < 2.0, f"Query processing took {duration:.2f}s (too slow)"
    
    # QueryService doesn't require explicit shutdown
    # await query_service.shutdown()


@pytest.mark.asyncio
async def test_retrieval_performance(db_session: AsyncSession, test_user_with_content: dict):
    """Test retrieval performance."""
    import time
    from app.services.rag.retriever import HybridRetriever
    import numpy as np
    
    retriever = HybridRetriever(db_session)
    
    # Use mock embedding
    query_embedding = np.random.rand(384).tolist()
    
    # Measure retrieval time
    start = time.time()
    await retriever.retrieve(
        query_embedding=query_embedding,
        query_text="test query",
        top_k=10
    )
    duration = time.time() - start
    
    # Should be fast (< 1 second for 10 results)
    assert duration < 1.0, f"Retrieval took {duration:.2f}s (too slow)"

