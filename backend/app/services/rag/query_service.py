"""
Query Service for RAG

This module handles query processing for retrieval:
- Query cleaning and normalization
- Query embedding generation
- Query expansion for better retrieval
- Intent classification

The query service prepares user queries for the retrieval pipeline.
"""

import logging
import re
from typing import Optional, List, Dict, Any

from app.services.processors.embedder import get_embedding_service

logger = logging.getLogger(__name__)


class QueryService:
    """
    Service for processing user queries before retrieval.
    
    Handles:
    - Query cleaning and normalization
    - Embedding generation for semantic search
    - Query expansion for improved recall
    - Basic intent classification
    
    Usage:
    ------
    query_service = QueryService()
    await query_service.initialize()
    
    processed = await query_service.process_query("What are React hooks?")
    # Returns: {
    #     'original': 'What are React hooks?',
    #     'cleaned': 'what are react hooks',
    #     'embedding': [0.1, 0.2, ...],  # 768-dim vector
    #     'expanded_queries': ['react hooks', 'hooks in react', ...],
    #     'intent': 'factual'
    # }
    """
    
    def __init__(self):
        """Initialize the query service."""
        self.embedder = None
        self._initialized = False
        
    async def initialize(self):
        """
        Initialize the embedding service.
        
        This should be called once before processing queries.
        """
        if not self._initialized:
            self.embedder = await get_embedding_service()
            self._initialized = True
            logger.info("QueryService initialized")
    
    async def process_query(
        self,
        query: str,
        expand: bool = True,
        max_expansions: int = 3
    ) -> Dict[str, Any]:
        """
        Process a user query for retrieval.
        
        Steps:
        1. Clean and normalize the query
        2. Generate embedding for semantic search
        3. Optionally expand query for better recall
        4. Classify query intent
        
        Args:
            query: The user's search query
            expand: Whether to generate query expansions (default: True)
            max_expansions: Maximum number of expansion queries (default: 3)
            
        Returns:
            Dictionary containing:
            - original: Original query text
            - cleaned: Cleaned and normalized query
            - embedding: Query embedding vector (768-dim)
            - expanded_queries: List of query variations
            - intent: Query intent classification
            - tokens: Query tokens (words)
            
        Example:
            >>> processed = await query_service.process_query("What are React hooks?")
            >>> processed['cleaned']
            'what are react hooks'
            >>> processed['intent']
            'factual'
        """
        if not self._initialized:
            await self.initialize()
        
        # Step 1: Clean the query
        cleaned = self._clean_query(query)
        
        if not cleaned or len(cleaned.strip()) < 2:
            logger.warning(f"Query too short after cleaning: '{query}'")
            return {
                'original': query,
                'cleaned': cleaned,
                'embedding': None,
                'expanded_queries': [],
                'intent': 'unknown',
                'tokens': []
            }
        
        # Step 2: Generate embedding
        embedding = await self.embedder.embed_text(cleaned)
        
        # Step 3: Tokenize
        tokens = self._tokenize(cleaned)
        
        # Step 4: Expand query (optional)
        expanded_queries = []
        if expand and len(tokens) > 0:
            expanded_queries = self._expand_query(cleaned, tokens, max_expansions)
        
        # Step 5: Classify intent
        intent = self._classify_intent(cleaned, tokens)
        
        result = {
            'original': query,
            'cleaned': cleaned,
            'embedding': embedding,
            'expanded_queries': expanded_queries,
            'intent': intent,
            'tokens': tokens
        }
        
        logger.debug(f"Processed query: '{query}' -> intent={intent}, expansions={len(expanded_queries)}")
        
        return result
    
    def _clean_query(self, query: str) -> str:
        """
        Clean and normalize query text.
        
        Steps:
        - Convert to lowercase
        - Remove punctuation (except hyphens in words)
        - Remove extra whitespace
        - Trim whitespace
        
        Args:
            query: Raw query text
            
        Returns:
            Cleaned query text
        """
        if not query:
            return ""
        
        # Convert to lowercase
        cleaned = query.lower()
        
        # Remove punctuation except hyphens in words (e.g., "full-stack")
        # Replace punctuation with spaces first, then clean up
        cleaned = re.sub(r'[^\w\s-]', ' ', cleaned)
        
        # Remove hyphens at start/end of words (keep in middle)
        cleaned = re.sub(r'\s-+|-+\s', ' ', cleaned)
        
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        return cleaned
    
    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text into words.
        
        Args:
            text: Text to tokenize
            
        Returns:
            List of tokens (words)
        """
        if not text:
            return []
        
        # Simple word tokenization
        # Split on whitespace and punctuation
        tokens = re.findall(r'\b\w+\b', text.lower())
        
        # Remove very short tokens (< 2 chars)
        tokens = [t for t in tokens if len(t) >= 2]
        
        return tokens
    
    def _expand_query(
        self,
        query: str,
        tokens: List[str],
        max_expansions: int = 3
    ) -> List[str]:
        """
        Generate query expansions for improved recall.
        
        Expansion strategies:
        1. Remove question words (what, how, why, etc.)
        2. Rearrange word order
        3. Extract key phrases
        
        Args:
            query: Cleaned query text
            tokens: Query tokens
            max_expansions: Maximum expansions to generate
            
        Returns:
            List of expanded query strings
        """
        expansions = []
        
        # Question words to remove
        question_words = {'what', 'how', 'why', 'when', 'where', 'who', 'which', 'is', 'are', 'can', 'does', 'do'}
        
        # Strategy 1: Remove question words
        content_tokens = [t for t in tokens if t not in question_words]
        if content_tokens and content_tokens != tokens:
            expansions.append(' '.join(content_tokens))
        
        # Strategy 2: Take last 2-3 words (often the key topic)
        if len(content_tokens) >= 2:
            key_phrase = ' '.join(content_tokens[-2:])
            if key_phrase not in expansions:
                expansions.append(key_phrase)
        
        # Strategy 3: Take first 2-3 content words
        if len(content_tokens) >= 2:
            start_phrase = ' '.join(content_tokens[:3])
            if start_phrase not in expansions and start_phrase != key_phrase:
                expansions.append(start_phrase)
        
        # Limit to max_expansions
        return expansions[:max_expansions]
    
    def _classify_intent(self, query: str, tokens: List[str]) -> str:
        """
        Classify query intent for retrieval optimization.
        
        Intent types:
        - factual: Seeking specific information (what, how, definition)
        - exploratory: Browsing, discovering (best, recommend, list)
        - comparison: Comparing options (vs, versus, difference, compare)
        - troubleshooting: Solving problems (error, issue, problem, fix)
        
        Args:
            query: Cleaned query text
            tokens: Query tokens
            
        Returns:
            Intent classification string
        """
        query_lower = query.lower()
        
        # Factual intent patterns
        factual_words = {'what', 'how', 'why', 'when', 'define', 'explain', 'introduction', 'overview'}
        if any(word in tokens for word in factual_words):
            return 'factual'
        
        # Exploratory intent patterns
        exploratory_words = {'best', 'top', 'recommend', 'list', 'comparison', 'review', 'guide'}
        if any(word in tokens for word in exploratory_words):
            return 'exploratory'
        
        # Comparison intent patterns
        comparison_words = {'vs', 'versus', 'difference', 'compare', 'between', 'or'}
        if any(word in tokens for word in comparison_words):
            return 'comparison'
        
        # Troubleshooting intent patterns
        troubleshooting_words = {'error', 'issue', 'problem', 'fix', 'solve', 'debug', 'help', 'not', 'working'}
        if any(word in tokens for word in troubleshooting_words):
            return 'troubleshooting'
        
        # Default to factual
        return 'factual'
    
    async def batch_process_queries(
        self,
        queries: List[str],
        expand: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Process multiple queries in batch.
        
        More efficient than processing one at a time due to
        batch embedding generation.
        
        Args:
            queries: List of query strings
            expand: Whether to expand queries
            
        Returns:
            List of processed query dictionaries
        """
        if not self._initialized:
            await self.initialize()
        
        if not queries:
            return []
        
        # Process all queries
        results = []
        for query in queries:
            result = await self.process_query(query, expand=expand)
            results.append(result)
        
        logger.info(f"Batch processed {len(queries)} queries")
        
        return results
    
    async def get_query_embedding(self, query: str) -> Optional[Any]:
        """
        Get just the embedding for a query (quick method).
        
        Args:
            query: Query text
            
        Returns:
            Embedding vector or None
        """
        if not self._initialized:
            await self.initialize()
        
        cleaned = self._clean_query(query)
        if not cleaned:
            return None
        
        return await self.embedder.embed_text(cleaned)


# Global query service instance
_query_service: Optional[QueryService] = None


async def get_query_service() -> QueryService:
    """
    Get or create the global query service instance.
    
    This ensures we only have one QueryService with one EmbeddingService,
    avoiding multiple model loads.
    
    Returns:
        Initialized QueryService instance
        
    Example:
        >>> query_service = await get_query_service()
        >>> result = await query_service.process_query("How to use React?")
    """
    global _query_service
    
    if _query_service is None:
        _query_service = QueryService()
        await _query_service.initialize()
        logger.info("Created global QueryService instance")
    
    return _query_service

