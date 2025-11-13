"""
Content Chunking Service

This module provides hybrid chunking strategies for different content types.
Chunks are optimized for embedding and RAG retrieval.

Chunking Strategies:
--------------------
1. YouTube: Time-based chunking using transcript timestamps (2-3 min segments)
2. Reddit: Thread-aware chunking preserving post + comment structure
3. Blog: Semantic chunking based on sections, headings, and paragraphs

Configuration from settings:
- CHUNK_SIZE_TOKENS: 800 (default)
- CHUNK_OVERLAP_TOKENS: 100 (default)
- MAX_CHUNKS_PER_CONTENT: 50 (default)
"""

import json
import re
from typing import Any
import tiktoken

from app.core.config import settings
from app.models.content import ContentItem, ContentSourceType


class ContentChunker:
    """
    Hybrid content chunker with content-type specific strategies.
    
    This class provides intelligent chunking that adapts to the structure
    of different content types (YouTube transcripts, Reddit posts, blog articles).
    
    Features:
    ---------
    - Token-aware chunking (respects embedding model limits)
    - Context preservation (doesn't split mid-sentence)
    - Overlap between chunks for continuity
    - Metadata extraction (timestamps, sections, comment depth)
    
    Usage:
    ------
    chunker = ContentChunker()
    chunks = await chunker.chunk_content(content_item)
    
    for chunk_data in chunks:
        chunk = ContentChunk(
            content_item_id=content_item.id,
            chunk_index=chunk_data["index"],
            chunk_text=chunk_data["text"],
            chunk_metadata=chunk_data["metadata"]
        )
    """
    
    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
        max_chunks: int = None
    ):
        """
        Initialize the chunker with configuration.
        
        Args:
            chunk_size: Max tokens per chunk (default from settings)
            chunk_overlap: Tokens to overlap between chunks (default from settings)
            max_chunks: Maximum chunks per content item (default from settings)
        """
        self.chunk_size = chunk_size or settings.CHUNK_SIZE_TOKENS
        self.chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP_TOKENS
        self.max_chunks = max_chunks or settings.MAX_CHUNKS_PER_CONTENT
        
        # Initialize tokenizer (cl100k_base used by GPT-4, good general purpose)
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # Fallback if tiktoken fails
            self.tokenizer = None
    
    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text using tiktoken.
        
        Args:
            text: Text to count tokens in
            
        Returns:
            Number of tokens
        """
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        else:
            # Rough approximation: 1 token ≈ 4 characters
            return len(text) // 4
    
    async def chunk_content(self, content_item: ContentItem) -> list[dict[str, Any]]:
        """
        Chunk content item using appropriate strategy based on content type.
        
        Args:
            content_item: ContentItem to chunk
            
        Returns:
            List of chunk dictionaries with:
            - index: Chunk index (0-based)
            - text: Chunk text content
            - metadata: Content-type specific metadata
        """
        content_type = content_item.channel.source_type
        
        if content_type == ContentSourceType.YOUTUBE:
            return await self._chunk_youtube(content_item)
        elif content_type == ContentSourceType.REDDIT:
            return await self._chunk_reddit(content_item)
        elif content_type == ContentSourceType.BLOG:
            return await self._chunk_blog(content_item)
        else:
            # Fallback to generic chunking
            return await self._chunk_generic(content_item)
    
    # ========================================
    # YouTube Chunking Strategy
    # ========================================
    
    async def _chunk_youtube(self, content_item: ContentItem) -> list[dict[str, Any]]:
        """
        Chunk YouTube transcript by time windows (2-3 minute segments).
        
        Strategy:
        ---------
        1. Parse transcript with timestamps from metadata
        2. Group by time windows (target: 2-3 minutes = 120-180 seconds)
        3. Ensure chunks don't exceed token limit
        4. Preserve sentence boundaries
        5. Add overlap between chunks
        
        Metadata extracted:
        - start_time: Start timestamp in seconds
        - end_time: End timestamp in seconds
        - duration: Chunk duration in seconds
        - transcript_language: Language code
        
        Args:
            content_item: YouTube content item
            
        Returns:
            List of chunk dictionaries
        """
        chunks = []
        content = content_item.content_body
        metadata = content_item.content_metadata or {}
        
        # Target time window: 2-3 minutes (120-180 seconds)
        target_window_seconds = 150  # Middle of range
        
        # Check if we have transcript with timestamps
        has_timestamps = "transcript_segments" in metadata
        
        if has_timestamps:
            # Use timestamp-based chunking
            segments = metadata.get("transcript_segments", [])
            chunks = self._chunk_by_timestamps(
                segments,
                target_window_seconds,
                metadata.get("transcript_language", "en")
            )
        else:
            # Fallback to sentence-based chunking
            chunks = self._chunk_by_sentences(
                content,
                {
                    "transcript_language": metadata.get("transcript_language", "en"),
                    "video_id": metadata.get("video_id"),
                    "duration": metadata.get("duration")
                }
            )
        
        return chunks[:self.max_chunks]  # Limit number of chunks
    
    def _chunk_by_timestamps(
        self,
        segments: list[dict],
        target_window: int,
        language: str
    ) -> list[dict[str, Any]]:
        """
        Chunk transcript segments by time windows.
        
        Args:
            segments: List of {start, end, text} segments
            target_window: Target window size in seconds
            language: Transcript language
            
        Returns:
            List of chunks with timestamp metadata
        """
        chunks = []
        current_chunk = []
        current_start = None
        current_end = None
        current_tokens = 0
        
        for segment in segments:
            start = segment.get("start", 0)
            end = segment.get("end", 0)
            text = segment.get("text", "").strip()
            
            if not text:
                continue
            
            # Initialize first chunk
            if current_start is None:
                current_start = start
            
            segment_tokens = self.count_tokens(text)
            
            # Check if we should start a new chunk
            # Conditions: exceeded time window OR exceeded token limit
            time_exceeded = (end - current_start) >= target_window
            tokens_exceeded = current_tokens + segment_tokens > self.chunk_size
            
            if (time_exceeded or tokens_exceeded) and current_chunk:
                # Save current chunk
                chunk_text = " ".join(current_chunk)
                chunks.append({
                    "index": len(chunks),
                    "text": chunk_text,
                    "metadata": {
                        "start_time": current_start,
                        "end_time": current_end,
                        "duration": current_end - current_start,
                        "transcript_language": language,
                        "segment_count": len(current_chunk)
                    }
                })
                
                # Start new chunk with overlap
                # Keep last sentence for continuity
                if current_chunk:
                    overlap_text = current_chunk[-1]
                    current_chunk = [overlap_text]
                    current_tokens = self.count_tokens(overlap_text)
                else:
                    current_chunk = []
                    current_tokens = 0
                
                current_start = start
            
            # Add segment to current chunk
            current_chunk.append(text)
            current_tokens += segment_tokens
            current_end = end
        
        # Add final chunk
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append({
                "index": len(chunks),
                "text": chunk_text,
                "metadata": {
                    "start_time": current_start,
                    "end_time": current_end,
                    "duration": current_end - current_start,
                    "transcript_language": language,
                    "segment_count": len(current_chunk)
                }
            })
        
        return chunks
    
    # ========================================
    # Reddit Chunking Strategy
    # ========================================
    
    async def _chunk_reddit(self, content_item: ContentItem) -> list[dict[str, Any]]:
        """
        Chunk Reddit post preserving thread structure.
        
        Strategy:
        ---------
        1. Base chunk: Post + title (always included)
        2. Group top-level comments together
        3. Keep reply threads together (preserve context)
        4. Ensure chunks don't exceed token limit
        5. Add metadata about comment depth and IDs
        
        Metadata extracted:
        - comment_depth: Maximum comment depth in chunk
        - comment_ids: List of comment IDs in chunk
        - is_post: Whether chunk includes the post
        - parent_comment: Parent comment ID if this is a reply chunk
        
        Args:
            content_item: Reddit content item
            
        Returns:
            List of chunk dictionaries
        """
        chunks = []
        content = content_item.content_body
        metadata = content_item.content_metadata or {}
        
        # Parse Reddit content structure from metadata
        post_text = f"{content_item.title}\n\n{content}"
        comments = metadata.get("top_comments", [])
        
        # First chunk: Always include the post
        post_tokens = self.count_tokens(post_text)
        
        if post_tokens <= self.chunk_size:
            # Post fits in one chunk, can add some comments
            chunks.append({
                "index": 0,
                "text": post_text,
                "metadata": {
                    "is_post": True,
                    "comment_depth": 0,
                    "comment_ids": [],
                    "post_id": metadata.get("post_id"),
                    "subreddit": metadata.get("subreddit")
                }
            })
            
            # Try to add comments to additional chunks
            comment_chunks = self._chunk_reddit_comments(comments, metadata)
            for i, comment_chunk in enumerate(comment_chunks):
                comment_chunk["index"] = len(chunks)
                chunks.append(comment_chunk)
        else:
            # Post is too long, chunk it first
            post_chunks = self._chunk_by_sentences(
                post_text,
                {
                    "is_post": True,
                    "post_id": metadata.get("post_id"),
                    "subreddit": metadata.get("subreddit")
                }
            )
            chunks.extend(post_chunks)
            
            # Then chunk comments
            comment_chunks = self._chunk_reddit_comments(comments, metadata)
            for comment_chunk in comment_chunks:
                comment_chunk["index"] = len(chunks)
                chunks.append(comment_chunk)
        
        return chunks[:self.max_chunks]
    
    def _chunk_reddit_comments(
        self,
        comments: list[dict],
        base_metadata: dict
    ) -> list[dict[str, Any]]:
        """
        Chunk Reddit comments preserving thread structure.
        
        Args:
            comments: List of comment dictionaries
            base_metadata: Base metadata to include
            
        Returns:
            List of comment chunks
        """
        chunks = []
        current_chunk = []
        current_tokens = 0
        current_comment_ids = []
        max_depth = 0
        
        for comment in comments:
            author = comment.get("author", "[deleted]")
            body = comment.get("body", "")
            score = comment.get("score", 0)
            depth = comment.get("depth", 0)
            comment_id = comment.get("id", "")
            
            # Format comment
            comment_text = f"\n\nComment by {author} (score: {score}):\n{body}"
            comment_tokens = self.count_tokens(comment_text)
            
            # Check if we need to start a new chunk
            if current_tokens + comment_tokens > self.chunk_size and current_chunk:
                # Save current chunk
                chunk_text = "".join(current_chunk)
                chunks.append({
                    "index": len(chunks),
                    "text": chunk_text,
                    "metadata": {
                        "is_post": False,
                        "comment_depth": max_depth,
                        "comment_ids": current_comment_ids.copy(),
                        "post_id": base_metadata.get("post_id"),
                        "subreddit": base_metadata.get("subreddit")
                    }
                })
                
                # Reset for new chunk
                current_chunk = []
                current_tokens = 0
                current_comment_ids = []
                max_depth = 0
            
            # Add comment to current chunk
            current_chunk.append(comment_text)
            current_tokens += comment_tokens
            current_comment_ids.append(comment_id)
            max_depth = max(max_depth, depth)
        
        # Add final chunk
        if current_chunk:
            chunk_text = "".join(current_chunk)
            chunks.append({
                "index": len(chunks),
                "text": chunk_text,
                "metadata": {
                    "is_post": False,
                    "comment_depth": max_depth,
                    "comment_ids": current_comment_ids,
                    "post_id": base_metadata.get("post_id"),
                    "subreddit": base_metadata.get("subreddit")
                }
            })
        
        return chunks
    
    # ========================================
    # Blog Chunking Strategy
    # ========================================
    
    async def _chunk_blog(self, content_item: ContentItem) -> list[dict[str, Any]]:
        """
        Chunk blog article by sections and semantic boundaries.
        
        Strategy:
        ---------
        1. Detect sections using heading markers (h1, h2, h3, etc.)
        2. Keep sections together when possible
        3. Split long sections at paragraph boundaries
        4. Preserve code blocks and lists
        5. Add overlap between chunks
        
        Metadata extracted:
        - section: Section title/heading
        - heading_level: HTML heading level (1-6)
        - paragraph_indices: Paragraph indices in chunk
        - has_code: Whether chunk contains code blocks
        
        Args:
            content_item: Blog content item
            
        Returns:
            List of chunk dictionaries
        """
        chunks = []
        content = content_item.content_body
        metadata = content_item.content_metadata or {}
        
        # Try to detect sections using common heading patterns
        sections = self._extract_blog_sections(content)
        
        if sections:
            # Chunk by sections
            for section in sections:
                section_chunks = self._chunk_blog_section(section, metadata)
                for chunk in section_chunks:
                    chunk["index"] = len(chunks)
                    chunks.append(chunk)
        else:
            # Fallback to paragraph-based chunking
            chunks = self._chunk_by_paragraphs(content, metadata)
        
        return chunks[:self.max_chunks]
    
    def _extract_blog_sections(self, content: str) -> list[dict]:
        """
        Extract sections from blog content using heading patterns.
        
        Detects:
        - Markdown headings: # Heading, ## Heading, ### Heading
        - HTML headings: <h1>, <h2>, <h3>, etc.
        - Underlined headings: Heading\n====== or Heading\n------
        
        Args:
            content: Blog article content
            
        Returns:
            List of sections with heading and content
        """
        sections = []
        
        # Pattern 1: Markdown headings
        markdown_pattern = r'^(#{1,6})\s+(.+)$'
        
        # Pattern 2: HTML headings
        html_pattern = r'<h([1-6])>(.*?)</h\1>'
        
        # Split by markdown headings
        lines = content.split('\n')
        current_section = None
        current_content = []
        
        for line in lines:
            # Check for markdown heading
            match = re.match(markdown_pattern, line)
            if match:
                # Save previous section
                if current_section is not None and current_content:
                    sections.append({
                        "heading": current_section["heading"],
                        "level": current_section["level"],
                        "content": "\n".join(current_content)
                    })
                
                # Start new section
                level = len(match.group(1))  # Number of # characters
                heading = match.group(2).strip()
                current_section = {"heading": heading, "level": level}
                current_content = []
            else:
                # Add line to current section
                current_content.append(line)
        
        # Add final section
        if current_section is not None and current_content:
            sections.append({
                "heading": current_section["heading"],
                "level": current_section["level"],
                "content": "\n".join(current_content)
            })
        
        return sections
    
    def _chunk_blog_section(
        self,
        section: dict,
        base_metadata: dict
    ) -> list[dict[str, Any]]:
        """
        Chunk a blog section, splitting if necessary.
        
        Args:
            section: Section dictionary with heading and content
            base_metadata: Base metadata to include
            
        Returns:
            List of chunks for this section
        """
        heading = section["heading"]
        level = section["level"]
        content = section["content"]
        
        # Add heading to content
        full_text = f"{heading}\n\n{content}"
        tokens = self.count_tokens(full_text)
        
        if tokens <= self.chunk_size:
            # Section fits in one chunk
            return [{
                "index": 0,
                "text": full_text,
                "metadata": {
                    "section": heading,
                    "heading_level": level,
                    "has_code": "```" in content or "<code>" in content,
                    **base_metadata
                }
            }]
        else:
            # Section too long, split by paragraphs
            paragraphs = content.split("\n\n")
            chunks = []
            current_chunk = [heading]
            current_tokens = self.count_tokens(heading)
            para_indices = []
            
            for i, para in enumerate(paragraphs):
                para_tokens = self.count_tokens(para)
                
                if current_tokens + para_tokens > self.chunk_size and current_chunk:
                    # Save current chunk
                    chunk_text = "\n\n".join(current_chunk)
                    chunks.append({
                        "index": len(chunks),
                        "text": chunk_text,
                        "metadata": {
                            "section": heading,
                            "heading_level": level,
                            "paragraph_indices": para_indices.copy(),
                            "has_code": "```" in chunk_text or "<code>" in chunk_text,
                            **base_metadata
                        }
                    })
                    
                    # Start new chunk with heading
                    current_chunk = [heading]
                    current_tokens = self.count_tokens(heading)
                    para_indices = []
                
                # Add paragraph
                current_chunk.append(para)
                current_tokens += para_tokens
                para_indices.append(i)
            
            # Add final chunk
            if current_chunk:
                chunk_text = "\n\n".join(current_chunk)
                chunks.append({
                    "index": len(chunks),
                    "text": chunk_text,
                    "metadata": {
                        "section": heading,
                        "heading_level": level,
                        "paragraph_indices": para_indices,
                        "has_code": "```" in chunk_text or "<code>" in chunk_text,
                        **base_metadata
                    }
                })
            
            return chunks
    
    # ========================================
    # Generic/Fallback Chunking Strategies
    # ========================================
    
    async def _chunk_generic(self, content_item: ContentItem) -> list[dict[str, Any]]:
        """
        Generic chunking strategy for unknown content types.
        Uses sentence-based chunking with paragraph awareness.
        """
        return self._chunk_by_sentences(
            content_item.content_body,
            content_item.content_metadata or {}
        )
    
    def _chunk_by_sentences(
        self,
        text: str,
        metadata: dict
    ) -> list[dict[str, Any]]:
        """
        Chunk text by sentences while respecting token limits.
        
        Args:
            text: Text to chunk
            metadata: Base metadata
            
        Returns:
            List of chunks
        """
        chunks = []
        
        # Split into sentences (simple split on ., !, ?)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        current_chunk = []
        current_tokens = 0
        
        for sentence in sentences:
            sentence_tokens = self.count_tokens(sentence)
            
            # Check if we need to start a new chunk
            if current_tokens + sentence_tokens > self.chunk_size and current_chunk:
                # Save current chunk
                chunk_text = " ".join(current_chunk)
                chunks.append({
                    "index": len(chunks),
                    "text": chunk_text,
                    "metadata": {
                        "sentence_count": len(current_chunk),
                        **metadata
                    }
                })
                
                # Start new chunk with overlap (last sentence)
                if current_chunk:
                    overlap = current_chunk[-1]
                    current_chunk = [overlap]
                    current_tokens = self.count_tokens(overlap)
                else:
                    current_chunk = []
                    current_tokens = 0
            
            # Add sentence
            current_chunk.append(sentence)
            current_tokens += sentence_tokens
        
        # Add final chunk
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append({
                "index": len(chunks),
                "text": chunk_text,
                "metadata": {
                    "sentence_count": len(current_chunk),
                    **metadata
                }
            })
        
        return chunks
    
    def _chunk_by_paragraphs(
        self,
        text: str,
        metadata: dict
    ) -> list[dict[str, Any]]:
        """
        Chunk text by paragraphs while respecting token limits.
        
        Args:
            text: Text to chunk
            metadata: Base metadata
            
        Returns:
            List of chunks
        """
        chunks = []
        paragraphs = text.split("\n\n")
        
        current_chunk = []
        current_tokens = 0
        para_indices = []
        
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if not para:
                continue
            
            para_tokens = self.count_tokens(para)
            
            # Check if we need to start a new chunk
            if current_tokens + para_tokens > self.chunk_size and current_chunk:
                # Save current chunk
                chunk_text = "\n\n".join(current_chunk)
                chunks.append({
                    "index": len(chunks),
                    "text": chunk_text,
                    "metadata": {
                        "paragraph_indices": para_indices.copy(),
                        "paragraph_count": len(current_chunk),
                        **metadata
                    }
                })
                
                # Start new chunk
                current_chunk = []
                current_tokens = 0
                para_indices = []
            
            # Add paragraph
            current_chunk.append(para)
            current_tokens += para_tokens
            para_indices.append(i)
        
        # Add final chunk
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunks.append({
                "index": len(chunks),
                "text": chunk_text,
                "metadata": {
                    "paragraph_indices": para_indices,
                    "paragraph_count": len(current_chunk),
                    **metadata
                }
            })
        
        return chunks


# ========================================
# Utility Functions
# ========================================

def estimate_chunk_count(content_length: int, chunk_size: int = 800) -> int:
    """
    Estimate number of chunks for content.
    
    Args:
        content_length: Content length in characters
        chunk_size: Target chunk size in tokens
        
    Returns:
        Estimated number of chunks
    """
    # Rough estimate: 1 token ≈ 4 characters
    estimated_tokens = content_length // 4
    return max(1, estimated_tokens // chunk_size)

