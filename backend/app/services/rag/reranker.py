"""
Cross-Encoder Reranker for RAG

This module implements cross-encoder reranking to improve retrieval quality.
A cross-encoder jointly encodes the query and each candidate chunk to compute
a more accurate relevance score.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2
- Fast inference (92M parameters)
- Trained on MS MARCO passage ranking
- Better context understanding than bi-encoders
"""

import logging
from typing import List, Dict, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    Rerank retrieved chunks using a cross-encoder model.
    
    Cross-Encoder vs Bi-Encoder:
    ----------------------------
    - Bi-Encoder (what we use for retrieval):
      * Encodes query and documents separately
      * Fast: can pre-compute document embeddings
      * Lower quality: no query-document interaction
    
    - Cross-Encoder (what we use for reranking):
      * Encodes query + document together
      * Slow: must encode each pair individually
      * Higher quality: captures query-document interaction
    
    Pipeline:
    ---------
    1. Retrieval: Use bi-encoder to get top 50-100 candidates (fast)
    2. Reranking: Use cross-encoder to rerank top 5-10 (slow but accurate)
    
    Usage:
    ------
    reranker = CrossEncoderReranker()
    await reranker.initialize()
    
    reranked = await reranker.rerank(
        query="What are React hooks?",
        candidates=retrieval_results,
        top_k=5
    )
    """
    
    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        device: str = "cpu",
        batch_size: int = 8
    ):
        """
        Initialize the reranker.
        
        Args:
            model_name: Cross-encoder model name (default: ms-marco-MiniLM)
            device: Device to use: cpu, cuda, or mps (default: cpu)
            batch_size: Batch size for inference (default: 8)
        """
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        
        self.model = None
        self._initialized = False
        
        logger.info(f"CrossEncoderReranker configured with model={model_name}, device={device}")
    
    async def initialize(self):
        """
        Initialize the cross-encoder model.
        
        This loads the model into memory. Should be called once before reranking.
        Model is loaded lazily to avoid loading it when not needed.
        """
        if self._initialized:
            return
        
        import asyncio
        import concurrent.futures
        from sentence_transformers import CrossEncoder
        import torch
        
        def _load_model():
            """Load model in thread pool to avoid blocking."""
            # Validate device
            device = self.device
            if device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU")
                device = "cpu"
            elif device == "mps" and not torch.backends.mps.is_available():
                logger.warning("MPS not available, falling back to CPU")
                device = "cpu"
            
            # Load model
            model = CrossEncoder(
                self.model_name,
                max_length=512,
                device=device
            )
            
            logger.info(f"Loaded cross-encoder model on {device}")
            return model
        
        # Load model in thread pool (model loading can be slow)
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            self.model = await loop.run_in_executor(executor, _load_model)
        
        self._initialized = True
        logger.info("CrossEncoderReranker initialized")
    
    async def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Rerank candidate chunks using cross-encoder.
        
        Args:
            query: Query text
            candidates: List of candidate chunks from retrieval
                Each candidate should have at least 'chunk_text'
            top_k: Number of top results to return (default: 5)
            
        Returns:
            Reranked list of chunks with updated scores:
            [{
                ...original_fields...,
                'rerank_score': 0.95,
                'rerank_rank': 1
            }, ...]
            
        Example:
            >>> candidates = await retriever.retrieve(...)  # Get 50 candidates
            >>> top_5 = await reranker.rerank(query, candidates, top_k=5)
        """
        if not self._initialized:
            await self.initialize()
        
        if not candidates:
            logger.warning("No candidates to rerank")
            return []
        
        # Limit candidates to a reasonable number (reranking is expensive)
        max_candidates = min(len(candidates), 20)  # Rerank top 20 at most
        candidates = candidates[:max_candidates]
        
        logger.info(f"Reranking {len(candidates)} candidates with query: '{query[:50]}...'")
        
        # Prepare query-document pairs
        pairs = [(query, candidate['chunk_text']) for candidate in candidates]
        
        # Score pairs
        import asyncio
        import concurrent.futures
        
        def _score_pairs():
            """Score pairs in thread pool to avoid blocking."""
            scores = self.model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False
            )
            return scores
        
        # Run scoring in thread pool
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            scores = await loop.run_in_executor(executor, _score_pairs)
        
        # Add scores to candidates
        for candidate, score in zip(candidates, scores):
            candidate['rerank_score'] = float(score)
        
        # Sort by rerank score
        reranked = sorted(
            candidates,
            key=lambda x: x['rerank_score'],
            reverse=True
        )[:top_k]
        
        # Add rerank ranks
        for i, candidate in enumerate(reranked, 1):
            candidate['rerank_rank'] = i
        
        logger.info(f"Reranked to top {len(reranked)} results")
        
        return reranked
    
    async def rerank_batch(
        self,
        queries: List[str],
        candidates_list: List[List[Dict[str, Any]]],
        top_k: int = 5
    ) -> List[List[Dict[str, Any]]]:
        """
        Rerank multiple query-candidates pairs in batch.
        
        Args:
            queries: List of query strings
            candidates_list: List of candidate lists (one per query)
            top_k: Number of top results per query
            
        Returns:
            List of reranked results (one list per query)
        """
        if not self._initialized:
            await self.initialize()
        
        if len(queries) != len(candidates_list):
            raise ValueError("Number of queries must match number of candidate lists")
        
        results = []
        for query, candidates in zip(queries, candidates_list):
            reranked = await self.rerank(query, candidates, top_k)
            results.append(reranked)
        
        return results
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        Get information about the loaded model.
        
        Returns:
            Dictionary with model information
        """
        return {
            'model_name': self.model_name,
            'device': self.device,
            'batch_size': self.batch_size,
            'initialized': self._initialized
        }


# Global reranker instance
_reranker: Optional[CrossEncoderReranker] = None


async def get_reranker(
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    device: str = "cpu"
) -> CrossEncoderReranker:
    """
    Get or create the global reranker instance.
    
    This ensures we only have one reranker model loaded in memory.
    
    Args:
        model_name: Cross-encoder model name
        device: Device to use (cpu, cuda, mps)
        
    Returns:
        Initialized CrossEncoderReranker instance
        
    Example:
        >>> reranker = await get_reranker()
        >>> results = await reranker.rerank(query, candidates, top_k=5)
    """
    global _reranker
    
    if _reranker is None:
        _reranker = CrossEncoderReranker(model_name=model_name, device=device)
        await _reranker.initialize()
        logger.info("Created global CrossEncoderReranker instance")
    
    return _reranker


async def shutdown_reranker():
    """
    Shutdown and cleanup the global reranker instance.
    
    Call this when shutting down the application to free resources.
    """
    global _reranker
    
    if _reranker is not None:
        # Clean up model
        _reranker.model = None
        _reranker._initialized = False
        _reranker = None
        logger.info("Shut down global CrossEncoderReranker instance")

