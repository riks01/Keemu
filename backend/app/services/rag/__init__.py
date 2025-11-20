"""
RAG (Retrieval-Augmented Generation) Services

This package contains all services for the RAG pipeline:
- Query processing
- Hybrid retrieval (semantic + keyword)
- Reranking
- Context generation
"""

from app.services.rag.query_service import QueryService, get_query_service
from app.services.rag.retriever import HybridRetriever, create_retriever
from app.services.rag.reranker import CrossEncoderReranker, get_reranker, shutdown_reranker

__all__ = [
    "QueryService",
    "get_query_service",
    "HybridRetriever",
    "create_retriever",
    "CrossEncoderReranker",
    "get_reranker",
    "shutdown_reranker",
]

