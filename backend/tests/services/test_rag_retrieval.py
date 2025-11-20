"""
Tests for RAG Retrieval Services

This module tests:
- Query Service (query processing, embedding)
- Hybrid Retriever (semantic + keyword + metadata search)
- Cross-Encoder Reranker
"""

import pytest
import pytest_asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta
import numpy as np

from app.models.content import ContentItem, ContentChunk, Channel, ProcessingStatus, ContentSourceType
from app.services.rag.query_service import QueryService, get_query_service
from app.services.rag.retriever import HybridRetriever, create_retriever
from app.services.rag.reranker import CrossEncoderReranker, get_reranker


# ========================================
# Fixtures
# ========================================

@pytest.fixture
def mock_embedder():
    """Mock embedder service."""
    embedder = Mock()
    embedder.embed_text = AsyncMock(return_value=np.random.rand(768))
    embedder.embed_texts_batch = AsyncMock(return_value=[np.random.rand(768) for _ in range(3)])
    return embedder


@pytest_asyncio.fixture
async def test_channel(db_session):
    """Create a test channel."""
    channel = Channel(
        name="Test Channel",
        source_type=ContentSourceType.YOUTUBE,
        source_identifier="test_channel_001",
        is_active=True
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return channel


@pytest_asyncio.fixture
async def test_content_item(db_session, test_channel):
    """Create a test content item."""
    content_item = ContentItem(
        channel_id=test_channel.id,
        external_id="test_video_001",
        title="Introduction to React Hooks",
        content_body="React Hooks are functions that let you use state and other React features.",
        author="Test Author",
        published_at=datetime.now(timezone.utc),
        processing_status=ProcessingStatus.PROCESSED,
        content_metadata={
            "video_id": "test_video_001",
            "view_count": 10000,
            "like_count": 500
        }
    )
    db_session.add(content_item)
    await db_session.commit()
    await db_session.refresh(content_item)
    return content_item


@pytest_asyncio.fixture
async def test_chunks(db_session, test_content_item):
    """Create test content chunks."""
    chunks = []
    for i in range(3):
        chunk = ContentChunk(
            content_item_id=test_content_item.id,
            chunk_index=i,
            chunk_text=f"This is test chunk {i} about React hooks and state management.",
            chunk_metadata={"start_time": i * 30},
            embedding=np.random.rand(768).tolist(),
            processing_status=ProcessingStatus.PROCESSED
        )
        db_session.add(chunk)
        chunks.append(chunk)
    
    await db_session.commit()
    for chunk in chunks:
        await db_session.refresh(chunk)
    
    return chunks


# ========================================
# Test QueryService
# ========================================

@pytest.mark.asyncio
async def test_query_service_initialization():
    """Test query service initialization."""
    with patch('app.services.rag.query_service.get_embedding_service') as mock_get_embedder:
        mock_embedder = Mock()
        mock_get_embedder.return_value = mock_embedder
        
        service = QueryService()
        await service.initialize()
        
        assert service._initialized is True
        assert service.embedder == mock_embedder
        mock_get_embedder.assert_called_once()


@pytest.mark.asyncio
async def test_query_service_process_query(mock_embedder):
    """Test query processing."""
    with patch('app.services.rag.query_service.get_embedding_service', return_value=mock_embedder):
        service = QueryService()
        await service.initialize()
        
        result = await service.process_query("What are React hooks?")
        
        assert result['original'] == "What are React hooks?"
        assert result['cleaned'] == "what are react hooks"
        assert result['embedding'] is not None
        assert len(result['expanded_queries']) > 0
        assert result['intent'] in ['factual', 'exploratory', 'comparison', 'troubleshooting']
        assert len(result['tokens']) > 0


@pytest.mark.asyncio
async def test_query_service_clean_query(mock_embedder):
    """Test query cleaning."""
    with patch('app.services.rag.query_service.get_embedding_service', return_value=mock_embedder):
        service = QueryService()
        await service.initialize()
        
        # Test whitespace removal
        result = await service.process_query("  What   are   React hooks?  ")
        assert result['cleaned'] == "what are react hooks"
        
        # Test lowercase
        result = await service.process_query("WHAT ARE REACT HOOKS?")
        assert result['cleaned'] == "what are react hooks"


@pytest.mark.asyncio
async def test_query_service_query_expansion(mock_embedder):
    """Test query expansion."""
    with patch('app.services.rag.query_service.get_embedding_service', return_value=mock_embedder):
        service = QueryService()
        await service.initialize()
        
        result = await service.process_query("What are React hooks?", expand=True)
        
        # Should have expansions
        assert len(result['expanded_queries']) > 0
        
        # Expansions should be different from original
        for expansion in result['expanded_queries']:
            assert expansion != result['cleaned']
        
        # Should remove question words
        assert any('react hooks' in exp for exp in result['expanded_queries'])


@pytest.mark.asyncio
async def test_query_service_intent_classification(mock_embedder):
    """Test intent classification."""
    with patch('app.services.rag.query_service.get_embedding_service', return_value=mock_embedder):
        service = QueryService()
        await service.initialize()
        
        # Test factual
        result = await service.process_query("What is React?")
        assert result['intent'] == 'factual'
        
        # Test exploratory
        result = await service.process_query("Best React libraries")
        assert result['intent'] == 'exploratory'
        
        # Test comparison
        result = await service.process_query("React vs Vue")
        assert result['intent'] == 'comparison'
        
        # Test troubleshooting
        result = await service.process_query("React error not working")
        assert result['intent'] == 'troubleshooting'


@pytest.mark.asyncio
async def test_query_service_short_query(mock_embedder):
    """Test handling of very short queries."""
    with patch('app.services.rag.query_service.get_embedding_service', return_value=mock_embedder):
        service = QueryService()
        await service.initialize()
        
        result = await service.process_query("a")
        
        assert result['original'] == "a"
        assert result['embedding'] is None
        assert len(result['expanded_queries']) == 0


@pytest.mark.asyncio
async def test_query_service_batch_processing(mock_embedder):
    """Test batch query processing."""
    with patch('app.services.rag.query_service.get_embedding_service', return_value=mock_embedder):
        service = QueryService()
        await service.initialize()
        
        queries = ["What is React?", "How to use Vue?", "Angular tutorial"]
        results = await service.batch_process_queries(queries)
        
        assert len(results) == 3
        for i, result in enumerate(results):
            assert result['original'] == queries[i]
            assert result['cleaned'] is not None


# ========================================
# Test HybridRetriever
# ========================================

@pytest.mark.asyncio
async def test_hybrid_retriever_initialization(db_session):
    """Test hybrid retriever initialization."""
    retriever = HybridRetriever(db_session)
    
    assert retriever.db == db_session
    assert retriever.semantic_weight == 0.6
    assert retriever.keyword_weight == 0.3
    assert retriever.metadata_weight == 0.1


@pytest.mark.asyncio
async def test_hybrid_retriever_weight_normalization(db_session):
    """Test weight normalization."""
    # Weights don't sum to 1.0
    retriever = HybridRetriever(
        db_session,
        semantic_weight=0.5,
        keyword_weight=0.3,
        metadata_weight=0.05
    )
    
    # Should be normalized
    total = retriever.semantic_weight + retriever.keyword_weight + retriever.metadata_weight
    assert abs(total - 1.0) < 0.01


@pytest.mark.skip(reason="Integration test - requires full database setup with pgvector")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_hybrid_retriever_semantic_search(db_session, test_chunks):
    """Test semantic search.
    
    Note: This is an integration test that requires:
    - PostgreSQL with pgvector extension
    - Proper vector indexes
    - Full database setup with migrations
    """
    
    retriever = HybridRetriever(db_session)
    
    query_embedding = np.random.rand(768)
    results = await retriever._semantic_search(
        query_embedding,
        top_k=10
    )
    
    # Should return results
    assert len(results) > 0
    
    # Each result should have required fields
    for result in results:
        assert 'chunk_id' in result
        assert 'chunk_text' in result
        assert 'semantic_score' in result
        assert 0.0 <= result['semantic_score'] <= 1.0


@pytest.mark.skip(reason="Integration test - requires full database setup with FTS")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_hybrid_retriever_keyword_search(db_session, test_chunks):
    """Test keyword search.
    
    Note: This is an integration test that requires:
    - PostgreSQL full-text search setup
    - GIN indexes on tsvector columns
    - Full database setup with migrations
    """
    
    retriever = HybridRetriever(db_session)
    
    results = await retriever._keyword_search(
        "React hooks",
        top_k=10
    )
    
    # Should return results
    assert len(results) > 0
    
    # Each result should have required fields
    for result in results:
        assert 'chunk_id' in result
        assert 'chunk_text' in result
        assert 'keyword_score' in result
        assert 0.0 <= result['keyword_score'] <= 1.0


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_hybrid_retriever_full_retrieval(db_session, test_chunks):
    """Test full hybrid retrieval.
    
    Note: This is an integration test that requires full database setup.
    """
    
    retriever = HybridRetriever(db_session)
    
    query_embedding = np.random.rand(768)
    results = await retriever.retrieve(
        query_embedding=query_embedding,
        query_text="React hooks",
        top_k=5
    )
    
    # Should return results
    assert len(results) <= 5
    
    # Results should be sorted by final_score
    if len(results) > 1:
        for i in range(len(results) - 1):
            assert results[i]['final_score'] >= results[i+1]['final_score']
    
    # Each result should have all scores
    for result in results:
        assert 'semantic_score' in result
        assert 'keyword_score' in result
        assert 'metadata_score' in result
        assert 'final_score' in result
        assert 'rank' in result


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_hybrid_retriever_content_type_filter(db_session, test_chunks):
    """Test content type filtering.
    
    Note: This is an integration test that requires full database setup.
    """
    
    retriever = HybridRetriever(db_session)
    
    query_embedding = np.random.rand(768)
    results = await retriever.retrieve(
        query_embedding=query_embedding,
        query_text="React hooks",
        content_types=['youtube'],
        top_k=10
    )
    
    # All results should be YouTube
    for result in results:
        assert result['source_type'] == 'youtube'


@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_hybrid_retriever_date_range_filter(db_session, test_chunks):
    """Test date range filtering.
    
    Note: This is an integration test that requires full database setup.
    """
    
    retriever = HybridRetriever(db_session)
    
    query_embedding = np.random.rand(768)
    results = await retriever.retrieve(
        query_embedding=query_embedding,
        query_text="React hooks",
        date_range_days=7,  # Last 7 days
        top_k=10
    )
    
    # All results should be recent
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for result in results:
        assert result['published_at'] >= cutoff


@pytest.mark.asyncio
async def test_hybrid_retriever_metadata_scoring(db_session):
    """Test metadata scoring."""
    retriever = HybridRetriever(db_session)
    
    # Test with YouTube content
    result = {
        'published_at': datetime.now(timezone.utc) - timedelta(days=1),  # Recent
        'content_metadata': {
            'view_count': 100000,
            'like_count': 5000
        },
        'source_type': 'youtube'
    }
    
    score = retriever._calculate_metadata_score(result)
    
    assert 0.0 <= score <= 1.0
    assert score > 0.5  # Should be high for recent + popular content


# ========================================
# Test CrossEncoderReranker
# ========================================

@pytest.mark.asyncio
async def test_reranker_initialization():
    """Test reranker initialization."""
    with patch('sentence_transformers.CrossEncoder') as mock_cross_encoder:
        mock_model = Mock()
        mock_cross_encoder.return_value = mock_model
        
        reranker = CrossEncoderReranker()
        await reranker.initialize()
        
        assert reranker._initialized is True
        assert reranker.model == mock_model


@pytest.mark.asyncio
async def test_reranker_rerank():
    """Test reranking."""
    with patch('sentence_transformers.CrossEncoder') as mock_cross_encoder:
        mock_model = Mock()
        mock_model.predict = Mock(return_value=np.array([0.9, 0.7, 0.5]))
        mock_cross_encoder.return_value = mock_model
        
        reranker = CrossEncoderReranker()
        await reranker.initialize()
        
        candidates = [
            {'chunk_text': 'Text 1', 'chunk_id': 1},
            {'chunk_text': 'Text 2', 'chunk_id': 2},
            {'chunk_text': 'Text 3', 'chunk_id': 3}
        ]
        
        results = await reranker.rerank("query", candidates, top_k=2)
        
        # Should return top 2
        assert len(results) == 2
        
        # Should be sorted by rerank_score
        assert results[0]['rerank_score'] == 0.9
        assert results[1]['rerank_score'] == 0.7
        
        # Should have ranks
        assert results[0]['rerank_rank'] == 1
        assert results[1]['rerank_rank'] == 2


@pytest.mark.asyncio
async def test_reranker_empty_candidates():
    """Test reranking with empty candidates."""
    with patch('sentence_transformers.CrossEncoder') as mock_cross_encoder:
        mock_model = Mock()
        mock_cross_encoder.return_value = mock_model
        
        reranker = CrossEncoderReranker()
        await reranker.initialize()
        
        results = await reranker.rerank("query", [], top_k=5)
        
        assert len(results) == 0


@pytest.mark.asyncio
async def test_reranker_batch_rerank():
    """Test batch reranking."""
    with patch('sentence_transformers.CrossEncoder') as mock_cross_encoder:
        mock_model = Mock()
        mock_model.predict = Mock(return_value=np.array([0.9, 0.7]))
        mock_cross_encoder.return_value = mock_model
        
        reranker = CrossEncoderReranker()
        await reranker.initialize()
        
        queries = ["query1", "query2"]
        candidates_list = [
            [{'chunk_text': 'Text 1', 'chunk_id': 1}, {'chunk_text': 'Text 2', 'chunk_id': 2}],
            [{'chunk_text': 'Text 3', 'chunk_id': 3}, {'chunk_text': 'Text 4', 'chunk_id': 4}]
        ]
        
        results = await reranker.rerank_batch(queries, candidates_list, top_k=2)
        
        assert len(results) == 2
        assert len(results[0]) == 2
        assert len(results[1]) == 2


# ========================================
# Test Integration
# ========================================

@pytest.mark.skip(reason="Integration test - requires full database setup")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_retrieval_pipeline(db_session, test_chunks, mock_embedder):
    """Test full retrieval pipeline: query -> retrieve -> rerank.
    
    Note: This is an integration test that requires full database setup.
    """
    
    with patch('app.services.rag.query_service.get_embedding_service', return_value=mock_embedder), \
         patch('sentence_transformers.CrossEncoder') as mock_cross_encoder:
        
        # Setup mocks
        mock_model = Mock()
        mock_model.predict = Mock(return_value=np.array([0.9, 0.8, 0.7]))
        mock_cross_encoder.return_value = mock_model
        
        # Step 1: Process query
        query_service = QueryService()
        await query_service.initialize()
        query_result = await query_service.process_query("What are React hooks?")
        
        assert query_result['embedding'] is not None
        
        # Step 2: Retrieve
        retriever = HybridRetriever(db_session)
        retrieval_results = await retriever.retrieve(
            query_embedding=query_result['embedding'],
            query_text=query_result['cleaned'],
            top_k=10
        )
        
        assert len(retrieval_results) > 0
        
        # Step 3: Rerank
        reranker = CrossEncoderReranker()
        await reranker.initialize()
        final_results = await reranker.rerank(
            query_result['original'],
            retrieval_results,
            top_k=5
        )
        
        assert len(final_results) <= 5
        assert all('rerank_score' in r for r in final_results)
        assert all('rerank_rank' in r for r in final_results)

