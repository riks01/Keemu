"""
Text Search Service

This module provides full-text search vector generation for PostgreSQL.
Uses PostgreSQL's tsvector and GIN indexes for fast keyword search.

Features:
---------
- Generate tsvector from text
- Language-specific stemming (English primary)
- Custom ranking weights
- Query parsing and preparation
- Combined with semantic search for hybrid retrieval
"""

import re
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import logging


logger = logging.getLogger(__name__)


class TextSearchService:
    """
    Service for generating and managing full-text search vectors.
    
    PostgreSQL's full-text search provides:
    - Stemming: "running" matches "run"
    - Stop word removal: Common words like "the", "a" ignored
    - Ranking: Results sorted by relevance
    - Boolean operators: AND, OR, NOT, phrase search
    
    Usage:
    ------
    search_service = TextSearchService()
    
    # Generate tsvector for text
    tsvector = await search_service.generate_tsvector(
        db_session,
        "React hooks are amazing"
    )
    
    # Prepare search query
    query = search_service.prepare_search_query("react hooks")
    """
    
    def __init__(self, language: str = "english"):
        """
        Initialize the text search service.
        
        Args:
            language: Language for stemming (default: english)
                     Supported: english, spanish, french, german, etc.
        """
        self.language = language
    
    async def generate_tsvector(
        self,
        db_session: AsyncSession,
        text: str,
        weight: str = "A"
    ) -> Optional[str]:
        """
        Generate tsvector from text using PostgreSQL.
        
        This runs the PostgreSQL to_tsvector function which:
        1. Tokenizes the text
        2. Removes stop words
        3. Applies stemming
        4. Assigns weights (A-D, where A is highest)
        
        Args:
            db_session: Database session
            text: Text to convert to tsvector
            weight: Weight for this text (A, B, C, or D)
                   A = most important (e.g., title)
                   B = important (e.g., heading)
                   C = less important (e.g., body)
                   D = least important (e.g., metadata)
            
        Returns:
            tsvector string (e.g., "'amaz':3 'hook':2 'react':1")
            None if text is empty or error occurs
        """
        if not text or not text.strip():
            return None
        
        try:
            # Use PostgreSQL's to_tsvector function
            # setweight assigns importance weights to lexemes
            query = text(f"""
                SELECT setweight(
                    to_tsvector(:language, :text),
                    :weight
                )::text
            """)
            
            result = await db_session.execute(
                query,
                {
                    "language": self.language,
                    "text": text,
                    "weight": weight
                }
            )
            
            tsvector = result.scalar()
            return tsvector
        
        except Exception as e:
            logger.error(f"Error generating tsvector: {e}")
            return None
    
    async def generate_weighted_tsvector(
        self,
        db_session: AsyncSession,
        title: Optional[str] = None,
        body: Optional[str] = None,
        metadata: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate weighted tsvector from multiple text fields.
        
        Different parts of content have different importance:
        - Title: Weight A (highest)
        - Body: Weight C (medium)
        - Metadata: Weight D (lowest)
        
        This allows ranking search results by field importance.
        
        Args:
            db_session: Database session
            title: Title text (weight A)
            body: Body text (weight C)
            metadata: Metadata text (weight D)
            
        Returns:
            Combined weighted tsvector
            None if all fields are empty
        """
        vectors = []
        
        if title and title.strip():
            title_vector = await self.generate_tsvector(db_session, title, "A")
            if title_vector:
                vectors.append(title_vector)
        
        if body and body.strip():
            body_vector = await self.generate_tsvector(db_session, body, "C")
            if body_vector:
                vectors.append(body_vector)
        
        if metadata and metadata.strip():
            metadata_vector = await self.generate_tsvector(db_session, metadata, "D")
            if metadata_vector:
                vectors.append(metadata_vector)
        
        if not vectors:
            return None
        
        # Combine vectors using PostgreSQL's || operator
        try:
            combined_query = text("""
                SELECT (
                    """ + " || ".join([f"'{v}'::tsvector" for v in vectors]) + """
                )::text
            """)
            
            result = await db_session.execute(combined_query)
            return result.scalar()
        
        except Exception as e:
            logger.error(f"Error combining tsvectors: {e}")
            return vectors[0]  # Return first vector as fallback
    
    def prepare_search_query(
        self,
        query_text: str,
        use_prefix_matching: bool = True
    ) -> str:
        """
        Prepare user query for full-text search.
        
        Transforms user query into PostgreSQL tsquery format:
        - Splits on whitespace
        - Adds AND operator between words
        - Optionally adds prefix matching (:*)
        - Handles special characters
        
        Args:
            query_text: User's search query
            use_prefix_matching: Enable prefix matching (e.g., "hook" matches "hooks")
            
        Returns:
            Formatted tsquery string
            
        Examples:
            "react hooks" → "react:* & hooks:*" (with prefix)
            "react hooks" → "react & hooks" (without prefix)
            "react OR hooks" → "react:* | hooks:*"
        """
        if not query_text or not query_text.strip():
            return ""
        
        # Clean query
        query = query_text.strip()
        
        # Remove special characters that could break tsquery
        # Keep: letters, numbers, spaces, AND, OR, NOT
        query = re.sub(r'[^\w\s&|!]', ' ', query)
        
        # Split into words
        words = query.split()
        
        if not words:
            return ""
        
        # Build tsquery
        query_parts = []
        i = 0
        while i < len(words):
            word = words[i].lower()
            
            # Handle boolean operators
            if word in ("and", "&"):
                query_parts.append("&")
                i += 1
                continue
            elif word in ("or", "|"):
                query_parts.append("|")
                i += 1
                continue
            elif word in ("not", "!"):
                query_parts.append("!")
                i += 1
                continue
            
            # Regular word
            if use_prefix_matching:
                query_parts.append(f"{word}:*")
            else:
                query_parts.append(word)
            
            i += 1
        
        # Join with AND operator if no explicit operators
        result = []
        for part in query_parts:
            if part not in ("&", "|", "!"):
                if result and result[-1] not in ("&", "|", "!"):
                    result.append("&")
                result.append(part)
            else:
                result.append(part)
        
        return " ".join(result)
    
    async def search(
        self,
        db_session: AsyncSession,
        query_text: str,
        tsvectors: list[str],
        use_prefix_matching: bool = True
    ) -> list[float]:
        """
        Perform full-text search and return relevance scores.
        
        Uses PostgreSQL's ts_rank function to score how well each
        tsvector matches the query.
        
        Args:
            db_session: Database session
            query_text: User's search query
            tsvectors: List of tsvector strings to search
            use_prefix_matching: Enable prefix matching
            
        Returns:
            List of relevance scores (0-1, higher = more relevant)
        """
        if not query_text or not tsvectors:
            return [0.0] * len(tsvectors)
        
        # Prepare query
        tsquery = self.prepare_search_query(query_text, use_prefix_matching)
        
        if not tsquery:
            return [0.0] * len(tsvectors)
        
        try:
            # Use PostgreSQL's ts_rank to score relevance
            # Normalization: 1 = divide by document length
            scores = []
            
            for tsvector_str in tsvectors:
                query = text("""
                    SELECT ts_rank(
                        :tsvector::tsvector,
                        to_tsquery(:language, :tsquery),
                        1  -- normalization: divide by document length
                    )
                """)
                
                result = await db_session.execute(
                    query,
                    {
                        "tsvector": tsvector_str,
                        "language": self.language,
                        "tsquery": tsquery
                    }
                )
                
                score = result.scalar()
                scores.append(float(score) if score is not None else 0.0)
            
            return scores
        
        except Exception as e:
            logger.error(f"Error performing text search: {e}")
            return [0.0] * len(tsvectors)
    
    def explain_query(self, query_text: str) -> dict:
        """
        Explain how a query will be processed.
        
        Useful for debugging and user feedback.
        
        Args:
            query_text: User's query
            
        Returns:
            Dictionary with query analysis:
            - original: Original query
            - prepared: Prepared tsquery
            - tokens: List of search tokens
            - operators: Boolean operators used
        """
        prepared = self.prepare_search_query(query_text)
        
        # Extract tokens and operators
        parts = prepared.split()
        tokens = [p.replace(":*", "") for p in parts if p not in ("&", "|", "!")]
        operators = [p for p in parts if p in ("&", "|", "!")]
        
        return {
            "original": query_text,
            "prepared": prepared,
            "tokens": tokens,
            "operators": operators,
            "language": self.language
        }


# ========================================
# Utility Functions
# ========================================

def clean_text_for_search(text: str) -> str:
    """
    Clean text before generating tsvector.
    
    Removes:
    - HTML tags
    - URLs
    - Excessive whitespace
    - Special characters that don't add search value
    
    Args:
        text: Text to clean
        
    Returns:
        Cleaned text
    """
    if not text:
        return ""
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Remove URLs
    text = re.sub(r'https?://\S+', ' ', text)
    
    # Remove email addresses
    text = re.sub(r'\S+@\S+', ' ', text)
    
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

