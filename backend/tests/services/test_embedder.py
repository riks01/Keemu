"""
Tests for EmbeddingService.

This test module verifies:
1. Service initialization
2. Single text embedding
3. Batch embedding
4. Similarity computation
5. Error handling
6. Device selection

Note: These tests may download the embedding model on first run (~300MB).
"""

import pytest
import numpy as np

from app.services.processors.embedder import (
    EmbeddingService,
    get_embedding_service,
    shutdown_embedding_service
)


@pytest.mark.asyncio
class TestEmbeddingServiceBasics:
    """Test basic EmbeddingService functionality."""
    
    async def test_initialization(self):
        """Test service initialization."""
        service = EmbeddingService()
        assert not service._initialized
        
        await service.initialize()
        assert service._initialized
        assert service.model is not None
        
        await service.shutdown()
    
    async def test_get_embedding_dimension(self):
        """Test getting embedding dimension."""
        service = EmbeddingService()
        
        # Before initialization
        dim_before = service.get_embedding_dimension()
        assert dim_before == 384  # Default from settings
        
        # After initialization
        await service.initialize()
        dim_after = service.get_embedding_dimension()
        assert dim_after == 384  # granite-embedding-107m-multilingual dimension
        
        await service.shutdown()
    
    async def test_device_validation(self):
        """Test device validation."""
        # CPU should always work
        service_cpu = EmbeddingService(device="cpu")
        assert service_cpu.device == "cpu"
        
        # CUDA/MPS may fall back to CPU if not available
        service_cuda = EmbeddingService(device="cuda")
        assert service_cuda.device in ("cuda", "cpu")
        
        service_mps = EmbeddingService(device="mps")
        assert service_mps.device in ("mps", "cpu")


@pytest.mark.asyncio
class TestSingleTextEmbedding:
    """Test single text embedding generation."""
    
    async def test_embed_single_text(self):
        """Test embedding a single text."""
        service = EmbeddingService()
        await service.initialize()
        
        text = "React hooks are a powerful feature."
        embedding = await service.embed_text(text)
        
        # Verify embedding properties
        assert isinstance(embedding, list)
        assert len(embedding) == 384
        assert all(isinstance(x, float) for x in embedding)
        
        # Check that embedding is not all zeros
        assert any(x != 0.0 for x in embedding)
        
        await service.shutdown()
    
    async def test_embed_empty_text(self):
        """Test embedding empty text."""
        service = EmbeddingService()
        await service.initialize()
        
        embedding = await service.embed_text("")
        
        # Should return zero vector for empty text
        assert isinstance(embedding, list)
        assert len(embedding) == 384
        assert all(x == 0.0 for x in embedding)
        
        await service.shutdown()
    
    async def test_embed_without_initialization(self):
        """Test that embedding without initialization raises error."""
        service = EmbeddingService()
        
        with pytest.raises(RuntimeError, match="not initialized"):
            await service.embed_text("test")
    
    async def test_embed_with_normalization(self):
        """Test embedding with normalization."""
        service = EmbeddingService(normalize=True)
        await service.initialize()
        
        text = "React hooks are useful."
        embedding = await service.embed_text(text)
        
        # Normalized embeddings should have unit length (L2 norm ≈ 1)
        norm = np.linalg.norm(np.array(embedding))
        assert abs(norm - 1.0) < 0.01  # Allow small floating point error
        
        await service.shutdown()


@pytest.mark.asyncio
class TestBatchEmbedding:
    """Test batch embedding generation."""
    
    async def test_embed_batch(self):
        """Test embedding multiple texts in batch."""
        service = EmbeddingService(batch_size=2)
        await service.initialize()
        
        texts = [
            "React hooks are great.",
            "Vue composition API is similar.",
            "Angular has dependency injection."
        ]
        
        embeddings = await service.embed_texts_batch(texts)
        
        # Verify batch results
        assert isinstance(embeddings, list)
        assert len(embeddings) == 3
        
        for embedding in embeddings:
            assert isinstance(embedding, list)
            assert len(embedding) == 384
            assert any(x != 0.0 for x in embedding)
        
        await service.shutdown()
    
    async def test_embed_empty_batch(self):
        """Test embedding empty batch."""
        service = EmbeddingService()
        await service.initialize()
        
        embeddings = await service.embed_texts_batch([])
        assert embeddings == []
        
        await service.shutdown()
    
    async def test_embed_batch_with_empty_texts(self):
        """Test batch embedding with some empty texts."""
        service = EmbeddingService()
        await service.initialize()
        
        texts = [
            "Valid text",
            "",
            "Another valid text",
            "   ",  # Whitespace only
            "Final text"
        ]
        
        embeddings = await service.embed_texts_batch(texts)
        
        # Should have embeddings for all texts
        assert len(embeddings) == 5
        
        # Valid texts should have non-zero embeddings
        assert any(x != 0.0 for x in embeddings[0])
        assert any(x != 0.0 for x in embeddings[2])
        assert any(x != 0.0 for x in embeddings[4])
        
        # Empty texts should have zero embeddings
        assert all(x == 0.0 for x in embeddings[1])
        assert all(x == 0.0 for x in embeddings[3])
        
        await service.shutdown()
    
    async def test_embed_chunks(self):
        """Test embedding chunk dictionaries."""
        service = EmbeddingService()
        await service.initialize()
        
        chunks = [
            {"index": 0, "text": "First chunk about React."},
            {"index": 1, "text": "Second chunk about hooks."},
            {"index": 2, "text": "Third chunk about components."}
        ]
        
        result_chunks = await service.embed_chunks(chunks)
        
        # Should have same number of chunks
        assert len(result_chunks) == 3
        
        # Each chunk should now have an embedding
        for chunk in result_chunks:
            assert "embedding" in chunk
            assert isinstance(chunk["embedding"], list)
            assert len(chunk["embedding"]) == 384
        
        await service.shutdown()


@pytest.mark.asyncio
class TestSimilarityComputation:
    """Test similarity computation."""
    
    async def test_compute_similarity_identical(self):
        """Test similarity between identical embeddings."""
        service = EmbeddingService(normalize=True)
        await service.initialize()
        
        text = "React hooks"
        embedding = await service.embed_text(text)
        
        # Identical embeddings should have similarity ≈ 1.0
        similarity = await service.compute_similarity(embedding, embedding)
        assert abs(similarity - 1.0) < 0.01
        
        await service.shutdown()
    
    async def test_compute_similarity_similar_texts(self):
        """Test similarity between similar texts."""
        service = EmbeddingService(normalize=True)
        await service.initialize()
        
        text1 = "React hooks are powerful"
        text2 = "React hooks are useful"
        
        emb1 = await service.embed_text(text1)
        emb2 = await service.embed_text(text2)
        
        similarity = await service.compute_similarity(emb1, emb2)
        
        # Similar texts should have high similarity (> 0.7)
        assert similarity > 0.7
        
        await service.shutdown()
    
    async def test_compute_similarity_different_texts(self):
        """Test similarity between very different texts."""
        service = EmbeddingService(normalize=True)
        await service.initialize()
        
        text1 = "React hooks for state management"
        text2 = "Cooking pasta with tomato sauce"
        
        emb1 = await service.embed_text(text1)
        emb2 = await service.embed_text(text2)
        
        similarity = await service.compute_similarity(emb1, emb2)
        
        # Different texts should have low similarity (< 0.5)
        assert similarity < 0.5
        
        await service.shutdown()
    
    async def test_find_most_similar(self):
        """Test finding most similar embeddings."""
        service = EmbeddingService()
        await service.initialize()
        
        # Query
        query = "React hooks"
        query_emb = await service.embed_text(query)
        
        # Candidates
        candidates = [
            "Vue composition API",  # Somewhat similar
            "React hooks tutorial",  # Very similar
            "Cooking recipes",  # Not similar
            "useState hook example"  # Similar
        ]
        
        candidate_embs = await service.embed_texts_batch(candidates)
        
        # Find top 2 similar
        results = await service.find_most_similar(
            query_emb,
            candidate_embs,
            top_k=2
        )
        
        # Should return 2 results
        assert len(results) == 2
        
        # Results should be tuples of (index, score)
        for idx, score in results:
            assert isinstance(idx, int)
            assert isinstance(score, float)
            assert 0 <= idx < len(candidates)
            assert 0 <= score <= 1
        
        # Results should be sorted by score (descending)
        assert results[0][1] >= results[1][1]
        
        # "React hooks tutorial" (index 1) should be most similar
        assert results[0][0] == 1
        
        await service.shutdown()


@pytest.mark.asyncio
class TestGlobalInstance:
    """Test global instance management."""
    
    async def test_get_embedding_service(self):
        """Test getting global service instance."""
        # First call initializes
        service1 = await get_embedding_service()
        assert service1 is not None
        assert service1._initialized
        
        # Second call returns same instance
        service2 = await get_embedding_service()
        assert service2 is service1
        
        # Cleanup
        await shutdown_embedding_service()
    
    async def test_shutdown_embedding_service(self):
        """Test shutting down global service."""
        # Get service
        service = await get_embedding_service()
        assert service._initialized
        
        # Shutdown
        await shutdown_embedding_service()
        
        # Service should be shut down
        # (We can't directly check the global variable, but next call will reinitialize)


@pytest.mark.asyncio
class TestErrorHandling:
    """Test error handling and edge cases."""
    
    async def test_retry_on_error(self):
        """Test retry logic on error."""
        service = EmbeddingService()
        await service.initialize()
        
        # Normal embedding should work
        text = "Test text"
        embedding = await service.embed_text(text, retry_on_error=True)
        assert len(embedding) == 384
        
        await service.shutdown()
    
    async def test_double_initialization(self):
        """Test that double initialization is handled."""
        service = EmbeddingService()
        
        await service.initialize()
        assert service._initialized
        
        # Second initialization should be a no-op
        await service.initialize()
        assert service._initialized
        
        await service.shutdown()
    
    async def test_shutdown_and_reinitialize(self):
        """Test shutting down and reinitializing."""
        service = EmbeddingService()
        
        # Initialize
        await service.initialize()
        assert service._initialized
        
        # Shutdown
        await service.shutdown()
        assert not service._initialized
        assert service.model is None
        
        # Reinitialize
        await service.initialize()
        assert service._initialized
        assert service.model is not None
        
        await service.shutdown()

