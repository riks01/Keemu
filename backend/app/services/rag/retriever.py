"""
Hybrid Retriever for RAG

This module implements multi-stage hybrid retrieval combining:
1. Semantic search (pgvector cosine similarity)
2. Keyword search (PostgreSQL full-text search)
3. Metadata filtering and boosting (recency, engagement, preferences)

The retriever returns ranked chunks ready for reranking and generation.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import numpy as np

from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.content import ContentChunk, ContentItem, Channel, ProcessingStatus, UserSubscription
from app.models.user import User
from app.services.processors.text_search import TextSearchService
from typing import Union
logger = logging.getLogger(__name__)


class HybridRetriever:
    """
    Hybrid retrieval combining semantic, keyword, and metadata signals.
    
    Retrieval Pipeline:
    -------------------
    1. Semantic Search (60% weight)
       - Uses query embedding + pgvector cosine similarity
       - Finds semantically similar chunks
    
    2. Keyword Search (30% weight)
       - Uses PostgreSQL ts_rank with tsvector
       - Finds lexically matching chunks
    
    3. Metadata Boosting (10% weight)
       - Recency: Newer content ranked higher
       - Engagement: High views/scores ranked higher
       - User preferences: Subscribed channels ranked higher
    
    4. Score Fusion
       - Combines all signals into final score
       - Applies normalization
    
    Usage:
    ------
    retriever = HybridRetriever(db_session)
    
    results = await retriever.retrieve(
        query_embedding=[0.1, 0.2, ...],
        query_text="What are React hooks?",
        user_id=123,
        top_k=50
    )
    """
    
    def __init__(
        self,
        db: AsyncSession,
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.3,
        metadata_weight: float = 0.1
    ):
        """
        Initialize the hybrid retriever.
        
        Args:
            db: Database session
            semantic_weight: Weight for semantic similarity (default: 0.6)
            keyword_weight: Weight for keyword matching (default: 0.3)
            metadata_weight: Weight for metadata signals (default: 0.1)
        """
        self.db = db
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.metadata_weight = metadata_weight
        self.text_search = TextSearchService()
        
        # Validate weights sum to 1.0
        total_weight = semantic_weight + keyword_weight + metadata_weight
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(
                f"Weights sum to {total_weight}, not 1.0. "
                f"Normalizing: semantic={semantic_weight/total_weight:.2f}, "
                f"keyword={keyword_weight/total_weight:.2f}, "
                f"metadata={metadata_weight/total_weight:.2f}"
            )
            self.semantic_weight = semantic_weight / total_weight
            self.keyword_weight = keyword_weight / total_weight
            self.metadata_weight = metadata_weight / total_weight
    
    async def retrieve(
        self,
        query_embedding: np.ndarray,
        query_text: str,
        user_id: Optional[int] = None,
        top_k: int = 50,
        content_types: Optional[List[str]] = None,
        date_range_days: Optional[int] = None,
        min_score: float = 0.1
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant chunks using hybrid search.
        
        Args:
            query_embedding: Query embedding vector (384-dim)
            query_text: Original query text for keyword search
            user_id: User ID for personalization (optional)
            top_k: Number of results to return (default: 50)
            content_types: Filter by content types (youtube, reddit, blog)
            date_range_days: Only retrieve content from last N days
            min_score: Minimum score threshold (default: 0.1)
            
        Returns:
            List of chunk dictionaries with scores, sorted by relevance:
            [{
                'chunk_id': 123,
                'chunk_text': '...',
                'chunk_metadata': {...},
                'content_item_id': 456,
                'content_title': '...',
                'content_author': '...',
                'channel_name': '...',
                'source_type': 'youtube',
                'published_at': datetime(...),
                'semantic_score': 0.85,
                'keyword_score': 0.72,
                'metadata_score': 0.60,
                'final_score': 0.78,
                'rank': 1
            }, ...]
        """
        logger.info(
            f"Hybrid retrieval: user_id={user_id}, top_k={top_k}, "
            f"content_types={content_types}, date_range={date_range_days}"
        )
        
        # Step 1: Semantic search
        semantic_results = await self._semantic_search(
            query_embedding,
            top_k=top_k * 2,  # Get more candidates
            content_types=content_types,
            date_range_days=date_range_days,
            user_id=user_id
        )
        
        logger.debug(f"Semantic search returned {len(semantic_results)} results")
        
        # Step 2: Keyword search
        keyword_results = await self._keyword_search(
            query_text,
            top_k=top_k * 2,  # Get more candidates
            content_types=content_types,
            date_range_days=date_range_days,
            user_id=user_id
        )
        
        logger.debug(f"Keyword search returned {len(keyword_results)} results")
        
        # Step 3: Merge and score
        merged_results = self._merge_and_score(
            semantic_results,
            keyword_results,
            user_id
        )
        
        # Step 4: Filter by minimum score
        filtered_results = [r for r in merged_results if r['final_score'] >= min_score]
        
        # Step 5: Sort by final score and limit to top_k
        sorted_results = sorted(
            filtered_results,
            key=lambda x: x['final_score'],
            reverse=True
        )[:top_k]
        
        # Step 6: Add ranks
        for i, result in enumerate(sorted_results, 1):
            result['rank'] = i
        
        logger.info(f"Retrieved {len(sorted_results)} chunks (after filtering and ranking)")
        
        return sorted_results
    
    async def _semantic_search(
        self,
        query_embedding: Union[List[float], List[List[float]]],
        top_k: int = 100,
        content_types: Optional[List[str]] = None,
        date_range_days: Optional[int] = None,
        user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic search using pgvector cosine similarity.
        
        Args:
            query_embedding: Query embedding list of floats
            top_k: Number of results
            content_types: Filter by content types
            date_range_days: Filter by date range
            user_id: User ID for filtering
            
        Returns:
            List of chunk dictionaries with semantic scores
        """
        # Build the query
        # Use cosine distance (1 - cosine_similarity)
        # Lower distance = higher similarity
        query = select(
            ContentChunk.id.label('chunk_id'),
            ContentChunk.chunk_text,
            ContentChunk.chunk_metadata,
            ContentChunk.content_item_id,
            ContentItem.title.label('content_title'),
            ContentItem.author.label('content_author'),
            ContentItem.published_at,
            ContentItem.content_metadata.label('content_metadata'),
            Channel.name.label('channel_name'),
            Channel.source_type,
            # Cosine distance (lower is better, so we'll convert to similarity)
            ContentChunk.embedding.cosine_distance(query_embedding).label('distance')
        ).select_from(ContentChunk).join(
            ContentItem, ContentChunk.content_item_id == ContentItem.id
        ).join(
            Channel, ContentItem.channel_id == Channel.id
        ).where(
            and_(
                ContentChunk.processing_status == ProcessingStatus.PROCESSED,
                ContentChunk.embedding.isnot(None)
            )
        )
        
        # Apply filters
        if content_types:
            query = query.where(Channel.source_type.in_(content_types))
        
        if date_range_days:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=date_range_days)
            query = query.where(ContentItem.published_at >= cutoff_date)
        
        # Add user subscription filtering if user_id provided
        # TODO: use this filtering before itself to limit the number of searches
        if user_id:
            query = query.join(UserSubscription).where(UserSubscription.user_id == user_id)
        
        # Order by similarity (ascending distance = descending similarity)
        query = query.order_by(text('distance')).limit(top_k)
        
        # Execute query
        result = await self.db.execute(query)
        rows = result.all()
        
        # Convert to dictionaries and calculate similarity scores
        results = []
        for row in rows:
            # Convert distance to similarity: similarity = 1 - distance
            # Distance is in range [0, 2], so similarity is in range [-1, 1]
            # But typically distance is in [0, 1], giving similarity in [0, 1]
            similarity = 1.0 - float(row.distance)
            
            results.append({
                'chunk_id': row.chunk_id,
                'chunk_text': row.chunk_text,
                'chunk_metadata': row.chunk_metadata or {},
                'content_item_id': row.content_item_id,
                'content_title': row.content_title,
                'content_author': row.content_author,
                'published_at': row.published_at,
                'content_metadata': row.content_metadata or {},
                'channel_name': row.channel_name,
                'source_type': row.source_type.value,
                'semantic_score': max(0.0, similarity)  # Ensure non-negative
            })
        
        return results
    
    async def _keyword_search(
        self,
        query_text: str,
        top_k: int = 100,
        content_types: Optional[List[str]] = None,
        date_range_days: Optional[int] = None,
        user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Keyword search using PostgreSQL full-text search.
        
        Args:
            query_text: Query text
            top_k: Number of results
            content_types: Filter by content types
            date_range_days: Filter by date range
            user_id: User ID for filtering
            
        Returns:
            List of chunk dictionaries with keyword scores
        """
        # Prepare search query
        search_query = self.text_search.prepare_search_query(query_text)
        
        if not search_query:
            logger.warning("Empty search query after preparation")
            return []
        
        # Build the query
        # ts_rank returns relevance score (higher is better)
        query = select(
            ContentChunk.id.label('chunk_id'),
            ContentChunk.chunk_text,
            ContentChunk.chunk_metadata,
            ContentChunk.content_item_id,
            ContentItem.title.label('content_title'),
            ContentItem.author.label('content_author'),
            ContentItem.published_at,
            ContentItem.content_metadata.label('content_metadata'),
            Channel.name.label('channel_name'),
            Channel.source_type,
            # ts_rank for relevance scoring
            func.ts_rank(
                ContentChunk.text_search_vector,
                func.to_tsquery('english', search_query)
            ).label('rank_score')
        ).select_from(ContentChunk).join(
            ContentItem, ContentChunk.content_item_id == ContentItem.id
        ).join(
            Channel, ContentItem.channel_id == Channel.id
        ).where(
            and_(
                ContentChunk.processing_status == ProcessingStatus.PROCESSED,
                ContentChunk.text_search_vector.op('@@')(
                    func.to_tsquery('english', search_query)
                )
            )
        )
        
        # Apply filters
        if content_types:
            query = query.where(Channel.source_type.in_(content_types))
        
        if date_range_days:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=date_range_days)
            query = query.where(ContentItem.published_at >= cutoff_date)
        
        # Order by rank score
        query = query.order_by(text('rank_score DESC')).limit(top_k)
        
        # Execute query
        result = await self.db.execute(query)
        rows = result.all()
        
        # Convert to dictionaries
        # Normalize ts_rank scores to [0, 1] range (ts_rank is typically 0-1 but can be higher)
        max_score = max([float(row.rank_score) for row in rows]) if rows else 1.0
        max_score = max(max_score, 1.0)  # Ensure we don't divide by zero
        
        results = []
        for row in rows:
            normalized_score = float(row.rank_score) / max_score
            
            results.append({
                'chunk_id': row.chunk_id,
                'chunk_text': row.chunk_text,
                'chunk_metadata': row.chunk_metadata or {},
                'content_item_id': row.content_item_id,
                'content_title': row.content_title,
                'content_author': row.content_author,
                'published_at': row.published_at,
                'content_metadata': row.content_metadata or {},
                'channel_name': row.channel_name,
                'source_type': row.source_type.value,
                'keyword_score': normalized_score
            })
        
        return results
    
    def _merge_and_score(
        self,
        semantic_results: List[Dict[str, Any]],
        keyword_results: List[Dict[str, Any]],
        user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Merge semantic and keyword results and calculate final scores.
        
        Args:
            semantic_results: Results from semantic search
            keyword_results: Results from keyword search
            user_id: User ID for personalization
            
        Returns:
            Merged and scored results
        """
        # Create a dictionary to merge results by chunk_id
        merged = {}
        
        # Add semantic results
        for result in semantic_results:
            chunk_id = result['chunk_id']
            merged[chunk_id] = {
                **result,
                'semantic_score': result.get('semantic_score', 0.0),
                'keyword_score': 0.0,
                'metadata_score': 0.0
            }
        
        # Merge keyword results
        for result in keyword_results:
            chunk_id = result['chunk_id']
            if chunk_id in merged:
                # Update existing
                merged[chunk_id]['keyword_score'] = result.get('keyword_score', 0.0)
            else:
                # Add new
                merged[chunk_id] = {
                    **result,
                    'semantic_score': 0.0,
                    'keyword_score': result.get('keyword_score', 0.0),
                    'metadata_score': 0.0
                }
        
        # Calculate metadata scores and final scores
        results = []
        for chunk_id, result in merged.items():
            # Calculate metadata score (recency + engagement)
            metadata_score = self._calculate_metadata_score(result, user_id)
            result['metadata_score'] = metadata_score
            
            # Calculate weighted final score
            final_score = (
                self.semantic_weight * result['semantic_score'] +
                self.keyword_weight * result['keyword_score'] +
                self.metadata_weight * metadata_score
            )
            result['final_score'] = final_score
            
            results.append(result)
        
        return results
    
    def _calculate_metadata_score(
        self,
        result: Dict[str, Any],
        user_id: Optional[int] = None
    ) -> float:
        """
        Calculate metadata-based score from content signals.
        
        Factors:
        - Recency: Newer content scored higher (50% weight)
        - Engagement: High views/scores/likes scored higher (50% weight)
        
        Args:
            result: Result dictionary with metadata
            user_id: User ID for personalization
            
        Returns:
            Metadata score in [0, 1]
        """
        score = 0.0
        
        # Recency score (50% weight)
        published_at = result.get('published_at')
        if published_at:
            days_old = (datetime.now(timezone.utc) - published_at).days
            # Decay function: score = 1.0 for today, 0.5 for 30 days, 0.0 for 365+ days
            recency_score = max(0.0, 1.0 - (days_old / 365.0))
            score += 0.5 * recency_score
        
        # Engagement score (50% weight)
        content_metadata = result.get('content_metadata', {})
        source_type = result.get('source_type', '')
        
        if source_type == 'youtube':
            # YouTube engagement: views, likes
            view_count = content_metadata.get('view_count', 0)
            like_count = content_metadata.get('like_count', 0)
            
            # Normalize (log scale for views, linear for likes)
            import math
            view_score = min(1.0, math.log10(view_count + 1) / 7.0)  # 10M views = 1.0
            like_score = min(1.0, like_count / 10000.0)  # 10K likes = 1.0
            
            engagement_score = (view_score + like_score) / 2.0
            score += 0.5 * engagement_score
            
        elif source_type == 'reddit':
            # Reddit engagement: score, comment count
            post_score = content_metadata.get('score', 0)
            comment_count = content_metadata.get('num_comments', 0)
            
            # Normalize
            score_normalized = min(1.0, post_score / 1000.0)  # 1000 upvotes = 1.0
            comment_normalized = min(1.0, comment_count / 100.0)  # 100 comments = 1.0
            
            engagement_score = (score_normalized + comment_normalized) / 2.0
            score += 0.5 * engagement_score
            
        elif source_type == 'blog':
            # Blog engagement: assume recent = good (no engagement metrics typically)
            # Just use recency (already added above)
            pass
        
        return min(1.0, score)  # Ensure in [0, 1]


async def create_retriever(db: AsyncSession) -> HybridRetriever:
    """
    Create a hybrid retriever instance.
    
    Args:
        db: Database session
        
    Returns:
        Initialized HybridRetriever
        
    Example:
        >>> retriever = await create_retriever(db)
        >>> results = await retriever.retrieve(query_embedding, query_text)
    """
    return HybridRetriever(db)

