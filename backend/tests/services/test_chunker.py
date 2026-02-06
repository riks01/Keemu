"""
Tests for ContentChunker service.

This test module verifies:
1. YouTube chunking (timestamp-based and sentence-based)
2. Reddit chunking (thread-aware)
3. Blog chunking (section-based)
4. Generic chunking (fallback)
5. Token counting
6. Edge cases (empty content, very long content, etc.)
"""

import pytest
from datetime import datetime, timezone

from app.models.content import Channel, ContentItem, ContentSourceType
from app.models.user import User
from app.services.processors.chunker import ContentChunker, estimate_chunk_count


class TestContentChunkerBasics:
    """Test basic ContentChunker functionality."""
    
    def test_initialization(self):
        """Test ContentChunker initialization with custom settings."""
        chunker = ContentChunker(
            chunk_size=500,
            chunk_overlap=50,
            max_chunks=25
        )
        assert chunker.chunk_size == 500
        assert chunker.chunk_overlap == 50
        assert chunker.max_chunks == 25
    
    def test_initialization_defaults(self):
        """Test ContentChunker initialization with default settings."""
        chunker = ContentChunker()
        assert chunker.chunk_size == 800  # Default from settings
        assert chunker.chunk_overlap == 100
        assert chunker.max_chunks == 50
    
    def test_count_tokens(self):
        """Test token counting."""
        chunker = ContentChunker()
        
        # Short text
        text1 = "Hello world"
        tokens1 = chunker.count_tokens(text1)
        assert tokens1 > 0
        assert tokens1 < 10  # Should be ~2-3 tokens
        
        # Longer text
        text2 = "This is a much longer piece of text that should have more tokens."
        tokens2 = chunker.count_tokens(text2)
        assert tokens2 > tokens1
        assert tokens2 < 30


@pytest.mark.asyncio
class TestYouTubeChunking:
    """Test YouTube-specific chunking strategies."""
    
    async def test_youtube_chunking_with_timestamps(self, db_session):
        """Test YouTube chunking with transcript timestamps."""
        # Create dependencies
        user = User(email="test_youtube_chunking_with_timestamps@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test Channel"
        )
        db_session.add(channel)
        await db_session.flush()
        
        # Create content with timestamp segments
        transcript_segments = [
            {"start": 0, "end": 30, "text": "Welcome to this video about React hooks."},
            {"start": 30, "end": 60, "text": "Hooks allow you to use state in functional components."},
            {"start": 60, "end": 90, "text": "The useState hook is the most basic hook."},
            {"start": 90, "end": 120, "text": "You can also use useEffect for side effects."},
            {"start": 120, "end": 150, "text": "Let's see an example of how to use hooks."},
            {"start": 150, "end": 180, "text": "First, import React and the hooks you need."},
            {"start": 180, "end": 210, "text": "Then declare your state variables with useState."},
            {"start": 210, "end": 240, "text": "Finally, add your useEffect for side effects."}
        ]
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="test_video_123",
            title="React Hooks Tutorial",
            content_body=" ".join([seg["text"] for seg in transcript_segments]),
            author="Test Author",
            published_at=datetime.now(timezone.utc),
            content_metadata={
                "video_id": "test_video_123",
                "duration": 240,
                "transcript_language": "en",
                "transcript_segments": transcript_segments
            }
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Chunk the content
        chunker = ContentChunker(chunk_size=200, chunk_overlap=20)
        chunks = await chunker.chunk_content(content_item)
        
        # Verify chunks
        assert len(chunks) > 0
        assert len(chunks) <= chunker.max_chunks
        
        # Verify first chunk has metadata
        first_chunk = chunks[0]
        assert "start_time" in first_chunk["metadata"]
        assert "end_time" in first_chunk["metadata"]
        assert "duration" in first_chunk["metadata"]
        assert "transcript_language" in first_chunk["metadata"]
        assert first_chunk["metadata"]["transcript_language"] == "en"
        
        # Verify chunks have sequential indices
        for i, chunk in enumerate(chunks):
            assert chunk["index"] == i
    
    async def test_youtube_chunking_without_timestamps(self, db_session):
        """Test YouTube chunking without timestamps (fallback to sentences)."""
        user = User(email="test_youtube_chunking_without_timestamps@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test Channel"
        )
        db_session.add(channel)
        await db_session.flush()
        
        # Create content WITHOUT timestamp segments
        long_transcript = " ".join([
            "This is a sentence about React hooks.",
            "Hooks are a great feature.",
            "You can use useState for state.",
            "useEffect handles side effects.",
            "Custom hooks let you reuse logic."
        ] * 50)  # Repeat to create long content
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="test_video_456",
            title="React Hooks",
            content_body=long_transcript,
            author="Test Author",
            published_at=datetime.now(timezone.utc),
            content_metadata={
                "video_id": "test_video_456",
                "transcript_language": "en"
            }
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Chunk the content
        chunker = ContentChunker(chunk_size=100)  # Small chunk size to force multiple chunks
        chunks = await chunker.chunk_content(content_item)
        
        # Verify chunks were created
        assert len(chunks) > 1
        
        # Verify chunks have metadata
        for chunk in chunks:
            assert "text" in chunk
            assert "metadata" in chunk
            assert chunk["metadata"]["transcript_language"] == "en"


@pytest.mark.asyncio
class TestRedditChunking:
    """Test Reddit-specific chunking strategies."""
    
    async def test_reddit_chunking_post_and_comments(self, db_session):
        """Test Reddit chunking with post and comments."""
        user = User(email="test_reddit_chunking_post_and_comments@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.REDDIT,
            source_identifier="programming",
            name="r/programming"
        )
        db_session.add(channel)
        await db_session.flush()
        
        # Create Reddit post with comments
        post_text = """
        I just learned about React hooks and they're amazing!
        Here's why I think hooks are a game changer for React development.
        """
        
        comments = [
            {
                "id": "comment1",
                "author": "user1",
                "body": "Great post! Hooks definitely changed how I write React.",
                "score": 50,
                "depth": 0
            },
            {
                "id": "comment2",
                "author": "user2",
                "body": "I agree. useState and useEffect are my most used hooks.",
                "score": 25,
                "depth": 1
            },
            {
                "id": "comment3",
                "author": "user3",
                "body": "Have you tried custom hooks? They're even better!",
                "score": 30,
                "depth": 0
            }
        ]
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="post_abc123",
            title="React Hooks Are Amazing",
            content_body=post_text,
            author="test_user",
            published_at=datetime.now(timezone.utc),
            content_metadata={
                "post_id": "post_abc123",
                "subreddit": "programming",
                "score": 100,
                "num_comments": 3,
                "top_comments": comments
            }
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Chunk the content
        chunker = ContentChunker()
        chunks = await chunker.chunk_content(content_item)
        
        # Verify chunks
        assert len(chunks) > 0
        
        # First chunk should include the post
        first_chunk = chunks[0]
        assert first_chunk["metadata"]["is_post"] is True
        assert first_chunk["metadata"]["post_id"] == "post_abc123"
        assert first_chunk["metadata"]["subreddit"] == "programming"
        
        # Check if comments were included
        if len(chunks) > 1:
            # Comment chunks should have different metadata
            comment_chunk = chunks[1]
            assert "comment_ids" in comment_chunk["metadata"]
            assert "comment_depth" in comment_chunk["metadata"]
    
    async def test_reddit_chunking_long_post(self, db_session):
        """Test Reddit chunking with very long post."""
        user = User(email="test_reddit_chunking_long_post@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.REDDIT,
            source_identifier="programming",
            name="r/programming"
        )
        db_session.add(channel)
        await db_session.flush()
        
        # Create very long post (will need multiple chunks)
        long_post = " ".join([
            "This is a very long post about React hooks and how they work.",
            "I'm going to explain everything in great detail."
        ] * 200)  # Repeat many times
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="post_long",
            title="Comprehensive Guide to React Hooks",
            content_body=long_post,
            author="test_user",
            published_at=datetime.now(timezone.utc),
            content_metadata={
                "post_id": "post_long",
                "subreddit": "programming",
                "top_comments": []
            }
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Chunk with small chunk size
        chunker = ContentChunker(chunk_size=200)
        chunks = await chunker.chunk_content(content_item)
        
        # Should create multiple chunks
        assert len(chunks) > 1
        
        # All chunks should be related to the post
        for chunk in chunks:
            assert "post_id" in chunk["metadata"]


@pytest.mark.asyncio
class TestBlogChunking:
    """Test Blog-specific chunking strategies."""
    
    async def test_blog_chunking_with_sections(self, db_session):
        """Test blog chunking with markdown sections."""
        user = User(email="test_blog_chunking_with_sections@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.BLOG,
            source_identifier="https://blog.example.com/feed",
            name="Example Blog"
        )
        db_session.add(channel)
        await db_session.flush()
        
        # Create blog article with sections
        article_text = """
# Introduction to React Hooks

React Hooks were introduced in React 16.8 and have revolutionized how we write React components.

## What are Hooks?

Hooks are functions that let you use state and other React features in functional components.
They allow you to reuse stateful logic without changing your component hierarchy.

## useState Hook

The useState hook is the most fundamental hook.
It allows you to add state to functional components.

Here's an example:
```javascript
const [count, setCount] = useState(0);
```

## useEffect Hook

The useEffect hook lets you perform side effects in functional components.
It serves the same purpose as componentDidMount, componentDidUpdate, and componentWillUnmount.

### Basic Usage

You can use useEffect to fetch data, subscribe to events, or manually change the DOM.

## Conclusion

Hooks make React development more enjoyable and productive.
        """
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="article_123",
            title="Introduction to React Hooks",
            content_body=article_text,
            author="John Doe",
            published_at=datetime.now(timezone.utc),
            content_metadata={
                "url": "https://blog.example.com/react-hooks",
                "word_count": 150,
                "tags": ["react", "hooks", "javascript"]
            }
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Chunk the content
        chunker = ContentChunker()
        chunks = await chunker.chunk_content(content_item)
        
        # Verify chunks
        assert len(chunks) > 0
        
        # Chunks should have section metadata
        for chunk in chunks:
            assert "metadata" in chunk
            # At least some chunks should have section info
            if "section" in chunk["metadata"]:
                assert "heading_level" in chunk["metadata"]
                assert chunk["metadata"]["heading_level"] >= 1
    
    async def test_blog_chunking_without_sections(self, db_session):
        """Test blog chunking without clear sections (fallback to paragraphs)."""
        user = User(email="test_blog_chunking_without_sections@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.BLOG,
            source_identifier="https://blog.example.com/feed",
            name="Example Blog"
        )
        db_session.add(channel)
        await db_session.flush()
        
        # Create blog article without clear section markers
        article_text = """
React Hooks are a powerful feature introduced in React 16.8.

They allow you to use state and other React features in functional components.

The most commonly used hooks are useState and useEffect.

useState lets you add state to functional components.

useEffect lets you perform side effects like data fetching.
        """
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="article_456",
            title="React Hooks Overview",
            content_body=article_text,
            author="Jane Doe",
            published_at=datetime.now(timezone.utc),
            content_metadata={
                "url": "https://blog.example.com/hooks-overview"
            }
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Chunk the content
        chunker = ContentChunker()
        chunks = await chunker.chunk_content(content_item)
        
        # Should create at least one chunk
        assert len(chunks) > 0


@pytest.mark.asyncio
class TestGenericChunking:
    """Test generic/fallback chunking strategies."""
    
    async def test_generic_chunking(self, db_session):
        """Test generic chunking for unknown content types."""
        user = User(email="test_generic_chunking@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        # Create channel with unknown type (will use ContentSourceType.BLOG as fallback)
        channel = Channel(
            source_type=ContentSourceType.BLOG,
            source_identifier="unknown",
            name="Unknown Source"
        )
        db_session.add(channel)
        await db_session.flush()
        
        # Create content
        long_text = " ".join([
            "This is a test sentence.",
            "This is another test sentence.",
            "And here's one more."
        ] * 100)  # Repeat to create long content
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="unknown_123",
            title="Test Content",
            content_body=long_text,
            author="Test Author",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Chunk the content
        chunker = ContentChunker(chunk_size=100)  # Small chunks
        chunks = await chunker.chunk_content(content_item)
        
        # Should create multiple chunks
        assert len(chunks) > 1
        
        # Verify chunk structure
        for chunk in chunks:
            assert "index" in chunk
            assert "text" in chunk
            assert "metadata" in chunk
    
    async def test_extreme_oversized_content(self, db_session):
        """Test that recursive chunking handles extreme edge cases."""
        user = User(email="test_extreme@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.BLOG,
            source_identifier="extreme",
            name="Extreme Source"
        )
        db_session.add(channel)
        await db_session.flush()
        
        # Create extreme edge cases:
        # 1. Super long word with no spaces
        super_long_word = "a" * 1000
        
        # 2. Long sentence with no punctuation
        long_sentence_no_punctuation = " ".join(["word"] * 200)
        
        # 3. Mixed content
        extreme_text = f"{super_long_word} {long_sentence_no_punctuation}. Normal sentence here."
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="extreme_123",
            title="Extreme Content",
            content_body=extreme_text,
            author="Test Author",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Chunk with very small chunk_size to force recursive splitting
        chunker = ContentChunker(chunk_size=50)
        chunks = await chunker.chunk_content(content_item)
        
        # Should create multiple chunks
        assert len(chunks) > 1
        
        # CRITICAL: Verify NO chunk exceeds the token limit
        for chunk in chunks:
            chunk_tokens = chunker.count_tokens(chunk["text"])
            assert chunk_tokens <= 50, f"Chunk exceeded limit: {chunk_tokens} tokens (max: 50)"
            assert len(chunk["text"]) > 0, "Empty chunk created"
            assert len(chunk["text"]) > 0


@pytest.mark.asyncio
class TestChunkerEdgeCases:
    """Test edge cases and error handling."""
    
    async def test_empty_content(self, db_session):
        """Test chunking empty content."""
        user = User(email="test_empty_content@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test"
        )
        db_session.add(channel)
        await db_session.flush()
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="empty",
            title="Empty",
            content_body="",  # Empty content
            author="Test",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        chunker = ContentChunker()
        chunks = await chunker.chunk_content(content_item)
        
        # Should handle empty content gracefully
        assert isinstance(chunks, list)
    
    async def test_very_short_content(self, db_session):
        """Test chunking very short content."""
        user = User(email="test_very_short_content@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test"
        )
        db_session.add(channel)
        await db_session.flush()
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="short",
            title="Short",
            content_body="Hello world.",  # Very short
            author="Test",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        chunker = ContentChunker()
        chunks = await chunker.chunk_content(content_item)
        
        # Should create exactly one chunk
        assert len(chunks) == 1
        assert chunks[0]["text"] == "Hello world."
    
    async def test_max_chunks_limit(self, db_session):
        """Test that max_chunks limit is enforced."""
        user = User(email="test_max_chunks_limit@example.com", name="Test User")
        db_session.add(user)
        await db_session.flush()
        
        channel = Channel(
            source_type=ContentSourceType.YOUTUBE,
            source_identifier="UC_test",
            name="Test"
        )
        db_session.add(channel)
        await db_session.flush()
        
        # Create very long content
        very_long_content = " ".join([
            "This is a sentence that will be repeated many times."
        ] * 1000)
        
        content_item = ContentItem(
            channel_id=channel.id,
            external_id="very_long",
            title="Very Long",
            content_body=very_long_content,
            author="Test",
            published_at=datetime.now(timezone.utc)
        )
        db_session.add(content_item)
        await db_session.flush()
        
        # Chunk with small chunk size and max limit
        chunker = ContentChunker(chunk_size=50, max_chunks=10)
        chunks = await chunker.chunk_content(content_item)
        
        # Should not exceed max_chunks
        assert len(chunks) <= 10


def test_estimate_chunk_count():
    """Test chunk count estimation."""
    # Short content
    assert estimate_chunk_count(100) == 1
    
    # Medium content
    estimate = estimate_chunk_count(10000, chunk_size=800)
    assert estimate > 1
    assert estimate < 10
    
    # Very long content
    estimate = estimate_chunk_count(100000, chunk_size=800)
    assert estimate > 10

