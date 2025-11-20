"""
RAG Generator for Chat

This module implements the RAG generation pipeline using Claude API:
- Context assembly from retrieved chunks
- Citation generation
- Prompt engineering for RAG
- Response generation with streaming
- Source attribution

The generator takes retrieved chunks and produces contextual answers.
"""

import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from datetime import datetime

from anthropic import AsyncAnthropic
from anthropic.types import MessageStreamEvent

from app.core.config import settings

logger = logging.getLogger(__name__)


class RAGGenerator:
    """
    RAG Generator using Claude API.
    
    This service takes retrieved chunks and generates contextual responses
    with proper citations and source attribution.
    
    Features:
    ---------
    - Context assembly from chunks
    - Smart truncation to fit token limits
    - Citation generation
    - Streaming responses
    - Source attribution
    - Multi-turn conversation support
    
    Usage:
    ------
    generator = RAGGenerator(api_key=settings.ANTHROPIC_API_KEY)
    
    # Generate response
    response = await generator.generate(
        query="What are React hooks?",
        chunks=retrieved_chunks,
        conversation_history=[...]
    )
    
    # Or stream response
    async for chunk in generator.generate_stream(query, chunks):
        print(chunk, end="", flush=True)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 2048,
        temperature: float = 0.7
    ):
        """
        Initialize the RAG generator.
        
        Args:
            api_key: Anthropic API key (defaults to settings.ANTHROPIC_API_KEY)
            model: Claude model to use (default: claude-3-5-sonnet-20241022)
            max_tokens: Maximum tokens in response (default: 2048)
            temperature: Sampling temperature 0-1 (default: 0.7)
        """
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        
        if not self.api_key:
            raise ValueError("Anthropic API key is required. Set ANTHROPIC_API_KEY in environment.")
        
        self.client = AsyncAnthropic(api_key=self.api_key)
        
        logger.info(f"RAGGenerator initialized with model={model}, max_tokens={max_tokens}")
    
    async def generate(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        conversation_history: Optional[List[Dict[str, str]]] = None,
        max_context_tokens: int = 3000,
        include_citations: bool = True
    ) -> Dict[str, Any]:
        """
        Generate a response using RAG.
        
        Args:
            query: User's question
            chunks: Retrieved chunks (from retriever + reranker)
            conversation_history: Previous messages [{"role": "user|assistant", "content": "..."}]
            max_context_tokens: Max tokens for context (default: 3000)
            include_citations: Whether to include source citations (default: True)
            
        Returns:
            Dictionary containing:
            {
                'answer': 'The generated answer...',
                'sources': [{'chunk_id': 1, 'title': '...', 'author': '...', ...}],
                'citations': [1, 2, 3],  # Chunk IDs cited
                'model': 'claude-3-5-sonnet-20241022',
                'tokens_used': 1234
            }
        """
        logger.info(f"Generating response for query: '{query[:50]}...' with {len(chunks)} chunks")
        
        # Step 1: Assemble context from chunks
        context = self._assemble_context(chunks, max_context_tokens)
        
        # Step 2: Build the prompt
        system_prompt = self._build_system_prompt(include_citations)
        user_message = self._build_user_message(query, context, chunks)
        
        # Step 3: Prepare messages
        messages = []
        
        # Add conversation history
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current query
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        # Step 4: Call Claude API
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=messages
            )
            
            # Extract answer
            answer = response.content[0].text
            
            # Extract citations (if enabled)
            citations = []
            if include_citations:
                citations = self._extract_citations(answer, chunks)
            
            # Build sources list
            sources = self._build_sources_list(chunks, citations if citations else list(range(len(chunks))))
            
            result = {
                'answer': answer,
                'sources': sources,
                'citations': citations,
                'model': self.model,
                'tokens_used': response.usage.input_tokens + response.usage.output_tokens
            }
            
            logger.info(f"Generated response: {len(answer)} chars, {len(sources)} sources, {result['tokens_used']} tokens")
            
            return result
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise
    
    async def generate_stream(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        conversation_history: Optional[List[Dict[str, str]]] = None,
        max_context_tokens: int = 3000,
        include_citations: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Generate a streaming response using RAG.
        
        Args:
            query: User's question
            chunks: Retrieved chunks
            conversation_history: Previous messages
            max_context_tokens: Max tokens for context
            include_citations: Whether to include citations
            
        Yields:
            Response text chunks as they're generated
            
        Example:
            async for chunk in generator.generate_stream(query, chunks):
                print(chunk, end="", flush=True)
        """
        logger.info(f"Generating streaming response for query: '{query[:50]}...'")
        
        # Assemble context and build prompt
        context = self._assemble_context(chunks, max_context_tokens)
        system_prompt = self._build_system_prompt(include_citations)
        user_message = self._build_user_message(query, context, chunks)
        
        # Prepare messages
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        # Stream response
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=messages
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                    
        except Exception as e:
            logger.error(f"Error streaming response: {e}")
            raise
    
    def _assemble_context(
        self,
        chunks: List[Dict[str, Any]],
        max_tokens: int = 3000
    ) -> str:
        """
        Assemble context from chunks, truncating to fit token limit.
        
        Args:
            chunks: Retrieved chunks
            max_tokens: Maximum tokens for context
            
        Returns:
            Assembled context string
        """
        context_parts = []
        current_tokens = 0
        
        for i, chunk in enumerate(chunks):
            # Format chunk with metadata
            chunk_text = chunk.get('chunk_text', '')
            title = chunk.get('content_title', 'Unknown')
            author = chunk.get('content_author', 'Unknown')
            source_type = chunk.get('source_type', 'unknown')
            
            # Format as source [i]
            formatted_chunk = f"[Source {i+1}] {title} by {author} ({source_type})\n{chunk_text}\n"
            
            # Estimate tokens (rough: 4 chars = 1 token)
            chunk_tokens = len(formatted_chunk) // 4
            
            if current_tokens + chunk_tokens > max_tokens:
                logger.info(f"Context truncated at {i} chunks ({current_tokens} tokens)")
                break
            
            context_parts.append(formatted_chunk)
            current_tokens += chunk_tokens
        
        return "\n---\n\n".join(context_parts)
    
    def _build_system_prompt(self, include_citations: bool = True) -> str:
        """
        Build the system prompt for RAG.
        
        Args:
            include_citations: Whether to request citations
            
        Returns:
            System prompt string
        """
        base_prompt = """You are KeeMU, a helpful AI assistant that answers questions based on the provided context from YouTube videos, Reddit posts, and blog articles.

Your task is to:
1. Answer the user's question using ONLY the information provided in the context
2. Be accurate and factual - don't make up information
3. If the context doesn't contain enough information to answer fully, say so
4. Be concise but comprehensive
5. Use a friendly, conversational tone"""
        
        if include_citations:
            base_prompt += """
6. When referencing information, cite your sources using [Source N] notation
7. If multiple sources support a point, cite all relevant sources like [Source 1, 2]"""
        
        base_prompt += """

Remember: You can ONLY use information from the provided context. If the answer isn't in the context, acknowledge the limitation politely."""
        
        return base_prompt
    
    def _build_user_message(
        self,
        query: str,
        context: str,
        chunks: List[Dict[str, Any]]
    ) -> str:
        """
        Build the user message with context and query.
        
        Args:
            query: User's question
            context: Assembled context
            chunks: Retrieved chunks
            
        Returns:
            Formatted user message
        """
        message = f"""Context from your knowledge base:

{context}

---

Question: {query}

Please answer the question based on the context provided above."""
        
        return message
    
    def _extract_citations(
        self,
        answer: str,
        chunks: List[Dict[str, Any]]
    ) -> List[int]:
        """
        Extract citation numbers from the answer.
        
        Args:
            answer: Generated answer text
            chunks: Retrieved chunks
            
        Returns:
            List of chunk indices that were cited (0-indexed)
        """
        import re
        
        citations = set()
        
        # Find all [Source N] patterns
        pattern = r'\[Source (\d+)\]'
        matches = re.findall(pattern, answer)
        
        for match in matches:
            source_num = int(match)
            # Convert to 0-indexed
            if 1 <= source_num <= len(chunks):
                citations.add(source_num - 1)
        
        return sorted(list(citations))
    
    def _build_sources_list(
        self,
        chunks: List[Dict[str, Any]],
        citation_indices: List[int]
    ) -> List[Dict[str, Any]]:
        """
        Build a clean sources list for the response.
        
        Args:
            chunks: Retrieved chunks
            citation_indices: Indices of cited chunks
            
        Returns:
            List of source dictionaries
        """
        sources = []
        
        for idx in citation_indices:
            if idx < len(chunks):
                chunk = chunks[idx]
                source = {
                    'source_number': idx + 1,
                    'chunk_id': chunk.get('chunk_id'),
                    'content_item_id': chunk.get('content_item_id'),
                    'title': chunk.get('content_title'),
                    'author': chunk.get('content_author'),
                    'source_type': chunk.get('source_type'),
                    'channel_name': chunk.get('channel_name'),
                    'published_at': chunk.get('published_at'),
                    'excerpt': chunk.get('chunk_text', '')[:200] + '...',
                    'metadata': chunk.get('chunk_metadata', {})
                }
                sources.append(source)
        
        return sources


async def create_generator(
    api_key: Optional[str] = None,
    model: str = "claude-3-5-sonnet-20241022"
) -> RAGGenerator:
    """
    Create a RAG generator instance.
    
    Args:
        api_key: Anthropic API key
        model: Claude model name
        
    Returns:
        Initialized RAGGenerator
        
    Example:
        generator = await create_generator()
        response = await generator.generate(query, chunks)
    """
    return RAGGenerator(api_key=api_key, model=model)


# Global generator instance
_generator: Optional[RAGGenerator] = None


async def get_generator() -> RAGGenerator:
    """
    Get or create the global generator instance.
    
    Returns:
        Initialized RAGGenerator instance
    """
    global _generator
    
    if _generator is None:
        _generator = RAGGenerator()
        logger.info("Created global RAGGenerator instance")
    
    return _generator

