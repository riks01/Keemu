"""
Reddit API service for fetching subreddit and post information.

This module provides a comprehensive wrapper around the PRAW (Python Reddit API Wrapper),
handling subreddit discovery, post fetching, and comment extraction.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import praw
from praw.exceptions import RedditAPIException
from prawcore.exceptions import NotFound, Forbidden
from praw.models import Submission, Subreddit, Comment

from app.core.config import settings

logger = logging.getLogger(__name__)


# ========================================
# Custom Exceptions
# ========================================


class RedditAPIError(Exception):
    """Base exception for Reddit API errors."""
    pass


class RedditQuotaExceededError(RedditAPIError):
    """Raised when Reddit API quota is exceeded."""
    pass


class SubredditNotFoundError(RedditAPIError):
    """Raised when a subreddit is not found."""
    pass


class RedditContentNotFoundError(RedditAPIError):
    """Raised when Reddit content (post/comment) is not found."""
    pass


# ========================================
# Reddit Service
# ========================================


class RedditService:
    """
    Service for interacting with Reddit API via PRAW.
    
    Provides methods for:
    - Subreddit discovery and metadata fetching
    - Post listing with various filters
    - Comment extraction and threading
    - Engagement scoring
    
    Example:
        >>> reddit = RedditService()
        >>> subreddit = reddit.get_subreddit_by_name("python")
        >>> posts = reddit.get_subreddit_posts("python", limit=10, time_filter="day")
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """
        Initialize Reddit service with credentials.
        
        Args:
            client_id: Reddit application client ID. If None, uses settings.REDDIT_CLIENT_ID
            client_secret: Reddit application client secret. If None, uses settings.REDDIT_CLIENT_SECRET
            user_agent: User agent string. If None, uses settings.REDDIT_USER_AGENT
            
        Raises:
            ValueError: If credentials are missing
        """
        self.client_id = client_id or settings.REDDIT_CLIENT_ID
        self.client_secret = client_secret or settings.REDDIT_CLIENT_SECRET
        self.user_agent = user_agent or settings.REDDIT_USER_AGENT
        
        if not all([self.client_id, self.client_secret, self.user_agent]):
            raise ValueError(
                "Reddit credentials are required. Set REDDIT_CLIENT_ID, "
                "REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT in environment variables."
            )
        
        self._reddit = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize PRAW Reddit client."""
        try:
            self._reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
                check_for_async=False,  # We handle async at task level
            )
            # Test connection
            self._reddit.read_only = True
            logger.info("Reddit API client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Reddit API client: {e}")
            raise RedditAPIError(f"Failed to initialize Reddit API: {e}")
    
    # ========================================
    # Subreddit Operations
    # ========================================
    
    def extract_subreddit_name(self, query: str) -> str:
        """
        Extract subreddit name from various input formats.
        
        Handles:
        - r/python
        - /r/python
        - python
        - https://reddit.com/r/python
        - https://www.reddit.com/r/python/
        
        Args:
            query: Subreddit identifier in various formats
            
        Returns:
            Clean subreddit name (e.g., "python")
            
        Raises:
            ValueError: If query format is invalid
        """
        query = query.strip()
        
        # Handle URL
        if query.startswith('http://') or query.startswith('https://'):
            parsed = urlparse(query)
            path = parsed.path
            # Extract from path like /r/python or /r/python/
            match = re.search(r'/r/([^/]+)', path)
            if match:
                return match.group(1)
            raise ValueError(f"Could not extract subreddit name from URL: {query}")
        
        # Handle r/python or /r/python
        if query.startswith('r/'):
            return query[2:]
        if query.startswith('/r/'):
            return query[3:]
        
        # Direct name (already clean)
        # Validate format: alphanumeric and underscores, 3-21 chars
        if re.match(r'^[A-Za-z0-9_]{3,21}$', query):
            return query
        
        raise ValueError(
            f"Invalid subreddit format: {query}. Use format like 'python', 'r/python', "
            "or a Reddit URL."
        )
    
    def validate_subreddit_url(self, url: str) -> Tuple[bool, Optional[str]]:
        """
        Validate if URL is a valid Reddit subreddit URL.
        
        Args:
            url: URL to validate
            
        Returns:
            Tuple of (is_valid, subreddit_name)
        """
        try:
            name = self.extract_subreddit_name(url)
            return (True, name)
        except ValueError:
            return (False, None)
    
    def get_subreddit_by_name(self, subreddit_name: str) -> Dict:
        """
        Get subreddit metadata by name.
        
        Args:
            subreddit_name: Name of the subreddit (without r/)
            
        Returns:
            Dictionary containing subreddit information:
            - name: Subreddit name
            - display_name: Display name
            - title: Subreddit title
            - description: Public description
            - subscribers: Number of subscribers
            - created_utc: Creation timestamp
            - over18: NSFW flag
            - public: Whether subreddit is public
            - icon_img: Icon image URL
            - banner_img: Banner image URL
            
        Raises:
            SubredditNotFoundError: If subreddit doesn't exist
            RedditAPIError: For other API errors
        """
        try:
            subreddit = self._reddit.subreddit(subreddit_name)
            
            # Access display_name to trigger API call and check if exists
            _ = subreddit.display_name
            
            return {
                'name': subreddit.display_name,
                'display_name': subreddit.display_name,
                'title': subreddit.title,
                'description': subreddit.public_description or '',
                'subscribers': subreddit.subscribers or 0,
                'created_utc': datetime.fromtimestamp(subreddit.created_utc, tz=timezone.utc),
                'over18': subreddit.over18,
                'public': not subreddit.subreddit_type == 'private',
                'icon_img': getattr(subreddit, 'icon_img', '') or '',
                'banner_img': getattr(subreddit, 'banner_img', '') or '',
                'url': f"https://reddit.com/r/{subreddit.display_name}",
            }
            
        except NotFound:
            logger.warning(f"Subreddit not found: {subreddit_name}")
            raise SubredditNotFoundError(f"Subreddit not found: r/{subreddit_name}")
        except Forbidden:
            logger.warning(f"Subreddit is private or banned: {subreddit_name}")
            raise SubredditNotFoundError(
                f"Subreddit r/{subreddit_name} is private, banned, or quarantined"
            )
        except RedditAPIException as e:
            logger.error(f"Reddit API error for subreddit {subreddit_name}: {e}")
            raise RedditAPIError(f"Reddit API error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching subreddit {subreddit_name}: {e}")
            raise RedditAPIError(f"Failed to fetch subreddit: {e}")
    
    # ========================================
    # Post Operations
    # ========================================
    
    def get_subreddit_posts(
        self,
        subreddit_name: str,
        limit: int = 100,
        time_filter: str = 'day',
        sort: str = 'hot',
    ) -> List[Dict]:
        """
        Get posts from a subreddit with filters.
        
        Args:
            subreddit_name: Name of the subreddit
            limit: Maximum number of posts to fetch (1-100)
            time_filter: Time filter for 'top' sort ('hour', 'day', 'week', 'month', 'year', 'all')
            sort: Sort method ('hot', 'new', 'top', 'rising')
            
        Returns:
            List of post dictionaries with metadata (not including comments)
            
        Raises:
            SubredditNotFoundError: If subreddit doesn't exist
            RedditAPIError: For other API errors
        """
        try:
            subreddit = self._reddit.subreddit(subreddit_name)
            
            # Get posts based on sort method
            if sort == 'hot':
                submissions = subreddit.hot(limit=limit)
            elif sort == 'new':
                submissions = subreddit.new(limit=limit)
            elif sort == 'top':
                submissions = subreddit.top(time_filter=time_filter, limit=limit)
            elif sort == 'rising':
                submissions = subreddit.rising(limit=limit)
            else:
                raise ValueError(f"Invalid sort method: {sort}")
            
            posts = []
            for submission in submissions:
                post_data = self._submission_to_dict(submission)
                posts.append(post_data)
            
            logger.info(
                f"Fetched {len(posts)} posts from r/{subreddit_name} "
                f"(sort={sort}, limit={limit})"
            )
            return posts
            
        except NotFound:
            logger.warning(f"Subreddit not found: {subreddit_name}")
            raise SubredditNotFoundError(f"Subreddit not found: r/{subreddit_name}")
        except Forbidden:
            logger.warning(f"Subreddit is private or banned: {subreddit_name}")
            raise SubredditNotFoundError(
                f"Subreddit r/{subreddit_name} is private, banned, or quarantined"
            )
        except Exception as e:
            logger.error(f"Error fetching posts from r/{subreddit_name}: {e}")
            raise RedditAPIError(f"Failed to fetch posts: {e}")
    
    def get_post_details(self, post_id: str) -> Dict:
        """
        Get full details for a specific post by ID.
        
        Args:
            post_id: Reddit post ID (e.g., "abc123")
            
        Returns:
            Dictionary with post metadata
            
        Raises:
            RedditContentNotFoundError: If post not found
            RedditAPIError: For other errors
        """
        try:
            submission = self._reddit.submission(id=post_id)
            # Access title to trigger API call
            _ = submission.title
            
            return self._submission_to_dict(submission)
            
        except NotFound:
            logger.warning(f"Post not found: {post_id}")
            raise RedditContentNotFoundError(f"Post not found: {post_id}")
        except Exception as e:
            logger.error(f"Error fetching post {post_id}: {e}")
            raise RedditAPIError(f"Failed to fetch post: {e}")
    
    def get_post_comments(
        self,
        post_id: str,
        comment_limit: int = 20,
        sort: str = 'top',
    ) -> List[Dict]:
        """
        Get top comments for a post.
        
        Args:
            post_id: Reddit post ID
            comment_limit: Maximum number of top-level comments to fetch
            sort: Comment sort method ('top', 'best', 'new', 'controversial')
            
        Returns:
            List of comment dictionaries with metadata
            
        Raises:
            RedditContentNotFoundError: If post not found
            RedditAPIError: For other errors
        """
        try:
            submission = self._reddit.submission(id=post_id)
            submission.comment_sort = sort
            
            # Fetch comments (PRAW lazy loads)
            submission.comments.replace_more(limit=0)  # Don't fetch "load more" comments
            
            comments = []
            for comment in submission.comments[:comment_limit]:
                if isinstance(comment, Comment):
                    comment_data = self._comment_to_dict(comment)
                    comments.append(comment_data)
            
            logger.info(f"Fetched {len(comments)} comments for post {post_id}")
            return comments
            
        except NotFound:
            logger.warning(f"Post not found: {post_id}")
            raise RedditContentNotFoundError(f"Post not found: {post_id}")
        except Exception as e:
            logger.error(f"Error fetching comments for post {post_id}: {e}")
            raise RedditAPIError(f"Failed to fetch comments: {e}")
    
    # ========================================
    # Utility Functions
    # ========================================
    
    def _submission_to_dict(self, submission: Submission) -> Dict:
        """
        Convert PRAW Submission to dictionary.
        
        Args:
            submission: PRAW Submission object
            
        Returns:
            Dictionary with post metadata
        """
        return {
            'post_id': submission.id,
            'title': submission.title,
            'author': str(submission.author) if submission.author else '[deleted]',
            'subreddit': str(submission.subreddit),
            'created_utc': datetime.fromtimestamp(submission.created_utc, tz=timezone.utc),
            'score': submission.score,
            'upvote_ratio': submission.upvote_ratio,
            'num_comments': submission.num_comments,
            'permalink': f"https://reddit.com{submission.permalink}",
            'url': submission.url,
            'is_self': submission.is_self,
            'selftext': submission.selftext if submission.is_self else '',
            'over_18': submission.over_18,
            'spoiler': submission.spoiler,
            'stickied': submission.stickied,
            'locked': submission.locked,
            'post_hint': getattr(submission, 'post_hint', None),
            'link_flair_text': submission.link_flair_text or '',
            'gilded': submission.gilded,
            'total_awards_received': submission.total_awards_received,
        }
    
    def _comment_to_dict(self, comment: Comment) -> Dict:
        """
        Convert PRAW Comment to dictionary.
        
        Args:
            comment: PRAW Comment object
            
        Returns:
            Dictionary with comment metadata
        """
        return {
            'comment_id': comment.id,
            'author': str(comment.author) if comment.author else '[deleted]',
            'body': comment.body,
            'score': comment.score,
            'created_utc': datetime.fromtimestamp(comment.created_utc, tz=timezone.utc),
            'is_submitter': comment.is_submitter,
            'stickied': comment.stickied,
            'gilded': comment.gilded,
            'total_awards_received': getattr(comment, 'total_awards_received', 0),
            'depth': comment.depth if hasattr(comment, 'depth') else 0,
        }
    
    def format_post_content(self, post: Dict) -> str:
        """
        Format post into readable text content.
        
        Handles different post types (self, link, image, video).
        
        Args:
            post: Post dictionary from _submission_to_dict
            
        Returns:
            Formatted text content
        """
        parts = []
        
        # Title
        parts.append(f"Title: {post['title']}")
        parts.append(f"Subreddit: r/{post['subreddit']}")
        parts.append(f"Author: u/{post['author']}")
        parts.append(f"Posted: {post['created_utc'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
        parts.append(f"Score: {post['score']} | Comments: {post['num_comments']}")
        
        if post['link_flair_text']:
            parts.append(f"Flair: {post['link_flair_text']}")
        
        parts.append('')  # Empty line
        
        # Content
        if post['is_self']:
            # Self post with text
            if post['selftext']:
                parts.append(post['selftext'])
            else:
                parts.append('[No text content]')
        else:
            # Link post
            parts.append(f"Link: {post['url']}")
            post_hint = post.get('post_hint', '')
            if post_hint:
                parts.append(f"Type: {post_hint}")
        
        return '\n'.join(parts)
    
    def parse_comment_tree(
        self,
        comments: List[Dict],
        max_depth: int = 2,
    ) -> List[Dict]:
        """
        Flatten comment hierarchy for storage.
        
        Args:
            comments: List of comment dictionaries
            max_depth: Maximum comment depth to include (0 = top-level only)
            
        Returns:
            Filtered list of comments up to max_depth
        """
        # Filter by depth
        filtered = [c for c in comments if c['depth'] <= max_depth]
        
        # Sort by score descending
        filtered.sort(key=lambda x: x['score'], reverse=True)
        
        return filtered
    
    def calculate_engagement_score(self, post: Dict) -> float:
        """
        Calculate engagement score for a post.
        
        Formula: (upvotes * 0.6) + (comments * 0.3) + (awards * 0.1)
        
        Args:
            post: Post dictionary
            
        Returns:
            Engagement score (higher = more engaged)
        """
        score = post.get('score', 0)
        comments = post.get('num_comments', 0)
        awards = post.get('total_awards_received', 0)
        
        engagement = (score * 0.6) + (comments * 0.3) + (awards * 0.1)
        
        return engagement
    
    def format_comments_for_storage(self, comments: List[Dict]) -> str:
        """
        Format comments into structured text for storage.
        
        Args:
            comments: List of comment dictionaries
            
        Returns:
            Formatted comment text
        """
        if not comments:
            return '[No comments]'
        
        parts = []
        for i, comment in enumerate(comments, 1):
            parts.append(f"[Comment {i} - Score: {comment['score']}]")
            parts.append(f"Author: u/{comment['author']}")
            parts.append(comment['body'])
            parts.append('')  # Empty line between comments
        
        return '\n'.join(parts)

