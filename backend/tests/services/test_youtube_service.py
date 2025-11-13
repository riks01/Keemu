"""
Unit tests for YouTube service.

These tests mock the YouTube API to avoid using quota during testing.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from app.services.youtube import (
    YouTubeService,
    YouTubeAPIError,
    YouTubeQuotaExceededError,
    YouTubeChannelNotFoundError,
    YouTubeVideoNotFoundError,
)


class TestYouTubeService:
    """Test suite for YouTubeService class."""
    
    @pytest.fixture
    def mock_youtube_client(self):
        """Mock YouTube API client."""
        with patch('app.services.youtube.build') as mock_build:
            mock_client = MagicMock()
            mock_build.return_value = mock_client
            yield mock_client
    
    @pytest.fixture
    def youtube_service(self, mock_youtube_client):
        """Create YouTubeService instance with mocked client."""
        with patch.dict('os.environ', {'YOUTUBE_API_KEY': 'test_api_key'}):
            service = YouTubeService(api_key='test_api_key')
            service._youtube = mock_youtube_client
            return service
    
    # ========================================
    # Channel Operations Tests
    # ========================================
    
    @pytest.mark.asyncio
    async def test_get_channel_by_id_success(self, youtube_service, mock_youtube_client):
        """Test successful channel fetch by ID."""
        # Mock response
        mock_response = {
            'items': [{
                'id': 'UCsBjURrPoezykLs9EqgamOA',
                'snippet': {
                    'title': 'Fireship',
                    'description': 'High-intensity code tutorials',
                    'customUrl': '@fireship',
                    'publishedAt': '2017-01-01T00:00:00Z',
                    'thumbnails': {
                        'high': {'url': 'https://example.com/thumb.jpg'}
                    }
                },
                'statistics': {
                    'subscriberCount': '1000000',
                    'videoCount': '500',
                    'viewCount': '50000000'
                }
            }]
        }
        
        mock_youtube_client.channels().list().execute.return_value = mock_response
        
        # Execute
        result = await youtube_service.get_channel_by_id('UCsBjURrPoezykLs9EqgamOA')
        
        # Assert
        assert result['id'] == 'UCsBjURrPoezykLs9EqgamOA'
        assert result['title'] == 'Fireship'
        assert result['subscriber_count'] == 1000000
        assert result['video_count'] == 500
        assert result['thumbnail_url'] == 'https://example.com/thumb.jpg'
    
    @pytest.mark.asyncio
    async def test_get_channel_by_id_not_found(self, youtube_service, mock_youtube_client):
        """Test channel not found error."""
        mock_youtube_client.channels().list().execute.return_value = {'items': []}
        
        with pytest.raises(YouTubeChannelNotFoundError):
            await youtube_service.get_channel_by_id('invalid_id')
    
    @pytest.mark.asyncio
    async def test_get_channel_by_username_success(self, youtube_service, mock_youtube_client):
        """Test successful channel fetch by username."""
        mock_response = {
            'items': [{
                'id': 'UCtest123',
                'snippet': {
                    'title': 'Test Channel',
                    'description': 'Test description',
                    'thumbnails': {
                        'default': {'url': 'https://example.com/thumb.jpg'}
                    }
                },
                'statistics': {
                    'subscriberCount': '5000',
                    'videoCount': '100',
                    'viewCount': '1000000'
                }
            }]
        }
        
        mock_youtube_client.channels().list().execute.return_value = mock_response
        
        result = await youtube_service.get_channel_by_username('testuser')
        
        assert result['id'] == 'UCtest123'
        assert result['title'] == 'Test Channel'
    
    # ========================================
    # Video Operations Tests
    # ========================================
    
    @pytest.mark.asyncio
    async def test_get_channel_videos_success(self, youtube_service, mock_youtube_client):
        """Test fetching videos from a channel."""
        # Mock channel response
        channel_response = {
            'items': [{
                'contentDetails': {
                    'relatedPlaylists': {
                        'uploads': 'UUsBjURrPoezykLs9EqgamOA'
                    }
                }
            }]
        }
        
        # Mock playlist response
        playlist_response = {
            'items': [
                {
                    'snippet': {
                        'title': 'Video 1',
                        'description': 'Description 1',
                        'publishedAt': '2024-01-01T00:00:00Z',
                        'thumbnails': {
                            'default': {'url': 'https://example.com/thumb1.jpg'}
                        }
                    },
                    'contentDetails': {
                        'videoId': 'video1'
                    }
                },
                {
                    'snippet': {
                        'title': 'Video 2',
                        'description': 'Description 2',
                        'publishedAt': '2024-01-02T00:00:00Z',
                        'thumbnails': {
                            'default': {'url': 'https://example.com/thumb2.jpg'}
                        }
                    },
                    'contentDetails': {
                        'videoId': 'video2'
                    }
                }
            ]
        }
        
        mock_youtube_client.channels().list().execute.return_value = channel_response
        mock_youtube_client.playlistItems().list().execute.return_value = playlist_response
        mock_youtube_client.playlistItems().list_next.return_value = None
        
        # Execute
        videos = await youtube_service.get_channel_videos('UCsBjURrPoezykLs9EqgamOA', max_results=10)
        
        # Assert
        assert len(videos) == 2
        assert videos[0]['video_id'] == 'video1'
        assert videos[0]['title'] == 'Video 1'
        assert videos[1]['video_id'] == 'video2'
    
    @pytest.mark.asyncio
    async def test_get_video_details_success(self, youtube_service, mock_youtube_client):
        """Test fetching detailed video information."""
        mock_response = {
            'items': [{
                'id': 'dQw4w9WgXcQ',
                'snippet': {
                    'title': 'Never Gonna Give You Up',
                    'description': 'Rick Astley',
                    'channelId': 'UCtest',
                    'channelTitle': 'Rick Astley',
                    'publishedAt': '2009-10-25T00:00:00Z',
                    'thumbnails': {
                        'high': {'url': 'https://example.com/thumb.jpg'}
                    },
                    'tags': ['music', 'official'],
                    'categoryId': '10'
                },
                'contentDetails': {
                    'duration': 'PT3M33S',
                    'definition': 'hd',
                    'caption': 'true'
                },
                'statistics': {
                    'viewCount': '1000000000',
                    'likeCount': '10000000',
                    'commentCount': '500000'
                }
            }]
        }
        
        mock_youtube_client.videos().list().execute.return_value = mock_response
        
        # Execute
        result = await youtube_service.get_video_details('dQw4w9WgXcQ')
        
        # Assert
        assert result['video_id'] == 'dQw4w9WgXcQ'
        assert result['title'] == 'Never Gonna Give You Up'
        assert result['duration_seconds'] == 213  # 3:33
        assert result['duration_formatted'] == '3:33'
        assert result['view_count'] == 1000000000
        assert result['has_captions'] is True
        assert 'music' in result['tags']
    
    @pytest.mark.asyncio
    async def test_get_video_details_not_found(self, youtube_service, mock_youtube_client):
        """Test video not found error."""
        mock_youtube_client.videos().list().execute.return_value = {'items': []}
        
        with pytest.raises(YouTubeVideoNotFoundError):
            await youtube_service.get_video_details('invalid_id')
    
    @pytest.mark.asyncio
    async def test_get_videos_details_batch(self, youtube_service, mock_youtube_client):
        """Test batch fetching of video details."""
        mock_response = {
            'items': [
                {
                    'id': 'video1',
                    'snippet': {
                        'title': 'Video 1',
                        'description': 'Desc 1',
                        'channelId': 'channel1',
                        'channelTitle': 'Channel 1',
                        'publishedAt': '2024-01-01T00:00:00Z',
                        'thumbnails': {'default': {'url': 'url1'}},
                        'tags': [],
                        'categoryId': '1'
                    },
                    'contentDetails': {
                        'duration': 'PT10M0S',
                        'definition': 'hd',
                        'caption': 'false'
                    },
                    'statistics': {
                        'viewCount': '1000',
                        'likeCount': '100',
                        'commentCount': '10'
                    }
                }
            ]
        }
        
        mock_youtube_client.videos().list().execute.return_value = mock_response
        
        # Execute
        results = await youtube_service.get_videos_details_batch(['video1', 'video2'])
        
        # Assert
        assert len(results) == 1
        assert results[0]['video_id'] == 'video1'
    
    # ========================================
    # Utility Function Tests
    # ========================================
    
    def test_extract_channel_id_from_url(self, youtube_service):
        """Test channel ID extraction from various URL formats."""
        url1 = "https://www.youtube.com/channel/UCsBjURrPoezykLs9EqgamOA"
        url2 = "https://youtube.com/channel/UCtest123456"
        url3 = "https://www.youtube.com/c/Fireship"  # Should return None
        
        assert youtube_service.extract_channel_id_from_url(url1) == 'UCsBjURrPoezykLs9EqgamOA'
        assert youtube_service.extract_channel_id_from_url(url2) == 'UCtest123456'
        assert youtube_service.extract_channel_id_from_url(url3) is None
    
    def test_extract_video_id_from_url(self, youtube_service):
        """Test video ID extraction from various URL formats."""
        url1 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        url2 = "https://youtu.be/dQw4w9WgXcQ"
        url3 = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        url4 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s"
        
        assert youtube_service.extract_video_id_from_url(url1) == 'dQw4w9WgXcQ'
        assert youtube_service.extract_video_id_from_url(url2) == 'dQw4w9WgXcQ'
        assert youtube_service.extract_video_id_from_url(url3) == 'dQw4w9WgXcQ'
        assert youtube_service.extract_video_id_from_url(url4) == 'dQw4w9WgXcQ'
    
    def test_format_duration(self, youtube_service):
        """Test ISO 8601 duration formatting."""
        # Test various duration formats
        seconds1, formatted1 = youtube_service.format_duration('PT3M33S')
        assert seconds1 == 213
        assert formatted1 == '3:33'
        
        seconds2, formatted2 = youtube_service.format_duration('PT1H2M30S')
        assert seconds2 == 3750
        assert formatted2 == '1:02:30'
        
        seconds3, formatted3 = youtube_service.format_duration('PT45S')
        assert seconds3 == 45
        assert formatted3 == '0:45'
        
        seconds4, formatted4 = youtube_service.format_duration('PT1H0M0S')
        assert seconds4 == 3600
        assert formatted4 == '1:00:00'
    
    def test_validate_channel_id(self, youtube_service):
        """Test channel ID validation."""
        assert youtube_service.validate_channel_id('UCsBjURrPoezykLs9EqgamOA') is True
        assert youtube_service.validate_channel_id('UCtest123456789012345') is True  # Valid length (22 chars)
        assert youtube_service.validate_channel_id('invalid') is False
        assert youtube_service.validate_channel_id('') is False
        assert youtube_service.validate_channel_id('AB123') is False  # Doesn't start with UC
        assert youtube_service.validate_channel_id('UCtest') is False  # Too short
    
    def test_validate_video_id(self, youtube_service):
        """Test video ID validation."""
        assert youtube_service.validate_video_id('dQw4w9WgXcQ') is True
        assert youtube_service.validate_video_id('abcdefghijk') is True
        assert youtube_service.validate_video_id('abc123-_XYZ') is True
        assert youtube_service.validate_video_id('short') is False  # Too short
        assert youtube_service.validate_video_id('toolongvidid') is False  # Too long
        assert youtube_service.validate_video_id('') is False


class TestYouTubeServiceErrors:
    """Test error handling in YouTubeService."""
    
    @pytest.mark.asyncio
    async def test_api_key_missing(self):
        """Test error when API key is not provided."""
        with patch.dict('os.environ', {}, clear=True):
            with patch('app.core.config.settings.YOUTUBE_API_KEY', None):
                with pytest.raises(ValueError, match="YouTube API key is required"):
                    YouTubeService()
    
    @pytest.mark.asyncio
    async def test_quota_exceeded_error(self):
        """Test quota exceeded error handling."""
        from googleapiclient.errors import HttpError
        from unittest.mock import Mock
        
        with patch('app.services.youtube.build') as mock_build:
            mock_client = MagicMock()
            mock_build.return_value = mock_client
            
            # Create HTTP 403 error (quota exceeded)
            http_error = HttpError(
                resp=Mock(status=403),
                content=b'Quota exceeded'
            )
            mock_client.channels().list().execute.side_effect = http_error
            
            service = YouTubeService(api_key='test_key')
            service._youtube = mock_client
            
            with pytest.raises(YouTubeQuotaExceededError):
                await service.get_channel_by_id('UCtest')


class TestYouTubeServiceIntegration:
    """
    Integration tests for YouTubeService.
    
    These tests are skipped by default as they require a real API key
    and will consume quota. Run with: pytest -m integration
    """
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_channel_fetch(self, pytestconfig):
        """Test fetching a real channel (requires API key)."""
        # This test is skipped by default
        # To run: pytest -m integration --run-integration
        if not pytestconfig.getoption("--run-integration", default=False):
            pytest.skip("Integration tests disabled by default")
        
        service = YouTubeService()  # Uses real API key from env
        
        # Fireship channel (public, stable)
        channel = await service.get_channel_by_id('UCsBjURrPoezykLs9EqgamOA')
        
        assert channel['id'] == 'UCsBjURrPoezykLs9EqgamOA'
        assert 'Fireship' in channel['title']
        assert channel['subscriber_count'] > 0

