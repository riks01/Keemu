"""
Content Query Service

Utility functions for querying content items with metadata filters.
Provides high-level API for filtering content by JSONB metadata fields.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy import select, func, and_, or_, desc, cast, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem, Channel, ProcessingStatus
from app.models.user import ContentSourceType

logger = logging.getLogger(__name__)


class ContentQueryService:
    """Service for querying content items with metadata filters."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ========================================
    # Basic Queries
    # ========================================
    
    async def get_by_channel(
        self,
        channel_id: int,
        status: Optional[ProcessingStatus] = ProcessingStatus.PROCESSED,
        limit: int = 50
    ) -> List[ContentItem]:
        """Get content items from a specific channel."""
        query = (
            select(ContentItem)
            .where(ContentItem.channel_id == channel_id)
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        if status:
            query = query.where(ContentItem.processing_status == status)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_recent(
        self,
        days: int = 7,
        source_type: Optional[ContentSourceType] = None,
        limit: int = 100
    ) -> List[ContentItem]:
        """Get recently published content items."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                ContentItem.published_at >= cutoff_date,
                ContentItem.processing_status == ProcessingStatus.PROCESSED
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        if source_type:
            query = query.where(Channel.source_type == source_type)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    # ========================================
    # Metadata Queries (YouTube-specific)
    # ========================================
    
    async def get_popular_videos(
        self,
        channel_id: Optional[int] = None,
        min_views: int = 10000,
        limit: int = 20
    ) -> List[ContentItem]:
        """
        Get popular videos based on view count.
        
        Uses JSONB metadata query: content_metadata->>'view_count'
        """
        # Cast view_count to integer for comparison
        view_count_expr = cast(
            ContentItem.content_metadata['view_count'],
            Integer
        )
        
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.YOUTUBE,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                view_count_expr >= min_views
            )
            .order_by(desc(view_count_expr))
            .limit(limit)
        )
        
        if channel_id:
            query = query.where(ContentItem.channel_id == channel_id)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_duration(
        self,
        min_seconds: Optional[int] = None,
        max_seconds: Optional[int] = None,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get videos filtered by duration.
        
        Example:
        - Short videos: max_seconds=300 (5 minutes)
        - Long videos: min_seconds=600 (10 minutes)
        """
        duration_expr = cast(
            ContentItem.content_metadata['duration_seconds'],
            Integer
        )
        
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.YOUTUBE,
                ContentItem.processing_status == ProcessingStatus.PROCESSED
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        if min_seconds:
            query = query.where(duration_expr >= min_seconds)
        if max_seconds:
            query = query.where(duration_expr <= max_seconds)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_transcript_language(
        self,
        language: str = "en",
        limit: int = 50
    ) -> List[ContentItem]:
        """Get videos with transcripts in a specific language."""
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.YOUTUBE,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.content_metadata['transcript_language'].astext == language
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_high_quality_transcripts(
        self,
        min_quality: float = 0.8,
        limit: int = 50
    ) -> List[ContentItem]:
        """Get videos with high-quality transcripts."""
        quality_expr = cast(
            ContentItem.content_metadata['transcript_quality'],
            Integer  # PostgreSQL will handle float comparison
        )
        
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.YOUTUBE,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.content_metadata['transcript_quality'].isnot(None)
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        # Filter in Python since JSONB float comparison is tricky
        items = list(result.scalars().all())
        return [
            item for item in items
            if item.content_metadata.get('transcript_quality', 0) >= min_quality
        ]
    
    # ========================================
    # Metadata Queries (Reddit-specific)
    # ========================================
    
    async def get_popular_reddit_posts(
        self,
        user_id: Optional[int] = None,
        min_score: int = 100,
        days: int = 7,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get popular Reddit posts based on score threshold.
        
        Uses JSONB metadata query: content_metadata->>'score'
        
        Args:
            user_id: Filter by user's subscriptions (optional)
            min_score: Minimum post score
            days: Look back this many days
            limit: Maximum results
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Cast score to integer for comparison
        score_expr = cast(
            ContentItem.content_metadata['score'],
            Integer
        )
        
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.REDDIT,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                score_expr >= min_score
            )
            .order_by(desc(score_expr))
            .limit(limit)
        )
        
        # Filter by user subscriptions if user_id provided
        if user_id:
            query = query.join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_posts_by_subreddit(
        self,
        user_id: int,
        subreddit_name: str,
        days: int = 30,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get posts from a specific subreddit.
        
        Uses JSONB metadata query: content_metadata->>'subreddit'
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(ContentItem)
            .join(Channel)
            .join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
            .where(
                Channel.source_type == ContentSourceType.REDDIT,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                ContentItem.content_metadata['subreddit'].astext == subreddit_name.lower()
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_posts_with_comments(
        self,
        user_id: Optional[int] = None,
        min_comment_count: int = 50,
        days: int = 7,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get Reddit posts with high comment counts (high engagement).
        
        Uses JSONB metadata query: content_metadata->>'num_comments'
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Cast num_comments to integer for comparison
        comments_expr = cast(
            ContentItem.content_metadata['num_comments'],
            Integer
        )
        
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.REDDIT,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                comments_expr >= min_comment_count
            )
            .order_by(desc(comments_expr))
            .limit(limit)
        )
        
        if user_id:
            query = query.join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_controversial_posts(
        self,
        user_id: Optional[int] = None,
        max_upvote_ratio: float = 0.6,
        min_score: int = 20,
        days: int = 7,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get controversial Reddit posts (low upvote ratio indicates debate/controversy).
        
        Low upvote ratio with decent score = controversial discussion.
        
        Args:
            max_upvote_ratio: Posts with ratio below this (e.g., 0.6 = 60% upvoted)
            min_score: Must have minimum engagement
            days: Look back period
            limit: Maximum results
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        score_expr = cast(
            ContentItem.content_metadata['score'],
            Integer
        )
        
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.REDDIT,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                score_expr >= min_score
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit * 2)  # Get more, will filter in Python
        )
        
        if user_id:
            query = query.join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
        
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        
        # Filter by upvote_ratio in Python (JSONB float comparison is tricky)
        controversial = [
            item for item in items
            if item.content_metadata.get('upvote_ratio', 1.0) <= max_upvote_ratio
        ]
        
        return controversial[:limit]
    
    async def get_post_by_reddit_id(
        self,
        post_id: str
    ) -> Optional[ContentItem]:
        """
        Get a Reddit post by its Reddit post ID.
        
        Uses JSONB metadata query: content_metadata->>'post_id'
        """
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.REDDIT,
                ContentItem.content_metadata['post_id'].astext == post_id
            )
        )
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_self_posts_only(
        self,
        user_id: Optional[int] = None,
        days: int = 7,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get Reddit self posts (text posts, not links).
        
        Uses JSONB metadata query: content_metadata->>'is_self'
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.REDDIT,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                ContentItem.content_metadata['is_self'].astext.cast(Integer) == 1
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        if user_id:
            query = query.join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_posts_by_engagement_score(
        self,
        user_id: Optional[int] = None,
        min_engagement_score: float = 50.0,
        days: int = 7,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get Reddit posts by calculated engagement score.
        
        Engagement score stored in metadata: (upvotes * 0.6) + (comments * 0.3) + (awards * 0.1)
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(ContentItem)
            .join(Channel)
            .where(
                Channel.source_type == ContentSourceType.REDDIT,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                ContentItem.content_metadata['engagement_score'].isnot(None)
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit * 2)
        )
        
        if user_id:
            query = query.join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
        
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        
        # Filter by engagement score in Python
        high_engagement = [
            item for item in items
            if item.content_metadata.get('engagement_score', 0) >= min_engagement_score
        ]
        
        # Sort by engagement score descending
        high_engagement.sort(
            key=lambda x: x.content_metadata.get('engagement_score', 0),
            reverse=True
        )
        
        return high_engagement[:limit]
    
    # ========================================
    # Metadata Queries (Blog-specific)
    # ========================================
    
    async def get_articles_by_author(
        self,
        user_id: int,
        author: str,
        days: int = 90,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get blog articles by specific author.
        
        Uses JSONB metadata query: content_metadata->>'author'
        
        Args:
            user_id: Filter by user's subscriptions
            author: Author name to search for
            days: Look back period
            limit: Maximum results
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(ContentItem)
            .join(Channel)
            .join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
            .where(
                Channel.source_type == ContentSourceType.BLOG,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                ContentItem.content_metadata['author'].astext.ilike(f"%{author}%")
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_articles_by_blog(
        self,
        user_id: int,
        blog_name: str,
        days: int = 90,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get articles from a specific blog.
        
        Uses JSONB metadata query: content_metadata->>'blog_name'
        
        Args:
            user_id: Filter by user's subscriptions
            blog_name: Blog name to filter by
            days: Look back period
            limit: Maximum results
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(ContentItem)
            .join(Channel)
            .join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
            .where(
                Channel.source_type == ContentSourceType.BLOG,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                ContentItem.content_metadata['blog_name'].astext.ilike(f"%{blog_name}%")
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_articles_by_date_range(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        limit: int = 100
    ) -> List[ContentItem]:
        """
        Get blog articles within a specific date range.
        
        Args:
            user_id: Filter by user's subscriptions
            start_date: Range start (inclusive)
            end_date: Range end (inclusive)
            limit: Maximum results
        """
        from app.models.content import UserSubscription
        
        query = (
            select(ContentItem)
            .join(Channel)
            .join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
            .where(
                Channel.source_type == ContentSourceType.BLOG,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= start_date,
                ContentItem.published_at <= end_date
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_articles_by_word_count(
        self,
        user_id: int,
        min_words: Optional[int] = None,
        max_words: Optional[int] = None,
        days: int = 90,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get blog articles filtered by word count.
        
        Uses JSONB metadata query: content_metadata->>'word_count'
        
        Example:
        - Short articles: max_words=500
        - Long articles: min_words=2000
        - Medium articles: min_words=500, max_words=2000
        
        Args:
            user_id: Filter by user's subscriptions
            min_words: Minimum word count (optional)
            max_words: Maximum word count (optional)
            days: Look back period
            limit: Maximum results
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        word_count_expr = cast(
            ContentItem.content_metadata['word_count'],
            Integer
        )
        
        query = (
            select(ContentItem)
            .join(Channel)
            .join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
            .where(
                Channel.source_type == ContentSourceType.BLOG,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                ContentItem.content_metadata['word_count'].isnot(None)
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        if min_words:
            query = query.where(word_count_expr >= min_words)
        if max_words:
            query = query.where(word_count_expr <= max_words)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_recent_blog_articles(
        self,
        user_id: int,
        days: int = 7,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get recent blog articles from user's subscriptions.
        
        Args:
            user_id: Filter by user's subscriptions
            days: Look back this many days
            limit: Maximum results
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(ContentItem)
            .join(Channel)
            .join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
            .where(
                Channel.source_type == ContentSourceType.BLOG,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def search_articles_by_tags(
        self,
        user_id: int,
        tags: List[str],
        days: int = 90,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get blog articles that have any of the specified tags.
        
        Uses JSONB metadata query: content_metadata->'tags'
        
        Args:
            user_id: Filter by user's subscriptions
            tags: List of tags to search for
            days: Look back period
            limit: Maximum results
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(ContentItem)
            .join(Channel)
            .join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
            .where(
                Channel.source_type == ContentSourceType.BLOG,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                ContentItem.content_metadata['tags'].isnot(None)
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit * 2)  # Get more, will filter in Python
        )
        
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        
        # Filter by tags in Python (easier than complex JSONB array queries)
        # Convert search tags to lowercase for case-insensitive matching
        search_tags_lower = [tag.lower() for tag in tags]
        
        matching_items = []
        for item in items:
            article_tags = item.content_metadata.get('tags', [])
            if not isinstance(article_tags, list):
                continue
            
            # Check if any article tag matches any search tag
            article_tags_lower = [t.lower() for t in article_tags if isinstance(t, str)]
            if any(tag in search_tags_lower for tag in article_tags_lower):
                matching_items.append(item)
                if len(matching_items) >= limit:
                    break
        
        return matching_items
    
    async def get_articles_by_language(
        self,
        user_id: int,
        language: str = "en",
        days: int = 90,
        limit: int = 50
    ) -> List[ContentItem]:
        """
        Get blog articles in a specific language.
        
        Uses JSONB metadata query: content_metadata->>'language'
        
        Args:
            user_id: Filter by user's subscriptions
            language: Language code (e.g., 'en', 'es', 'fr')
            days: Look back period
            limit: Maximum results
        """
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = (
            select(ContentItem)
            .join(Channel)
            .join(
                UserSubscription,
                and_(
                    Channel.id == UserSubscription.channel_id,
                    UserSubscription.user_id == user_id
                )
            )
            .where(
                Channel.source_type == ContentSourceType.BLOG,
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                ContentItem.published_at >= cutoff_date,
                ContentItem.content_metadata['language'].astext == language
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    # ========================================
    # Statistics
    # ========================================
    
    async def get_channel_stats(self, channel_id: int) -> Dict[str, Any]:
        """Get statistics for a specific channel."""
        # Total videos
        total_result = await self.db.execute(
            select(func.count(ContentItem.id))
            .where(ContentItem.channel_id == channel_id)
        )
        total_videos = total_result.scalar_one()
        
        # Processed videos
        processed_result = await self.db.execute(
            select(func.count(ContentItem.id))
            .where(
                ContentItem.channel_id == channel_id,
                ContentItem.processing_status == ProcessingStatus.PROCESSED
            )
        )
        processed_videos = processed_result.scalar_one()
        
        # Failed videos
        failed_result = await self.db.execute(
            select(func.count(ContentItem.id))
            .where(
                ContentItem.channel_id == channel_id,
                ContentItem.processing_status == ProcessingStatus.FAILED
            )
        )
        failed_videos = failed_result.scalar_one()
        
        # Latest video
        latest_result = await self.db.execute(
            select(ContentItem)
            .where(
                ContentItem.channel_id == channel_id,
                ContentItem.processing_status == ProcessingStatus.PROCESSED
            )
            .order_by(ContentItem.published_at.desc())
            .limit(1)
        )
        latest_video = latest_result.scalar_one_or_none()
        
        return {
            'total_videos': total_videos,
            'processed_videos': processed_videos,
            'failed_videos': failed_videos,
            'pending_videos': total_videos - processed_videos - failed_videos,
            'latest_video_date': latest_video.published_at if latest_video else None,
            'latest_video_title': latest_video.title if latest_video else None
        }
    
    async def get_user_content_stats(
        self,
        user_id: int,
        days: int = 7
    ) -> Dict[str, Any]:
        """Get content statistics for a user's subscriptions."""
        from app.models.content import UserSubscription
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Get user's subscribed channels
        subscriptions_result = await self.db.execute(
            select(UserSubscription.channel_id)
            .where(
                UserSubscription.user_id == user_id,
                UserSubscription.is_active == True
            )
        )
        channel_ids = [row[0] for row in subscriptions_result.all()]
        
        if not channel_ids:
            return {
                'total_content': 0,
                'recent_content': 0,
                'by_source_type': {},
                'by_status': {}
            }
        
        # Total content from subscribed channels
        total_result = await self.db.execute(
            select(func.count(ContentItem.id))
            .where(ContentItem.channel_id.in_(channel_ids))
        )
        total_content = total_result.scalar_one()
        
        # Recent content
        recent_result = await self.db.execute(
            select(func.count(ContentItem.id))
            .where(
                ContentItem.channel_id.in_(channel_ids),
                ContentItem.published_at >= cutoff_date
            )
        )
        recent_content = recent_result.scalar_one()
        
        # By source type
        by_source_result = await self.db.execute(
            select(
                Channel.source_type,
                func.count(ContentItem.id)
            )
            .join(Channel)
            .where(ContentItem.channel_id.in_(channel_ids))
            .group_by(Channel.source_type)
        )
        by_source_type = {
            row[0].value: row[1] for row in by_source_result.all()
        }
        
        # By processing status
        by_status_result = await self.db.execute(
            select(
                ContentItem.processing_status,
                func.count(ContentItem.id)
            )
            .where(ContentItem.channel_id.in_(channel_ids))
            .group_by(ContentItem.processing_status)
        )
        by_status = {
            row[0].value: row[1] for row in by_status_result.all()
        }
        
        return {
            'total_content': total_content,
            'recent_content': recent_content,
            'by_source_type': by_source_type,
            'by_status': by_status,
            'days_range': days
        }
    
    # ========================================
    # Search
    # ========================================
    
    async def search_content(
        self,
        query: str,
        channel_id: Optional[int] = None,
        limit: int = 20
    ) -> List[ContentItem]:
        """
        Search content by title or body text.
        
        Uses PostgreSQL full-text search for better performance.
        For now, uses simple ILIKE for compatibility.
        """
        search_pattern = f"%{query}%"
        
        sql_query = (
            select(ContentItem)
            .where(
                ContentItem.processing_status == ProcessingStatus.PROCESSED,
                or_(
                    ContentItem.title.ilike(search_pattern),
                    ContentItem.content_body.ilike(search_pattern)
                )
            )
            .order_by(ContentItem.published_at.desc())
            .limit(limit)
        )
        
        if channel_id:
            sql_query = sql_query.where(ContentItem.channel_id == channel_id)
        
        result = await self.db.execute(sql_query)
        return list(result.scalars().all())


# ========================================
# Dependency Injection
# ========================================

def get_content_query_service(db: AsyncSession) -> ContentQueryService:
    """Dependency for injecting ContentQueryService."""
    return ContentQueryService(db)

