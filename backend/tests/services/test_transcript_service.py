"""
Unit tests for transcript service.

These tests mock the YouTube Transcript API to avoid network calls.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from app.services.transcript_service import (
    TranscriptService,
    TranscriptError,
    NoTranscriptAvailable,
    TranscriptLanguageMismatch,
)
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)


class MockTranscript:
    """Mock transcript object."""
    
    def __init__(self, language_code, is_generated=False, is_translatable=False):
        self.language = f"Language-{language_code}"
        self.language_code = language_code
        self.is_generated = is_generated
        self.is_translatable = is_translatable
    
    def fetch(self):
        """Return mock transcript entries."""
        return [
            {'text': 'Hello', 'start': 0.0, 'duration': 1.0},
            {'text': 'world', 'start': 1.0, 'duration': 1.0},
            {'text': '!', 'start': 2.0, 'duration': 0.5},
        ]


class MockTranscriptList:
    """Mock transcript list."""
    
    def __init__(self, transcripts):
        self._transcripts = transcripts
    
    def __iter__(self):
        return iter(self._transcripts)
    
    def find_manually_created_transcript(self, language_codes):
        """Find manual transcript in specified languages."""
        for transcript in self._transcripts:
            if not transcript.is_generated and transcript.language_code in language_codes:
                return transcript
        raise NoTranscriptFound('video_id', language_codes, None)
    
    def find_generated_transcript(self, language_codes):
        """Find auto-generated transcript in specified languages."""
        for transcript in self._transcripts:
            if transcript.is_generated and transcript.language_code in language_codes:
                return transcript
        raise NoTranscriptFound('video_id', language_codes, None)


class TestTranscriptService:
    """Test suite for TranscriptService."""
    
    @pytest.fixture
    def transcript_service(self):
        """Create TranscriptService instance."""
        return TranscriptService()
    
    # ========================================
    # Transcript Extraction Tests
    # ========================================
    
    @pytest.mark.asyncio
    async def test_get_transcript_manual_english(self, transcript_service):
        """Test getting manual English transcript (preferred)."""
        mock_transcripts = [
            MockTranscript('en', is_generated=False),
            MockTranscript('es', is_generated=True),
        ]
        mock_list = MockTranscriptList(mock_transcripts)
        
        with patch('app.services.transcript_service.YouTubeTranscriptApi.list_transcripts') as mock:
            mock.return_value = mock_list
            
            text, metadata = await transcript_service.get_transcript('test_video_id')
            
            # Assert
            assert 'Hello world !' in text
            assert metadata['language'] == 'en'
            assert metadata['type'] == 'manual'
            assert metadata['video_id'] == 'test_video_id'
    
    @pytest.mark.asyncio
    async def test_get_transcript_auto_generated_fallback(self, transcript_service):
        """Test falling back to auto-generated transcript."""
        mock_transcripts = [
            MockTranscript('en', is_generated=True),  # Only auto-generated available
        ]
        mock_list = MockTranscriptList(mock_transcripts)
        
        with patch('app.services.transcript_service.YouTubeTranscriptApi.list_transcripts') as mock:
            mock.return_value = mock_list
            
            text, metadata = await transcript_service.get_transcript('test_video_id')
            
            # Assert
            assert 'Hello world !' in text
            assert metadata['language'] == 'en'
            assert metadata['type'] == 'auto'
    
    @pytest.mark.asyncio
    async def test_get_transcript_non_preferred_language(self, transcript_service):
        """Test getting transcript in non-preferred language."""
        mock_transcripts = [
            MockTranscript('es', is_generated=False),  # Spanish manual
            MockTranscript('fr', is_generated=True),   # French auto
        ]
        mock_list = MockTranscriptList(mock_transcripts)
        
        with patch('app.services.transcript_service.YouTubeTranscriptApi.list_transcripts') as mock:
            mock.return_value = mock_list
            
            text, metadata = await transcript_service.get_transcript('test_video_id')
            
            # Should get Spanish manual (strategy 3)
            assert metadata['language'] == 'es'
            assert metadata['type'] == 'manual'
    
    @pytest.mark.asyncio
    async def test_get_transcript_no_transcript_available(self, transcript_service):
        """Test error when no transcript is available."""
        mock_list = MockTranscriptList([])  # No transcripts
        
        with patch('app.services.transcript_service.YouTubeTranscriptApi.list_transcripts') as mock:
            mock.return_value = mock_list
            
            with pytest.raises(NoTranscriptAvailable):
                await transcript_service.get_transcript('test_video_id')
    
    @pytest.mark.asyncio
    async def test_get_transcript_transcripts_disabled(self, transcript_service):
        """Test error when transcripts are disabled."""
        with patch('app.services.transcript_service.YouTubeTranscriptApi.list_transcripts') as mock:
            mock.side_effect = TranscriptsDisabled('test_video_id')
            
            with pytest.raises(NoTranscriptAvailable, match="disabled"):
                await transcript_service.get_transcript('test_video_id')
    
    @pytest.mark.asyncio
    async def test_get_transcript_video_unavailable(self, transcript_service):
        """Test error when video is unavailable."""
        with patch('app.services.transcript_service.YouTubeTranscriptApi.list_transcripts') as mock:
            mock.side_effect = VideoUnavailable('test_video_id')
            
            with pytest.raises(NoTranscriptAvailable, match="unavailable"):
                await transcript_service.get_transcript('test_video_id')
    
    @pytest.mark.asyncio
    async def test_get_transcript_with_custom_languages(self, transcript_service):
        """Test getting transcript with custom preferred languages."""
        mock_transcripts = [
            MockTranscript('fr', is_generated=False),
            MockTranscript('en', is_generated=False),
        ]
        mock_list = MockTranscriptList(mock_transcripts)
        
        with patch('app.services.transcript_service.YouTubeTranscriptApi.list_transcripts') as mock:
            mock.return_value = mock_list
            
            # Request French specifically
            text, metadata = await transcript_service.get_transcript(
                'test_video_id',
                preferred_languages=['fr']
            )
            
            assert metadata['language'] == 'fr'
    
    # ========================================
    # Available Languages Tests
    # ========================================
    
    @pytest.mark.asyncio
    async def test_get_available_transcript_languages(self, transcript_service):
        """Test getting list of available transcript languages."""
        mock_transcripts = [
            MockTranscript('en', is_generated=False, is_translatable=True),
            MockTranscript('es', is_generated=True, is_translatable=False),
        ]
        mock_list = MockTranscriptList(mock_transcripts)
        
        with patch('app.services.transcript_service.YouTubeTranscriptApi.list_transcripts') as mock:
            mock.return_value = mock_list
            
            languages = await transcript_service.get_available_transcript_languages('test_video_id')
            
            assert len(languages) == 2
            assert languages[0]['language_code'] == 'en'
            assert languages[0]['is_generated'] is False
            assert languages[1]['language_code'] == 'es'
            assert languages[1]['is_generated'] is True
    
    @pytest.mark.asyncio
    async def test_get_available_transcript_languages_error(self, transcript_service):
        """Test error handling when getting available languages."""
        with patch('app.services.transcript_service.YouTubeTranscriptApi.list_transcripts') as mock:
            mock.side_effect = Exception("API error")
            
            # Should return empty list on error
            languages = await transcript_service.get_available_transcript_languages('test_video_id')
            assert languages == []
    
    # ========================================
    # Transcript Cleaning Tests
    # ========================================
    
    def test_clean_transcript_basic(self, transcript_service):
        """Test basic transcript cleaning."""
        raw = "  Hello   world  !  "
        cleaned = transcript_service.clean_transcript(raw)
        assert cleaned == "Hello world !"
    
    def test_clean_transcript_music_tags(self, transcript_service):
        """Test removal of music and sound tags."""
        raw = "[Music] Hello world [Applause] test [Laughter]"
        cleaned = transcript_service.clean_transcript(raw)
        assert cleaned == "Hello world test"
        assert '[Music]' not in cleaned
        assert '[Applause]' not in cleaned
    
    def test_clean_transcript_timestamps(self, transcript_service):
        """Test removal of timestamps."""
        raw = "00:00:10 Hello 1:23 world 01:23:45 test"
        cleaned = transcript_service.clean_transcript(raw)
        assert cleaned == "Hello world test"
        assert '00:00:10' not in cleaned
        assert '1:23' not in cleaned
    
    def test_clean_transcript_html_entities(self, transcript_service):
        """Test HTML entity decoding."""
        raw = "Hello&nbsp;world &amp; test &lt;tag&gt;"
        cleaned = transcript_service.clean_transcript(raw)
        assert cleaned == "Hello world & test <tag>"
    
    def test_clean_transcript_repeated_punctuation(self, transcript_service):
        """Test removal of repeated punctuation."""
        raw = "Hello!!! World??? Test..."
        cleaned = transcript_service.clean_transcript(raw)
        assert cleaned == "Hello! World? Test."
    
    def test_clean_transcript_empty(self, transcript_service):
        """Test cleaning empty transcript."""
        assert transcript_service.clean_transcript("") == ""
        assert transcript_service.clean_transcript(None) == ""
    
    # ========================================
    # Quality Score Tests
    # ========================================
    
    def test_calculate_transcript_quality_score_manual_preferred(self, transcript_service):
        """Test quality score for manual transcript in preferred language."""
        metadata = {
            'type': 'manual',
            'language': 'en',
            'is_translatable': True
        }
        
        score = transcript_service.calculate_transcript_quality_score(metadata)
        
        # Should get highest score: 0.5 + 0.3 (manual) + 0.2 (preferred) + 0.05 (translatable) = 1.05 -> 1.0
        assert score == 1.0
    
    def test_calculate_transcript_quality_score_auto_non_preferred(self, transcript_service):
        """Test quality score for auto-generated transcript in non-preferred language."""
        metadata = {
            'type': 'auto',
            'language': 'es',
            'is_translatable': False
        }
        
        score = transcript_service.calculate_transcript_quality_score(metadata)
        
        # Should get: 0.5 + 0.1 (auto) + 0 (non-preferred) + 0 (not translatable) = 0.6
        assert score == 0.6
    
    def test_calculate_transcript_quality_score_manual_non_preferred(self, transcript_service):
        """Test quality score for manual transcript in non-preferred language."""
        metadata = {
            'type': 'manual',
            'language': 'fr',
            'is_translatable': True
        }
        
        score = transcript_service.calculate_transcript_quality_score(metadata)
        
        # Should get: 0.5 + 0.3 (manual) + 0 (non-preferred) + 0.05 (translatable) = 0.85
        assert abs(score - 0.85) < 0.01  # Use approximate comparison for floats


class TestTranscriptServiceIntegration:
    """
    Integration tests for TranscriptService.
    
    These tests require network access and are skipped by default.
    Run with: pytest -m integration --run-integration
    """
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_transcript_fetch(self, pytestconfig):
        """Test fetching a real transcript."""
        if not pytestconfig.getoption("--run-integration", default=False):
            pytest.skip("Integration tests disabled by default")
        
        service = TranscriptService()
        
        # Rick Astley - Never Gonna Give You Up (has transcripts)
        video_id = 'dQw4w9WgXcQ'
        
        text, metadata = await service.get_transcript(video_id)
        
        assert len(text) > 0
        assert metadata['video_id'] == video_id
        assert metadata['language'] in ['en', 'en-US', 'en-GB']
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_available_languages(self, pytestconfig):
        """Test getting available languages for a real video."""
        if not pytestconfig.getoption("--run-integration", default=False):
            pytest.skip("Integration tests disabled by default")
        
        service = TranscriptService()
        
        # Rick Astley - Never Gonna Give You Up
        video_id = 'dQw4w9WgXcQ'
        
        languages = await service.get_available_transcript_languages(video_id)
        
        assert len(languages) > 0
        assert any(lang['language_code'].startswith('en') for lang in languages)


# ========================================
# Pytest Configuration
# ========================================

def pytest_addoption(parser):
    """Add custom pytest options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require network access"
    )


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires network)"
    )

