"""
RAG (Retrieval-Augmented Generation) Services

This package contains all services for the RAG pipeline:
- Query processing
- Hybrid retrieval (semantic + keyword)
- Reranking
- Generation (Claude integration)
- Conversation management
"""

from app.services.rag.query_service import QueryService, get_query_service
from app.services.rag.retriever import HybridRetriever, create_retriever
from app.services.rag.reranker import CrossEncoderReranker, get_reranker, shutdown_reranker
from app.services.rag.generator import RAGGenerator, get_generator, create_generator
from app.services.rag.conversation_service import ConversationService, create_conversation_service

__all__ = [
    "QueryService",
    "get_query_service",
    "HybridRetriever",
    "create_retriever",
    "CrossEncoderReranker",
    "get_reranker",
    "shutdown_reranker",
    "RAGGenerator",
    "get_generator",
    "create_generator",
    "ConversationService",
    "create_conversation_service",
]

