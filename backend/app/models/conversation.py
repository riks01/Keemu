"""
Conversation Models

This module contains conversation-related models for the KeeMU RAG chat interface.

Models Included:
----------------
1. Conversation - User chat sessions with the RAG system
2. Message - Individual messages within conversations
3. MessageRole (Enum) - Role of message sender

Database Tables:
----------------
- conversations: Stores chat sessions
- messages: Stores individual messages
- message_chunks: Junction table linking messages to retrieved chunks

Relationships:
--------------
- User (1) ←→ (Many) Conversation
- Conversation (1) ←→ (Many) Message
- Message (Many) ←→ (Many) ContentChunk via message_chunks
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, String100, String255

if TYPE_CHECKING:
    from app.models.content import ContentChunk
    from app.models.user import User


# ================================
# Enums
# ================================

class MessageRole(str, enum.Enum):
    """
    Enum for message roles in conversation.
    
    Roles:
    ------
    - USER: Message from the user (question/query)
    - ASSISTANT: Response from the RAG system (AI-generated answer)
    - SYSTEM: System messages (instructions, context, errors)
    
    Standard in Chat APIs:
    ----------------------
    This follows the OpenAI/Anthropic chat message format:
    [
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "What is React?"},
        {"role": "assistant", "content": "React is a JavaScript library..."}
    ]
    
    Usage in RAG:
    -------------
    - USER messages trigger retrieval and generation
    - ASSISTANT messages contain the generated responses with citations
    - SYSTEM messages provide context or handle errors
    """
    
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


# ================================
# Message-Chunk Junction Table
# ================================
# Many-to-many relationship between messages and content chunks
# Tracks which chunks were used to generate each assistant response

message_chunks = Table(
    "message_chunks",
    BaseModel.metadata,
    # Message foreign key
    Column(
        "message_id",
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
        comment="Foreign key to messages table"
    ),
    # ContentChunk foreign key
    Column(
        "chunk_id",
        Integer,
        ForeignKey("content_chunks.id", ondelete="CASCADE"),
        primary_key=True,
        comment="Foreign key to content_chunks table"
    ),
    # Relevance score (how relevant was this chunk to the query?)
    Column(
        "relevance_score",
        Float,
        nullable=True,
        comment="Relevance score from retrieval (0-1)"
    ),
    # Rank in retrieval results
    Column(
        "rank",
        Integer,
        nullable=True,
        comment="Rank in retrieval results (1=most relevant)"
    ),
    comment="Junction table linking messages to retrieved content chunks"
)
# Why a junction table?
# - Assistant messages are generated from multiple chunks
# - Need to track which chunks were used (for citations)
# - Store relevance scores for explainability
# - Enable "show sources" feature


# ================================
# Conversation Model
# ================================

class Conversation(BaseModel):
    """
    Conversation model - represents a chat session with the RAG system.
    
    This model stores metadata about a chat conversation, while individual
    messages are stored in the Message model.
    
    Table: conversations
    --------------------
    Each conversation belongs to one user and contains multiple messages.
    
    Use Cases:
    ----------
    1. Chat Interface:
       - User asks: "What did Fireship say about React?"
       - System retrieves relevant chunks
       - Claude generates response with citations
       - All stored as messages in this conversation
    
    2. Multi-Turn Conversations:
       - User: "What is React hooks?"
       - System: "React hooks are..."
       - User: "Can you show an example?"
       - System: "Here's an example from the video at 3:45..."
       (Context maintained across messages)
    
    3. Conversation History:
       - Users can view past conversations
       - Continue previous conversations
       - Search conversation history
    
    Conversation Lifecycle:
    -----------------------
    1. User clicks "New Chat" → Create Conversation
    2. User sends message → Create Message (role=user)
    3. System retrieves chunks → Link to Message
    4. System generates response → Create Message (role=assistant)
    5. User closes chat → is_active=False
    6. User archives → archived=True
    
    Metadata Storage (JSONB):
    -------------------------
    Store conversation-specific settings:
    {
        "filters": {
            "content_types": ["youtube"],
            "channels": [1, 5, 10],
            "date_range": {"start": "2024-01-01", "end": "2024-12-31"}
        },
        "settings": {
            "temperature": 0.7,
            "max_tokens": 500
        },
        "stats": {
            "total_chunks_retrieved": 50,
            "total_tokens_used": 5000,
            "average_response_time": 2.5
        }
    }
    
    Example Usage:
    --------------
    # Create new conversation
    conversation = Conversation(
        user_id=user.id,
        title="Questions about React Hooks",
        is_active=True
    )
    db.add(conversation)
    await db.commit()
    
    # Add messages
    user_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content="What are React hooks?"
    )
    db.add(user_message)
    
    # Generate response (with RAG)
    chunks = retriever.retrieve(user_message.content)
    response_text = generator.generate(user_message.content, chunks)
    
    assistant_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=response_text,
        retrieved_chunks=chunks  # Links via message_chunks table
    )
    db.add(assistant_message)
    """
    
    __tablename__ = "conversations"
    
    # ================================
    # Foreign Key (Links to User)
    # ================================
    
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to users table"
    )
    # Links to User
    # CASCADE: Delete user → delete all their conversations
    # Index: Fast queries for "all conversations for this user"
    
    # ================================
    # Conversation Metadata
    # ================================
    
    title: Mapped[str] = mapped_column(
        String255,
        nullable=False,
        default="New Conversation",
        comment="Conversation title (auto-generated or user-provided)"
    )
    # Conversation title for display
    # Can be auto-generated from first message
    # Example: "Questions about React Hooks"
    # User can edit this title
    
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether conversation is currently active"
    )
    # True: Conversation is ongoing
    # False: User closed/ended the conversation
    # Used to distinguish active vs. completed chats
    
    archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether conversation is archived"
    )
    # True: User archived this conversation
    # False: Normal conversation
    # Archived conversations hidden from main list
    # Can be unarchived later
    
    conversation_metadata: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Conversation-specific metadata (filters, settings, stats)"
    )
    # Flexible storage for conversation data
    # Filters: Which content sources to search
    # Settings: Generation parameters
    # Stats: Usage metrics
    
    # ================================
    # Statistics
    # ================================
    
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total number of messages in conversation"
    )
    # Track conversation length
    # Updated automatically via trigger or application logic
    # Useful for:
    # - Showing conversation size
    # - Limiting context window
    # - Analytics
    
    total_tokens_used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total tokens used in this conversation (for cost tracking)"
    )
    # Track token usage across all messages
    # Includes: prompt tokens + completion tokens
    # Used for:
    # - Cost estimation
    # - Usage analytics
    # - Rate limiting
    
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp of last message in conversation (UTC)"
    )
    # When was the last message sent?
    # Used for:
    # - Sorting conversations (most recent first)
    # - Detecting inactive conversations
    # - "Continue where you left off" feature
    
    # ================================
    # Relationships
    # ================================
    
    user: Mapped["User"] = relationship(
        "User",
        back_populates="conversations",
        lazy="joined"
    )
    # Many-to-one with User
    # conversation.user gives you the User object
    
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Message.created_at"
    )
    # One-to-many with Message
    # conversation.messages gives you all messages in order
    # Delete conversation → delete all messages
    # Ordered by created_at for chronological display
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"Conversation(id={self.id}, user_id={self.user_id}, "
            f"title='{self.title[:30]}...', messages={self.message_count})"
        )
    
    @property
    def is_empty(self) -> bool:
        """Check if conversation has no messages."""
        return self.message_count == 0
    
    @property
    def is_ongoing(self) -> bool:
        """Check if conversation is active and not archived."""
        return self.is_active and not self.archived


# ================================
# Message Model
# ================================

class Message(BaseModel):
    """
    Message model - represents a single message in a conversation.
    
    This model stores individual messages within a chat conversation,
    including both user queries and assistant responses.
    
    Table: messages
    ---------------
    Each message belongs to one conversation.
    
    Message Types:
    --------------
    1. USER messages:
       - User's question or query
       - Triggers RAG retrieval and generation
       - Example: "What did Fireship say about React hooks?"
    
    2. ASSISTANT messages:
       - AI-generated response
       - Based on retrieved chunks
       - Includes citations to source content
       - Example: "According to the video 'React Hooks Explained' at 3:45..."
    
    3. SYSTEM messages:
       - System notifications
       - Error messages
       - Context updates
       - Example: "Search filters updated to only include YouTube content"
    
    RAG Workflow:
    -------------
    1. User sends message (role=user)
    2. System embeds the query
    3. System retrieves relevant chunks (hybrid search)
    4. System reranks top chunks (cross-encoder)
    5. System generates response using Claude + retrieved context
    6. System creates assistant message with retrieved_chunks linked
    
    Citations & Sources:
    --------------------
    Assistant messages link to the ContentChunks used for generation.
    This enables:
    - "Show sources" feature
    - Verifiable responses
    - Jump to original content
    - Relevance scoring display
    
    Example: message.retrieved_chunks → [chunk1, chunk2, chunk3]
    
    Token Tracking:
    ---------------
    For cost estimation and rate limiting:
    - prompt_tokens: Tokens in user query + context
    - completion_tokens: Tokens in assistant response
    - total_tokens: prompt_tokens + completion_tokens
    
    Example Usage:
    --------------
    # User message
    user_msg = Message(
        conversation_id=conv_id,
        role=MessageRole.USER,
        content="What are React hooks?",
        prompt_tokens=5,
        completion_tokens=0,
        total_tokens=5
    )
    
    # Retrieve chunks
    chunks = retriever.retrieve(user_msg.content, top_k=5)
    
    # Generate response
    response = generator.generate(
        query=user_msg.content,
        context=chunks,
        conversation_history=conv.messages[-5:]
    )
    
    # Assistant message with citations
    assistant_msg = Message(
        conversation_id=conv_id,
        role=MessageRole.ASSISTANT,
        content=response.text,
        retrieved_chunks=chunks,  # Linked via message_chunks
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        total_tokens=response.total_tokens
    )
    """
    
    __tablename__ = "messages"
    
    # ================================
    # Foreign Key (Links to Conversation)
    # ================================
    
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to conversations table"
    )
    # Links to Conversation
    # CASCADE: Delete conversation → delete all its messages
    # Index: Fast queries for "all messages in this conversation"
    
    # ================================
    # Message Content
    # ================================
    
    role: Mapped[MessageRole] = mapped_column(
        nullable=False,
        comment="Message role: user, assistant, or system"
    )
    # Who sent this message?
    # USER: Human user
    # ASSISTANT: AI/RAG system
    # SYSTEM: Application (errors, notifications)
    
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Message text content"
    )
    # The actual message text
    # USER: "What are React hooks?"
    # ASSISTANT: "React hooks are functions that let you..."
    # TEXT type: No length limit (long responses)
    
    # ================================
    # Token Usage (for cost tracking)
    # ================================
    
    prompt_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of tokens in prompt (query + context)"
    )
    # Tokens sent to LLM as input
    # Includes: user query + retrieved context + conversation history
    
    completion_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of tokens in completion (generated response)"
    )
    # Tokens generated by LLM as output
    # Only applies to ASSISTANT messages
    # USER and SYSTEM messages: completion_tokens = 0
    
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total tokens used (prompt + completion)"
    )
    # Sum of prompt_tokens and completion_tokens
    # Used for: Cost calculation, rate limiting, analytics
    
    # ================================
    # Metadata
    # ================================
    
    message_metadata: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Message-specific metadata (model, temperature, filters, etc.)"
    )
    # Store additional message information:
    # {
    #     "model": "claude-3-5-haiku-20241022",
    #     "temperature": 0.7,
    #     "retrieval_query": "modified query for retrieval",
    #     "retrieval_time_ms": 150,
    #     "generation_time_ms": 1200,
    #     "filters": {"content_types": ["youtube"]},
    #     "error": "Rate limit exceeded"
    # }
    
    # ================================
    # Relationships
    # ================================
    
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
        lazy="joined"
    )
    # Many-to-one with Conversation
    # message.conversation gives you the Conversation object
    
    retrieved_chunks: Mapped[list["ContentChunk"]] = relationship(
        "ContentChunk",
        secondary=message_chunks,
        lazy="selectin"
    )
    # Many-to-many with ContentChunk (via message_chunks junction table)
    # message.retrieved_chunks gives you all chunks used for this message
    # Only populated for ASSISTANT messages
    # Used for citations and "show sources" feature
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        content_preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return (
            f"Message(id={self.id}, conversation_id={self.conversation_id}, "
            f"role={self.role.value}, content='{content_preview}')"
        )
    
    @property
    def is_user_message(self) -> bool:
        """Check if message is from user."""
        return self.role == MessageRole.USER
    
    @property
    def is_assistant_message(self) -> bool:
        """Check if message is from assistant."""
        return self.role == MessageRole.ASSISTANT
    
    @property
    def has_citations(self) -> bool:
        """Check if message has retrieved chunks (citations)."""
        return len(self.retrieved_chunks) > 0 if self.retrieved_chunks else False

