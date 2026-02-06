"""
Chat API Routes

This module provides REST API endpoints for RAG chat functionality:
- Create and manage conversations
- Send messages and get responses
- Stream responses
- List conversation history

All endpoints require authentication.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_active_user
from app.db.deps import get_db
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.services.rag import (
    get_query_service,
    create_retriever,
    get_reranker,
    get_generator,
    create_conversation_service
)
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
    ChatRequest,
    ChatResponse,
    ConversationListResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ========================================
# Conversation Management
# ========================================

@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    conversation_data: ConversationCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new conversation.
    
    Args:
        conversation_data: Conversation title (optional)
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Created conversation
    """
    try:
        conv_service = create_conversation_service(db)
        conversation = await conv_service.create_conversation(
            user_id=current_user.id,
            title=conversation_data.title
        )
        
        return ConversationResponse.model_validate(conversation)
        
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation"
        )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List user's conversations.
    
    Args:
        limit: Maximum conversations to return
        offset: Pagination offset
        current_user: Authenticated user
        db: Database session
        
    Returns:
        List of conversations
    """
    try:
        conv_service = create_conversation_service(db)
        conversations = await conv_service.list_user_conversations(
            user_id=current_user.id,
            limit=limit,
            offset=offset
        )
        total = await conv_service.get_conversation_count(current_user.id)
        
        return ConversationListResponse(
            conversations=[ConversationResponse.model_validate(c) for c in conversations],
            total=total,
            limit=limit,
            offset=offset
        )
        
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list conversations"
        )


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific conversation.
    
    Args:
        conversation_id: Conversation ID
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Conversation details
    """
    try:
        conv_service = create_conversation_service(db)
        conversation = await conv_service.get_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        return ConversationResponse.model_validate(conversation)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get conversation"
        )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a conversation.
    
    Args:
        conversation_id: Conversation ID
        current_user: Authenticated user
        db: Database session
    """
    try:
        conv_service = create_conversation_service(db)
        deleted = await conv_service.delete_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete conversation"
        )


# ========================================
# Message Management
# ========================================

@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    conversation_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get messages for a conversation.
    
    Args:
        conversation_id: Conversation ID
        limit: Maximum messages to return
        offset: Pagination offset
        current_user: Authenticated user
        db: Database session
        
    Returns:
        List of messages
    """
    try:
        conv_service = create_conversation_service(db)
        
        # Verify conversation belongs to user
        conversation = await conv_service.get_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        messages = await conv_service.get_messages(
            conversation_id=conversation_id,
            limit=limit,
            offset=offset
        )
        
        return [MessageResponse.model_validate(m) for m in messages]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get messages"
        )


# ========================================
# Chat / RAG Query
# ========================================

@router.post("/conversations/{conversation_id}/messages", response_model=ChatResponse)
async def send_message(
    conversation_id: int,
    message_data: ChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message and get RAG response.
    
    This endpoint:
    1. Adds user message to conversation
    2. Processes query through RAG pipeline (query -> retrieve -> rerank -> generate)
    3. Adds assistant response to conversation
    4. Returns the response with sources
    
    Args:
        conversation_id: Conversation ID
        message_data: User's message
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Assistant's response with sources
    """
    try:
        conv_service = create_conversation_service(db)
        
        # Verify conversation belongs to user
        conversation = await conv_service.get_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # Step 1: Add user message
        user_message = await conv_service.add_user_message(
            conversation_id=conversation_id,
            content=message_data.message
        )
        
        logger.info(f"Processing RAG query: '{message_data.message[:50]}...'")
        
        # Step 2: Process query
        query_service = await get_query_service()
        query_result = await query_service.process_query(message_data.message)
        
        # Step 3: Retrieve
        retriever = await create_retriever(db)
        candidates = await retriever.retrieve(
            query_embedding=query_result['embedding'],
            query_text=query_result['cleaned'],
            top_k=message_data.top_k or 50
        )
        
        logger.info(f"Retrieved {len(candidates)} candidates")
        
        # Step 4: Rerank
        reranker = await get_reranker()
        top_chunks = await reranker.rerank(
            query=message_data.message,
            candidates=candidates,
            top_k=message_data.rerank_top_k or 5
        )
        
        logger.info(f"Reranked to top {len(top_chunks)} chunks")
        
        # Step 5: Generate response
        generator = await get_generator()
        
        # Get conversation history (last N messages for context)
        history = await conv_service.get_conversation_history(
            conversation_id=conversation_id,
            max_messages=10,  # Last 10 messages
            for_llm=True
        )
        
        # Remove the user message we just added (it's in the query)
        if history and history[-1]['role'] == 'user':
            history = history[:-1]
        
        generation_result = await generator.generate(
            query=message_data.message,
            chunks=top_chunks,
            conversation_history=history,
            include_citations=True
        )
        
        logger.info(f"Generated response: {len(generation_result['answer'])} chars")
        
        # Step 6: Add assistant message
        assistant_message = await conv_service.add_assistant_message(
            conversation_id=conversation_id,
            content=generation_result['answer'],
            sources=generation_result['sources'],
            model=generation_result['model'],
            tokens_used=generation_result['tokens_used']
        )
        
        # Step 7: Return response
        return ChatResponse(
            message_id=assistant_message.id,
            answer=generation_result['answer'],
            sources=generation_result['sources'],
            model=generation_result['model'],
            tokens_used=generation_result['tokens_used']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process message: {str(e)}"
        )


@router.post("/conversations/{conversation_id}/messages/stream")
async def send_message_stream(
    conversation_id: int,
    message_data: ChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message and get streaming RAG response.
    
    This endpoint streams the response as it's generated.
    
    Args:
        conversation_id: Conversation ID
        message_data: User's message
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Streaming response (text/event-stream)
    """
    try:
        conv_service = create_conversation_service(db)
        
        # Verify conversation
        conversation = await conv_service.get_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id
        )
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # Add user message
        await conv_service.add_user_message(
            conversation_id=conversation_id,
            content=message_data.message
        )
        
        # Process query
        query_service = await get_query_service()
        query_result = await query_service.process_query(message_data.message)
        
        # Retrieve and rerank
        retriever = await create_retriever(db)
        candidates = await retriever.retrieve(
            query_embedding=query_result['embedding'],
            query_text=query_result['cleaned'],
            top_k=message_data.top_k or 50
        )
        
        reranker = await get_reranker()
        top_chunks = await reranker.rerank(
            query=message_data.message,
            candidates=candidates,
            top_k=message_data.rerank_top_k or 5
        )
        
        # Get history
        history = await conv_service.get_conversation_history(
            conversation_id=conversation_id,
            max_messages=10,
            for_llm=True
        )
        
        if history and history[-1]['role'] == 'user':
            history = history[:-1]
        
        # Generate streaming response
        generator = await get_generator()
        
        async def stream_generator():
            """Stream the response chunks."""
            full_response = ""
            
            async for chunk in generator.generate_stream(
                query=message_data.message,
                chunks=top_chunks,
                conversation_history=history
            ):
                full_response += chunk
                yield chunk
            
            # After streaming completes, save the assistant message
            # Note: This happens after the stream is consumed
            await conv_service.add_assistant_message(
                conversation_id=conversation_id,
                content=full_response,
                sources=generator._build_sources_list(top_chunks, list(range(len(top_chunks)))),
                model=generator.model
            )
        
        return StreamingResponse(
            stream_generator(),
            media_type="text/plain"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error streaming message: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stream message: {str(e)}"
        )

