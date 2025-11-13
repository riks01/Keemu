"""
YouTube Data API service for fetching channel and video information.

This module provides a comprehensive wrapper around the YouTube Data API v3,
handling channel discovery, video fetching, and metadata extraction.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import isodate

from app.core.config import settings

logger = logging.getLogger(__name__)


class YouTubeAPIError(Exception):
    """Base exception for YouTube API errors."""
    pass


class YouTubeQuotaExceededError(YouTubeAPIError):
    """Raised when YouTube API quota is exceeded."""
    pass


class YouTubeChannelNotFoundError(YouTubeAPIError):
    """Raised when a YouTube channel is not found."""
    pass


class YouTubeVideoNotFoundError(YouTubeAPIError):
    """Raised when a YouTube video is not found."""
    pass


class YouTubeService:
    """
    Service for interacting with YouTube Data API v3.
    
    Provides methods for:
    - Channel discovery and metadata fetching
    - Video listing and details
    - URL parsing and validation
    - Quota-efficient batch operations
    
    Example:
        >>> youtube = YouTubeService()
        >>> channel = await youtube.get_channel_by_id("UCsBjURrPoezykLs9EqgamOA")
        >>> videos = await youtube.get_channel_videos(channel['id'], max_results=10)
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize YouTube service with API key.
        
        Args:
            api_key: YouTube Data API key. If None, uses settings.YOUTUBE_API_KEY
            
        Raises:
            ValueError: If no API key is provided or found in settings
        """
        self.api_key = api_key or settings.YOUTUBE_API_KEY
        
        if not self.api_key:
            raise ValueError(
                "YouTube API key is required. Set YOUTUBE_API_KEY in environment variables."
            )
        
        self._youtube = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize YouTube API client."""
        try:
            self._youtube = build(
                'youtube',
                'v3',
                developerKey=self.api_key,
                cache_discovery=False  # Avoid caching issues in production
            )
            logger.info("YouTube API client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize YouTube API client: {e}")
            raise YouTubeAPIError(f"Failed to initialize YouTube API: {e}")
    
    # ========================================
    # Channel Operations
    # ========================================
    
    async def get_channel_by_id(self, channel_id: str) -> Dict:
        """
        Get channel information by channel ID.
        
        Args:
            channel_id: YouTube channel ID (e.g., "UCsBjURrPoezykLs9EqgamOA")
            
        Returns:
            Dictionary containing channel information:
            {
                'id': str,
                'title': str,
                'description': str,
                'thumbnail_url': str,
                'subscriber_count': int,
                'video_count': int,
                'view_count': int,
                'custom_url': str (optional),
                'published_at': str (ISO format)
            }
            
        Raises:
            YouTubeChannelNotFoundError: If channel doesn't exist
            YouTubeQuotaExceededError: If API quota exceeded
            YouTubeAPIError: For other API errors
        """
        try:
            response = self._youtube.channels().list(
                part='snippet,statistics,contentDetails',
                id=channel_id
            ).execute()
            
            if not response.get('items'):
                raise YouTubeChannelNotFoundError(f"Channel not found: {channel_id}")
            
            return self._parse_channel_data(response['items'][0])
        
        except HttpError as e:
            if e.resp.status == 403:
                raise YouTubeQuotaExceededError("YouTube API quota exceeded")
            elif e.resp.status == 404:
                raise YouTubeChannelNotFoundError(f"Channel not found: {channel_id}")
            else:
                logger.error(f"YouTube API error: {e}")
                raise YouTubeAPIError(f"YouTube API error: {e}")
    
    async def get_channel_by_username(self, username: str) -> Dict:
        """
        Get channel information by username.
        
        Args:
            username: YouTube username (e.g., "Fireship")
            
        Returns:
            Dictionary containing channel information (same as get_channel_by_id)
            
        Raises:
            YouTubeChannelNotFoundError: If channel doesn't exist
        """
        try:
            response = self._youtube.channels().list(
                part='snippet,statistics,contentDetails',
                forUsername=username
            ).execute()
            
            if not response.get('items'):
                raise YouTubeChannelNotFoundError(f"Channel not found: {username}")
            
            return self._parse_channel_data(response['items'][0])
        
        except HttpError as e:
            if e.resp.status == 403:
                raise YouTubeQuotaExceededError("YouTube API quota exceeded")
            else:
                logger.error(f"YouTube API error: {e}")
                raise YouTubeAPIError(f"YouTube API error: {e}")
    
    async def get_channel_by_custom_url(self, custom_url: str) -> Dict:
        """
        Get channel information by custom URL handle.
        
        Args:
            custom_url: Custom URL handle (e.g., "@Fireship" or "Fireship")
            
        Returns:
            Dictionary containing channel information
            
        Raises:
            YouTubeChannelNotFoundError: If channel doesn't exist
        """
        # Remove @ if present
        handle = custom_url.lstrip('@')
        
        try:
            # Search for channel by handle
            response = self._youtube.search().list(
                part='snippet',
                q=handle,
                type='channel',
                maxResults=1
            ).execute()
            
            if not response.get('items'):
                raise YouTubeChannelNotFoundError(f"Channel not found: {custom_url}")
            
            # Get full channel details
            channel_id = response['items'][0]['snippet']['channelId']
            return await self.get_channel_by_id(channel_id)
        
        except HttpError as e:
            if e.resp.status == 403:
                raise YouTubeQuotaExceededError("YouTube API quota exceeded")
            else:
                logger.error(f"YouTube API error: {e}")
                raise YouTubeAPIError(f"YouTube API error: {e}")
    
    async def get_channel_by_url(self, url: str) -> Dict:
        """
        Get channel information from any YouTube channel URL format.
        
        Supports:
        - https://www.youtube.com/channel/UCsBjURrPoezykLs9EqgamOA
        - https://www.youtube.com/c/Fireship
        - https://www.youtube.com/@Fireship
        - https://www.youtube.com/user/FireshipIO
        
        Args:
            url: YouTube channel URL
            
        Returns:
            Dictionary containing channel information
            
        Raises:
            ValueError: If URL is invalid
            YouTubeChannelNotFoundError: If channel doesn't exist
        """
        channel_id = self.extract_channel_id_from_url(url)
        
        if channel_id:
            # Direct channel ID URL
            return await self.get_channel_by_id(channel_id)
        
        # Try to extract username or handle
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        
        if len(path_parts) >= 1:
            # Handle @username format in path
            if path_parts[0].startswith('@'):
                return await self.get_channel_by_custom_url(path_parts[0])
            
            # Handle /c/name or /user/name format
            if len(path_parts) >= 2:
                identifier_type = path_parts[0]
                identifier = path_parts[1]
                
                if identifier_type == 'c' or identifier_type == 'user':
                    return await self.get_channel_by_username(identifier)
                elif identifier.startswith('@'):
                    return await self.get_channel_by_custom_url(identifier)
        
        raise ValueError(f"Invalid YouTube channel URL: {url}")
    
    # ========================================
    # Video Operations
    # ========================================
    
    async def get_channel_videos(
        self,
        channel_id: str,
        max_results: int = 50,
        published_after: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Get latest videos from a channel.
        
        Args:
            channel_id: YouTube channel ID
            max_results: Maximum number of videos to fetch (default: 50, max: 50)
            published_after: Only fetch videos published after this date
            
        Returns:
            List of video dictionaries containing:
            {
                'video_id': str,
                'title': str,
                'description': str,
                'published_at': str (ISO format),
                'thumbnail_url': str
            }
            
        Raises:
            YouTubeAPIError: For API errors
        """
        try:
            # Get channel's uploads playlist ID
            channel_response = self._youtube.channels().list(
                part='contentDetails',
                id=channel_id
            ).execute()
            
            if not channel_response.get('items'):
                raise YouTubeChannelNotFoundError(f"Channel not found: {channel_id}")
            
            uploads_playlist_id = (
                channel_response['items'][0]['contentDetails']
                ['relatedPlaylists']['uploads']
            )
            
            # Fetch videos from uploads playlist
            playlist_request = self._youtube.playlistItems().list(
                part='snippet,contentDetails',
                playlistId=uploads_playlist_id,
                maxResults=min(max_results, 50)  # API limit is 50
            )
            
            videos = []
            
            while playlist_request and len(videos) < max_results:
                playlist_response = playlist_request.execute()
                
                for item in playlist_response.get('items', []):
                    video_data = self._parse_playlist_item(item)
                    
                    # Filter by date if specified
                    if published_after:
                        published_dt = datetime.fromisoformat(
                            video_data['published_at'].replace('Z', '+00:00')
                        )
                        if published_dt < published_after:
                            continue
                    
                    videos.append(video_data)
                    
                    if len(videos) >= max_results:
                        break
                
                # Get next page
                playlist_request = self._youtube.playlistItems().list_next(
                    playlist_request, playlist_response
                )
            
            logger.info(f"Fetched {len(videos)} videos from channel {channel_id}")
            return videos
        
        except HttpError as e:
            if e.resp.status == 403:
                raise YouTubeQuotaExceededError("YouTube API quota exceeded")
            else:
                logger.error(f"YouTube API error: {e}")
                raise YouTubeAPIError(f"YouTube API error: {e}")
    
    async def get_video_details(self, video_id: str) -> Dict:
        """
        Get detailed information about a specific video.
        
        Args:
            video_id: YouTube video ID
            
        Returns:
            Dictionary containing detailed video information:
            {
                'video_id': str,
                'title': str,
                'description': str,
                'channel_id': str,
                'channel_title': str,
                'published_at': str,
                'duration_seconds': int,
                'duration_formatted': str,
                'view_count': int,
                'like_count': int,
                'comment_count': int,
                'thumbnail_url': str,
                'tags': List[str],
                'category_id': str,
                'definition': str (e.g., 'hd', 'sd'),
                'has_captions': bool
            }
            
        Raises:
            YouTubeVideoNotFoundError: If video doesn't exist
        """
        try:
            response = self._youtube.videos().list(
                part='snippet,contentDetails,statistics',
                id=video_id
            ).execute()
            
            if not response.get('items'):
                raise YouTubeVideoNotFoundError(f"Video not found: {video_id}")
            
            return self._parse_video_details(response['items'][0])
        
        except HttpError as e:
            if e.resp.status == 403:
                raise YouTubeQuotaExceededError("YouTube API quota exceeded")
            elif e.resp.status == 404:
                raise YouTubeVideoNotFoundError(f"Video not found: {video_id}")
            else:
                logger.error(f"YouTube API error: {e}")
                raise YouTubeAPIError(f"YouTube API error: {e}")
    
    async def get_videos_details_batch(self, video_ids: List[str]) -> List[Dict]:
        """
        Get details for multiple videos in a single API call (more quota-efficient).
        
        Args:
            video_ids: List of video IDs (max 50 per request)
            
        Returns:
            List of video detail dictionaries
        """
        if not video_ids:
            return []
        
        # API allows max 50 IDs per request
        batch_size = 50
        all_videos = []
        
        for i in range(0, len(video_ids), batch_size):
            batch = video_ids[i:i + batch_size]
            
            try:
                response = self._youtube.videos().list(
                    part='snippet,contentDetails,statistics',
                    id=','.join(batch)
                ).execute()
                
                for item in response.get('items', []):
                    all_videos.append(self._parse_video_details(item))
            
            except HttpError as e:
                logger.error(f"Error fetching batch of videos: {e}")
                continue
        
        return all_videos
    
    # ========================================
    # Utility Functions
    # ========================================
    
    @staticmethod
    def extract_channel_id_from_url(url: str) -> Optional[str]:
        """
        Extract channel ID from YouTube URL.
        
        Args:
            url: YouTube URL
            
        Returns:
            Channel ID if found, None otherwise
            
        Example:
            >>> extract_channel_id_from_url("https://youtube.com/channel/UCsBjURrPoezykLs9EqgamOA")
            "UCsBjURrPoezykLs9EqgamOA"
        """
        # Pattern: /channel/{CHANNEL_ID}
        pattern = r'youtube\.com/channel/([a-zA-Z0-9_-]+)'
        match = re.search(pattern, url)
        return match.group(1) if match else None
    
    @staticmethod
    def extract_video_id_from_url(url: str) -> Optional[str]:
        """
        Extract video ID from YouTube URL.
        
        Supports multiple URL formats:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://www.youtube.com/embed/VIDEO_ID
        
        Args:
            url: YouTube URL
            
        Returns:
            Video ID if found, None otherwise
        """
        # Standard watch URL
        parsed = urlparse(url)
        if 'youtube.com' in parsed.netloc:
            query_params = parse_qs(parsed.query)
            if 'v' in query_params:
                return query_params['v'][0]
            
            # Embed URL: /embed/VIDEO_ID
            if '/embed/' in parsed.path:
                return parsed.path.split('/embed/')[1].split('?')[0]
        
        # Short URL: youtu.be/VIDEO_ID
        if 'youtu.be' in parsed.netloc:
            return parsed.path.lstrip('/')
        
        return None
    
    @staticmethod
    def format_duration(iso_duration: str) -> Tuple[int, str]:
        """
        Convert ISO 8601 duration to seconds and human-readable format.
        
        Args:
            iso_duration: ISO 8601 duration string (e.g., "PT15M33S")
            
        Returns:
            Tuple of (total_seconds, formatted_string)
            
        Example:
            >>> format_duration("PT15M33S")
            (933, "15:33")
            >>> format_duration("PT1H2M30S")
            (3750, "1:02:30")
        """
        try:
            duration = isodate.parse_duration(iso_duration)
            total_seconds = int(duration.total_seconds())
            
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            
            if hours > 0:
                formatted = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                formatted = f"{minutes}:{seconds:02d}"
            
            return total_seconds, formatted
        
        except Exception as e:
            logger.warning(f"Failed to parse duration {iso_duration}: {e}")
            return 0, "0:00"
    
    @staticmethod
    def validate_channel_id(channel_id: str) -> bool:
        """
        Validate YouTube channel ID format.
        
        Channel IDs typically:
        - Start with "UC"
        - Are 24 characters long
        - Contain alphanumeric characters, hyphens, and underscores
        
        Args:
            channel_id: Channel ID to validate
            
        Returns:
            True if valid format, False otherwise
        """
        if not channel_id:
            return False
        
        # Basic validation: starts with UC and has reasonable length
        return channel_id.startswith('UC') and 20 <= len(channel_id) <= 30
    
    @staticmethod
    def validate_video_id(video_id: str) -> bool:
        """
        Validate YouTube video ID format.
        
        Video IDs are typically 11 characters long containing
        alphanumeric characters, hyphens, and underscores.
        
        Args:
            video_id: Video ID to validate
            
        Returns:
            True if valid format, False otherwise
        """
        if not video_id or len(video_id) != 11:
            return False
        
        # Valid characters in video ID
        return bool(re.match(r'^[a-zA-Z0-9_-]{11}$', video_id))
    
    # ========================================
    # Helper Methods
    # ========================================
    
    def _parse_channel_data(self, item: Dict) -> Dict:
        """Parse raw channel data from API response."""
        snippet = item['snippet']
        statistics = item.get('statistics', {})
        
        # Get best thumbnail
        thumbnails = snippet.get('thumbnails', {})
        thumbnail_url = (
            thumbnails.get('high', {}).get('url') or
            thumbnails.get('medium', {}).get('url') or
            thumbnails.get('default', {}).get('url')
        )
        
        return {
            'id': item['id'],
            'title': snippet.get('title', ''),
            'description': snippet.get('description', ''),
            'thumbnail_url': thumbnail_url,
            'subscriber_count': int(statistics.get('subscriberCount', 0)),
            'video_count': int(statistics.get('videoCount', 0)),
            'view_count': int(statistics.get('viewCount', 0)),
            'custom_url': snippet.get('customUrl'),
            'published_at': snippet.get('publishedAt')
        }
    
    def _parse_playlist_item(self, item: Dict) -> Dict:
        """Parse video data from playlist item."""
        snippet = item['snippet']
        
        # Get best thumbnail
        thumbnails = snippet.get('thumbnails', {})
        thumbnail_url = (
            thumbnails.get('high', {}).get('url') or
            thumbnails.get('medium', {}).get('url') or
            thumbnails.get('default', {}).get('url')
        )
        
        return {
            'video_id': item['contentDetails']['videoId'],
            'title': snippet.get('title', ''),
            'description': snippet.get('description', ''),
            'published_at': snippet.get('publishedAt'),
            'thumbnail_url': thumbnail_url
        }
    
    def _parse_video_details(self, item: Dict) -> Dict:
        """Parse detailed video data from API response."""
        snippet = item['snippet']
        content_details = item.get('contentDetails', {})
        statistics = item.get('statistics', {})
        
        # Get best thumbnail
        thumbnails = snippet.get('thumbnails', {})
        thumbnail_url = (
            thumbnails.get('maxres', {}).get('url') or
            thumbnails.get('high', {}).get('url') or
            thumbnails.get('medium', {}).get('url') or
            thumbnails.get('default', {}).get('url')
        )
        
        # Parse duration
        duration_seconds, duration_formatted = self.format_duration(
            content_details.get('duration', 'PT0S')
        )
        
        return {
            'video_id': item['id'],
            'title': snippet.get('title', ''),
            'description': snippet.get('description', ''),
            'channel_id': snippet.get('channelId'),
            'channel_title': snippet.get('channelTitle', ''),
            'published_at': snippet.get('publishedAt'),
            'duration_seconds': duration_seconds,
            'duration_formatted': duration_formatted,
            'view_count': int(statistics.get('viewCount', 0)),
            'like_count': int(statistics.get('likeCount', 0)),
            'comment_count': int(statistics.get('commentCount', 0)),
            'thumbnail_url': thumbnail_url,
            'tags': snippet.get('tags', []),
            'category_id': snippet.get('categoryId'),
            'definition': content_details.get('definition', 'sd'),
            'has_captions': content_details.get('caption') == 'true'
        }


# ========================================
# Helper Functions
# ========================================

def get_youtube_service() -> YouTubeService:
    """
    Get or create YouTube service instance.
    
    Returns:
        YouTubeService instance
        
    Raises:
        ValueError: If YouTube API key is not configured
    """
    return YouTubeService()

