"""
Pydantic schemas for Chat API

This module defines request/response models for the RAG chat endpoints.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict


# ========================================
# Conversation Schemas
# ========================================

class ConversationCreate(BaseModel):
    """Request schema for creating a conversation."""
    
    title: Optional[str] = Field(
        default="New Conversation",
        description="Conversation title",
        max_length=200
    )


class ConversationResponse(BaseModel):
    """Response schema for a conversation."""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: int = Field(description="Conversation ID")
    user_id: int = Field(description="User ID")
    title: str = Field(description="Conversation title")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")


class ConversationListResponse(BaseModel):
    """Response schema for list of conversations."""
    
    conversations: List[ConversationResponse] = Field(description="List of conversations")
    total: int = Field(description="Total number of conversations")
    limit: int = Field(description="Limit used")
    offset: int = Field(description="Offset used")


# ========================================
# Message Schemas
# ========================================

class MessageCreate(BaseModel):
    """Request schema for creating a message."""
    
    content: str = Field(
        description="Message content",
        min_length=1,
        max_length=4000
    )


class MessageResponse(BaseModel):
    """Response schema for a message."""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: int = Field(description="Message ID")
    conversation_id: int = Field(description="Conversation ID")
    role: str = Field(description="Message role: user or assistant")
    content: str = Field(description="Message content")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Message metadata (sources, model, etc.)"
    )
    created_at: datetime = Field(description="Creation timestamp")


# ========================================
# Chat / RAG Schemas
# ========================================

class ChatRequest(BaseModel):
    """Request schema for chat/RAG query."""
    
    message: str = Field(
        description="User's message/query",
        min_length=1,
        max_length=4000
    )
    
    top_k: Optional[int] = Field(
        default=50,
        description="Number of chunks to retrieve",
        ge=1,
        le=100
    )
    
    rerank_top_k: Optional[int] = Field(
        default=5,
        description="Number of chunks after reranking",
        ge=1,
        le=20
    )


class SourceInfo(BaseModel):
    """Information about a source used in the answer."""
    
    source_number: int = Field(description="Source number [1, 2, ...]")
    chunk_id: Optional[int] = Field(default=None, description="Chunk ID")
    content_item_id: Optional[int] = Field(default=None, description="Content item ID")
    title: Optional[str] = Field(default=None, description="Content title")
    author: Optional[str] = Field(default=None, description="Content author")
    source_type: Optional[str] = Field(default=None, description="Source type (youtube, reddit, blog)")
    channel_name: Optional[str] = Field(default=None, description="Channel name")
    published_at: Optional[datetime] = Field(default=None, description="Publication date")
    excerpt: Optional[str] = Field(default=None, description="Text excerpt")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Chunk metadata")


class ChatResponse(BaseModel):
    """Response schema for chat/RAG query."""
    
    message_id: int = Field(description="Message ID")
    answer: str = Field(description="Generated answer")
    sources: List[SourceInfo] = Field(description="Sources used in the answer")
    model: str = Field(description="Model used for generation")
    tokens_used: int = Field(description="Total tokens used")


# ========================================
# Quick Chat Schema (without conversation)
# ========================================

class QuickChatRequest(BaseModel):
    """Request schema for quick chat (no conversation history)."""
    
    query: str = Field(
        description="User's query",
        min_length=1,
        max_length=4000
    )
    
    top_k: Optional[int] = Field(
        default=50,
        description="Number of chunks to retrieve",
        ge=1,
        le=100
    )
    
    rerank_top_k: Optional[int] = Field(
        default=5,
        description="Number of chunks after reranking",
        ge=1,
        le=20
    )


class QuickChatResponse(BaseModel):
    """Response schema for quick chat."""
    
    answer: str = Field(description="Generated answer")
    sources: List[SourceInfo] = Field(description="Sources used")
    model: str = Field(description="Model used")
    tokens_used: int = Field(description="Tokens used")

