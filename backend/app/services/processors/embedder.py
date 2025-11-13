"""
Embedding Service

This module provides embedding generation using sentence-transformers.
Optimized for local inference with batch processing support.

Model: google/embeddinggemma-300m
- 768 dimensions
- Optimized for semantic search
- Good balance of speed and quality
- Free (no API costs)

Features:
---------
- Batch processing for efficiency
- CPU/CUDA/MPS device support
- Async processing with retry logic
- Embedding normalization for cosine similarity
- Progress tracking
- Error handling and fallbacks
"""

import asyncio
from typing import Any, Optional
import logging
import numpy as np
from sentence_transformers import SentenceTransformer
import torch

from app.core.config import settings


logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Service for generating embeddings using sentence-transformers.
    
    This service uses google/embeddinggemma-300m for generating 768-dimensional
    embeddings optimized for semantic search and RAG applications.
    
    Features:
    ---------
    - Batch processing (default: 32 texts per batch)
    - Device selection (CPU/CUDA/MPS)
    - Normalization for cosine similarity
    - Retry logic for failures
    - Async operation
    
    Usage:
    ------
    embedder = EmbeddingService()
    await embedder.initialize()
    
    # Single text
    embedding = await embedder.embed_text("What are React hooks?")
    
    # Batch processing
    embeddings = await embedder.embed_texts_batch([
        "Text 1",
        "Text 2",
        "Text 3"
    ])
    """
    
    def __init__(
        self,
        model_name: str = None,
        batch_size: int = None,
        device: str = None,
        normalize: bool = True
    ):
        """
        Initialize the embedding service.
        
        Args:
            model_name: Model name/path (default from settings)
            batch_size: Batch size for processing (default from settings)
            device: Device to use: cpu, cuda, mps (default from settings)
            normalize: Whether to normalize embeddings (default True)
        """
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        self.device = device or settings.EMBEDDING_DEVICE
        self.normalize = normalize
        
        self.model: Optional[SentenceTransformer] = None
        self._initialized = False
        
        # Validate device
        self._validate_device()
    
    def _validate_device(self) -> None:
        """Validate and adjust device setting based on availability."""
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA not available, falling back to CPU")
            self.device = "cpu"
        elif self.device == "mps" and not torch.backends.mps.is_available():
            logger.warning("MPS not available, falling back to CPU")
            self.device = "cpu"
    
    async def initialize(self) -> None:
        """
        Initialize the embedding model.
        
        Downloads model if not cached, loads into memory.
        Should be called once at application startup.
        
        Raises:
            Exception: If model loading fails
        """
        if self._initialized:
            logger.info("Embedding service already initialized")
            return
        
        try:
            logger.info(f"Loading embedding model: {self.model_name} on {self.device}")
            
            # Run model loading in thread pool (it's CPU-intensive)
            self.model = await asyncio.to_thread(
                SentenceTransformer,
                self.model_name,
                device=self.device
            )
            
            self._initialized = True
            
            logger.info(
                f"Embedding model loaded successfully. "
                f"Dimension: {self.get_embedding_dimension()}, "
                f"Device: {self.device}"
            )
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    
    def get_embedding_dimension(self) -> int:
        """
        Get the embedding dimension of the model.
        
        Returns:
            Embedding dimension (768 for embeddinggemma-300m)
        """
        if not self._initialized or self.model is None:
            return settings.EMBEDDING_DIMENSION  # Return configured dimension
        
        return self.model.get_sentence_embedding_dimension()
    
    async def embed_text(
        self,
        text: str,
        normalize: Optional[bool] = None,
        retry_on_error: bool = True
    ) -> list[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            normalize: Override default normalization setting
            retry_on_error: Whether to retry on error (default True)
            
        Returns:
            Embedding vector as list of floats (768 dimensions)
            
        Raises:
            RuntimeError: If service not initialized
            Exception: If embedding generation fails after retries
        """
        if not self._initialized:
            raise RuntimeError("Embedding service not initialized. Call initialize() first.")
        
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            # Return zero vector for empty text
            return [0.0] * self.get_embedding_dimension()
        
        use_normalize = normalize if normalize is not None else self.normalize
        
        try:
            # Generate embedding in thread pool
            embedding = await asyncio.to_thread(
                self._generate_single_embedding,
                text,
                use_normalize
            )
            return embedding.tolist()
        
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            if retry_on_error:
                logger.info("Retrying embedding generation...")
                await asyncio.sleep(1)  # Brief delay before retry
                return await self.embed_text(text, normalize, retry_on_error=False)
            else:
                raise
    
    def _generate_single_embedding(self, text: str, normalize: bool) -> np.ndarray:
        """
        Generate embedding (sync, runs in thread pool).
        
        Args:
            text: Text to embed
            normalize: Whether to normalize
            
        Returns:
            Embedding as numpy array
        """
        embedding = self.model.encode(
            text,
            normalize_embeddings=normalize,
            show_progress_bar=False
        )
        return embedding
    
    async def embed_texts_batch(
        self,
        texts: list[str],
        normalize: Optional[bool] = None,
        show_progress: bool = False
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in batches.
        
        This is more efficient than calling embed_text multiple times
        as it batches requests to the model.
        
        Args:
            texts: List of texts to embed
            normalize: Override default normalization setting
            show_progress: Show progress bar (default False)
            
        Returns:
            List of embedding vectors (each is 768-dimensional)
            
        Raises:
            RuntimeError: If service not initialized
        """
        if not self._initialized:
            raise RuntimeError("Embedding service not initialized. Call initialize() first.")
        
        if not texts:
            return []
        
        use_normalize = normalize if normalize is not None else self.normalize
        
        # Filter out empty texts
        valid_texts = []
        valid_indices = []
        for i, text in enumerate(texts):
            if text and text.strip():
                valid_texts.append(text)
                valid_indices.append(i)
        
        if not valid_texts:
            # All texts are empty, return zero vectors
            dim = self.get_embedding_dimension()
            return [[0.0] * dim for _ in texts]
        
        try:
            # Generate embeddings in thread pool (batched)
            embeddings = await asyncio.to_thread(
                self._generate_batch_embeddings,
                valid_texts,
                use_normalize,
                show_progress
            )
            
            # Convert to list and handle empty texts
            result = []
            valid_idx = 0
            for i in range(len(texts)):
                if i in valid_indices:
                    result.append(embeddings[valid_idx].tolist())
                    valid_idx += 1
                else:
                    # Empty text, return zero vector
                    result.append([0.0] * self.get_embedding_dimension())
            
            return result
        
        except Exception as e:
            logger.error(f"Error in batch embedding generation: {e}")
            raise
    
    def _generate_batch_embeddings(
        self,
        texts: list[str],
        normalize: bool,
        show_progress: bool
    ) -> np.ndarray:
        """
        Generate batch embeddings (sync, runs in thread pool).
        
        Args:
            texts: List of texts
            normalize: Whether to normalize
            show_progress: Show progress bar
            
        Returns:
            Embeddings as numpy array (shape: [len(texts), embedding_dim])
        """
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=normalize,
            show_progress_bar=show_progress,
            convert_to_numpy=True
        )
        return embeddings
    
    async def embed_chunks(
        self,
        chunks: list[dict[str, Any]],
        text_key: str = "text"
    ) -> list[dict[str, Any]]:
        """
        Generate embeddings for a list of chunk dictionaries.
        
        Adds 'embedding' key to each chunk dictionary.
        
        Args:
            chunks: List of chunk dictionaries (must have text_key)
            text_key: Key containing text to embed (default "text")
            
        Returns:
            Chunks with embeddings added
        """
        if not chunks:
            return []
        
        # Extract texts
        texts = [chunk.get(text_key, "") for chunk in chunks]
        
        # Generate embeddings in batch
        embeddings = await self.embed_texts_batch(texts)
        
        # Add embeddings to chunks
        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding
        
        return chunks
    
    async def compute_similarity(
        self,
        embedding1: list[float],
        embedding2: list[float]
    ) -> float:
        """
        Compute cosine similarity between two embeddings.
        
        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector
            
        Returns:
            Cosine similarity score (0-1)
        """
        # Convert to numpy arrays
        emb1 = np.array(embedding1)
        emb2 = np.array(embedding2)
        
        # Compute cosine similarity
        # If embeddings are normalized, this is just dot product
        if self.normalize:
            similarity = float(np.dot(emb1, emb2))
        else:
            # Manual cosine similarity calculation
            dot_product = np.dot(emb1, emb2)
            norm1 = np.linalg.norm(emb1)
            norm2 = np.linalg.norm(emb2)
            similarity = float(dot_product / (norm1 * norm2))
        
        return similarity
    
    async def find_most_similar(
        self,
        query_embedding: list[float],
        candidate_embeddings: list[list[float]],
        top_k: int = 5
    ) -> list[tuple[int, float]]:
        """
        Find most similar embeddings to query.
        
        Args:
            query_embedding: Query embedding vector
            candidate_embeddings: List of candidate embeddings
            top_k: Number of top results to return
            
        Returns:
            List of (index, similarity_score) tuples, sorted by score (descending)
        """
        if not candidate_embeddings:
            return []
        
        # Compute similarities
        similarities = []
        for i, candidate in enumerate(candidate_embeddings):
            sim = await self.compute_similarity(query_embedding, candidate)
            similarities.append((i, sim))
        
        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Return top k
        return similarities[:top_k]
    
    async def shutdown(self) -> None:
        """
        Shutdown the embedding service and free resources.
        
        Should be called at application shutdown.
        """
        if self.model is not None:
            # Clear CUDA cache if using GPU
            if self.device == "cuda":
                torch.cuda.empty_cache()
            
            # Delete model from memory
            del self.model
            self.model = None
        
        self._initialized = False
        logger.info("Embedding service shut down")


# ========================================
# Global Instance Management
# ========================================

_embedding_service: Optional[EmbeddingService] = None


async def get_embedding_service() -> EmbeddingService:
    """
    Get or create the global embedding service instance.
    
    This ensures we only load the model once across the application.
    
    Returns:
        Initialized EmbeddingService instance
    """
    global _embedding_service
    
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
        await _embedding_service.initialize()
    
    return _embedding_service


async def shutdown_embedding_service() -> None:
    """
    Shutdown the global embedding service.
    
    Should be called at application shutdown.
    """
    global _embedding_service
    
    if _embedding_service is not None:
        await _embedding_service.shutdown()
        _embedding_service = None

