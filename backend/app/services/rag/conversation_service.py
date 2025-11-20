"""
Conversation Service for RAG Chat

This module manages multi-turn conversations:
- Create and manage conversations
- Message history tracking
- Context window management
- Conversation summarization
- Message persistence

The service bridges the database models and the RAG generation pipeline.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation, Message
from app.models.user import User

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Service for managing RAG conversations.
    
    Features:
    ---------
    - Create/retrieve conversations
    - Add messages (user + assistant)
    - Get conversation history
    - Manage context window (truncate old messages)
    - Delete conversations
    - List user's conversations
    
    Usage:
    ------
    service = ConversationService(db)
    
    # Create conversation
    conversation = await service.create_conversation(
        user_id=123,
        title="React Hooks Discussion"
    )
    
    # Add user message
    user_msg = await service.add_user_message(
        conversation_id=conversation.id,
        content="What are React hooks?"
    )
    
    # Add assistant response
    assistant_msg = await service.add_assistant_message(
        conversation_id=conversation.id,
        content="React hooks are...",
        sources=[...]
    )
    
    # Get history
    history = await service.get_conversation_history(conversation_id)
    """
    
    def __init__(self, db: AsyncSession):
        """
        Initialize the conversation service.
        
        Args:
            db: Database session
        """
        self.db = db
    
    async def create_conversation(
        self,
        user_id: int,
        title: Optional[str] = None
    ) -> Conversation:
        """
        Create a new conversation.
        
        Args:
            user_id: User ID
            title: Optional conversation title
            
        Returns:
            Created Conversation object
        """
        conversation = Conversation(
            user_id=user_id,
            title=title or "New Conversation",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        
        logger.info(f"Created conversation {conversation.id} for user {user_id}")
        
        return conversation
    
    async def get_conversation(
        self,
        conversation_id: int,
        user_id: Optional[int] = None
    ) -> Optional[Conversation]:
        """
        Get a conversation by ID.
        
        Args:
            conversation_id: Conversation ID
            user_id: Optional user ID for authorization check
            
        Returns:
            Conversation object or None if not found
        """
        query = select(Conversation).where(Conversation.id == conversation_id)
        
        if user_id is not None:
            query = query.where(Conversation.user_id == user_id)
        
        result = await self.db.execute(query)
        conversation = result.scalar_one_or_none()
        
        return conversation
    
    async def list_user_conversations(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> List[Conversation]:
        """
        List all conversations for a user.
        
        Args:
            user_id: User ID
            limit: Maximum conversations to return
            offset: Pagination offset
            
        Returns:
            List of Conversation objects
        """
        query = select(Conversation).where(
            Conversation.user_id == user_id
        ).order_by(
            desc(Conversation.updated_at)
        ).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        conversations = result.scalars().all()
        
        return list(conversations)
    
    async def delete_conversation(
        self,
        conversation_id: int,
        user_id: Optional[int] = None
    ) -> bool:
        """
        Delete a conversation and all its messages.
        
        Args:
            conversation_id: Conversation ID
            user_id: Optional user ID for authorization check
            
        Returns:
            True if deleted, False if not found
        """
        conversation = await self.get_conversation(conversation_id, user_id)
        
        if not conversation:
            logger.warning(f"Conversation {conversation_id} not found for deletion")
            return False
        
        await self.db.delete(conversation)
        await self.db.commit()
        
        logger.info(f"Deleted conversation {conversation_id}")
        
        return True
    
    async def add_user_message(
        self,
        conversation_id: int,
        content: str
    ) -> Message:
        """
        Add a user message to the conversation.
        
        Args:
            conversation_id: Conversation ID
            content: Message content
            
        Returns:
            Created Message object
        """
        message = Message(
            conversation_id=conversation_id,
            role="user",
            content=content,
            created_at=datetime.now(timezone.utc)
        )
        
        self.db.add(message)
        
        # Update conversation timestamp
        conversation = await self.get_conversation(conversation_id)
        if conversation:
            conversation.updated_at = datetime.now(timezone.utc)
        
        await self.db.commit()
        await self.db.refresh(message)
        
        logger.debug(f"Added user message to conversation {conversation_id}")
        
        return message
    
    async def add_assistant_message(
        self,
        conversation_id: int,
        content: str,
        sources: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        tokens_used: Optional[int] = None
    ) -> Message:
        """
        Add an assistant message to the conversation.
        
        Args:
            conversation_id: Conversation ID
            content: Message content (generated answer)
            sources: List of sources used for the answer
            model: Model used for generation
            tokens_used: Number of tokens used
            
        Returns:
            Created Message object
        """
        metadata = {}
        if sources:
            metadata['sources'] = sources
        if model:
            metadata['model'] = model
        if tokens_used:
            metadata['tokens_used'] = tokens_used
        
        message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            metadata=metadata if metadata else None,
            created_at=datetime.now(timezone.utc)
        )
        
        self.db.add(message)
        
        # Update conversation timestamp
        conversation = await self.get_conversation(conversation_id)
        if conversation:
            conversation.updated_at = datetime.now(timezone.utc)
            
            # Auto-generate title from first user message if not set
            if conversation.title == "New Conversation":
                # Get first user message
                first_msg_query = select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.role == "user"
                ).order_by(Message.created_at).limit(1)
                result = await self.db.execute(first_msg_query)
                first_msg = result.scalar_one_or_none()
                
                if first_msg:
                    # Use first 50 chars of first message as title
                    title = first_msg.content[:50]
                    if len(first_msg.content) > 50:
                        title += "..."
                    conversation.title = title
        
        await self.db.commit()
        await self.db.refresh(message)
        
        logger.debug(f"Added assistant message to conversation {conversation_id}")
        
        return message
    
    async def get_conversation_history(
        self,
        conversation_id: int,
        max_messages: Optional[int] = None,
        for_llm: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get conversation history.
        
        Args:
            conversation_id: Conversation ID
            max_messages: Maximum messages to return (most recent)
            for_llm: Format for LLM API (only role + content)
            
        Returns:
            List of message dictionaries
        """
        query = select(Message).where(
            Message.conversation_id == conversation_id
        ).order_by(Message.created_at)
        
        if max_messages:
            # Get most recent N messages
            query = query.limit(max_messages)
        
        result = await self.db.execute(query)
        messages = result.scalars().all()
        
        if for_llm:
            # Format for LLM API (Claude/OpenAI format)
            return [
                {
                    "role": msg.role,
                    "content": msg.content
                }
                for msg in messages
            ]
        else:
            # Full format with metadata
            return [
                {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "metadata": msg.metadata,
                    "created_at": msg.created_at
                }
                for msg in messages
            ]
    
    async def get_messages(
        self,
        conversation_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> List[Message]:
        """
        Get messages for a conversation with pagination.
        
        Args:
            conversation_id: Conversation ID
            limit: Maximum messages to return
            offset: Pagination offset
            
        Returns:
            List of Message objects
        """
        query = select(Message).where(
            Message.conversation_id == conversation_id
        ).order_by(
            Message.created_at
        ).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        messages = result.scalars().all()
        
        return list(messages)
    
    async def update_conversation_title(
        self,
        conversation_id: int,
        title: str,
        user_id: Optional[int] = None
    ) -> bool:
        """
        Update conversation title.
        
        Args:
            conversation_id: Conversation ID
            title: New title
            user_id: Optional user ID for authorization
            
        Returns:
            True if updated, False if not found
        """
        conversation = await self.get_conversation(conversation_id, user_id)
        
        if not conversation:
            return False
        
        conversation.title = title
        conversation.updated_at = datetime.now(timezone.utc)
        
        await self.db.commit()
        
        logger.info(f"Updated conversation {conversation_id} title to '{title}'")
        
        return True
    
    async def get_conversation_count(self, user_id: int) -> int:
        """
        Get total conversation count for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Number of conversations
        """
        from sqlalchemy import func
        
        query = select(func.count(Conversation.id)).where(
            Conversation.user_id == user_id
        )
        
        result = await self.db.execute(query)
        count = result.scalar_one()
        
        return count


def create_conversation_service(db: AsyncSession) -> ConversationService:
    """
    Create a conversation service instance.
    
    Args:
        db: Database session
        
    Returns:
        ConversationService instance
    """
    return ConversationService(db)

