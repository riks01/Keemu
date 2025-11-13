"""
YouTube transcript extraction service with multiple fallback strategies.

This module provides robust transcript extraction with fallbacks:
1. Manual transcripts (preferred)
2. Auto-generated captions
3. Alternative languages
4. (Optional) Whisper API transcription
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    TooManyRequests,
    NotTranslatable,
    TranslationLanguageNotAvailable,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


class TranscriptError(Exception):
    """Base exception for transcript-related errors."""
    pass


class NoTranscriptAvailable(TranscriptError):
    """Raised when no transcript is available for a video."""
    pass


class TranscriptLanguageMismatch(TranscriptError):
    """Raised when transcript is not in preferred language."""
    pass


class TranscriptService:
    """
    Service for extracting and processing YouTube video transcripts.
    
    Implements multiple fallback strategies to maximize transcript availability:
    1. Try manual transcript in preferred languages
    2. Try auto-generated transcript in preferred languages
    3. Try manual transcript in any language
    4. Try auto-generated transcript in any language
    5. (Optional) Use Whisper API as last resort
    
    Example:
        >>> service = TranscriptService()
        >>> text, metadata = await service.get_transcript("dQw4w9WgXcQ")
        >>> print(f"Got {len(text)} chars in {metadata['language']}")
    """
    
    def __init__(self):
        """Initialize transcript service with configuration from settings."""
        self.preferred_languages = self._get_preferred_languages()
        logger.info(f"TranscriptService initialized with languages: {self.preferred_languages}")
    
    def _get_preferred_languages(self) -> List[str]:
        """Get preferred transcript languages from settings."""
        # settings.YOUTUBE_PREFERRED_TRANSCRIPT_LANGUAGES is already parsed as List[str]
        return settings.YOUTUBE_PREFERRED_TRANSCRIPT_LANGUAGES
    
    async def get_transcript(
        self,
        video_id: str,
        preferred_languages: Optional[List[str]] = None
    ) -> Tuple[str, Dict]:
        """
        Get transcript for a YouTube video with fallback strategies.
        
        Args:
            video_id: YouTube video ID
            preferred_languages: Override default preferred languages
            
        Returns:
            Tuple of (transcript_text, metadata)
            
            metadata contains:
            {
                'language': str,
                'type': 'manual' or 'auto',
                'video_id': str,
                'is_translatable': bool,
                'available_languages': List[str]
            }
            
        Raises:
            NoTranscriptAvailable: If no transcript could be obtained
            VideoUnavailable: If video doesn't exist
        """
        languages = preferred_languages or self.preferred_languages
        
        try:
            # Get all available transcripts for the video
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Collect available languages for metadata
            available_languages = []
            for transcript in transcript_list:
                available_languages.append(transcript.language_code)
            
            # Strategy 1: Try manual transcript in preferred languages
            transcript_text, transcript_obj = await self._try_manual_transcripts(
                transcript_list, languages
            )
            if transcript_text:
                return transcript_text, {
                    'language': transcript_obj.language_code,
                    'type': 'manual',
                    'video_id': video_id,
                    'is_translatable': transcript_obj.is_translatable,
                    'available_languages': available_languages
                }
            
            # Strategy 2: Try auto-generated transcript in preferred languages
            transcript_text, transcript_obj = await self._try_auto_generated_transcripts(
                transcript_list, languages
            )
            if transcript_text:
                return transcript_text, {
                    'language': transcript_obj.language_code,
                    'type': 'auto',
                    'video_id': video_id,
                    'is_translatable': transcript_obj.is_translatable,
                    'available_languages': available_languages
                }
            
            # Strategy 3: Try manual transcript in any language
            transcript_text, transcript_obj = await self._try_any_manual_transcript(
                transcript_list
            )
            if transcript_text:
                logger.info(
                    f"Using manual transcript in non-preferred language "
                    f"{transcript_obj.language_code} for video {video_id}"
                )
                return transcript_text, {
                    'language': transcript_obj.language_code,
                    'type': 'manual',
                    'video_id': video_id,
                    'is_translatable': transcript_obj.is_translatable,
                    'available_languages': available_languages
                }
            
            # Strategy 4: Try auto-generated transcript in any language
            transcript_text, transcript_obj = await self._try_any_auto_generated_transcript(
                transcript_list
            )
            if transcript_text:
                logger.info(
                    f"Using auto-generated transcript in non-preferred language "
                    f"{transcript_obj.language_code} for video {video_id}"
                )
                return transcript_text, {
                    'language': transcript_obj.language_code,
                    'type': 'auto',
                    'video_id': video_id,
                    'is_translatable': transcript_obj.is_translatable,
                    'available_languages': available_languages
                }
            
            # No transcript available
            raise NoTranscriptAvailable(
                f"No transcript available for video {video_id} in any language"
            )
        
        except NoTranscriptAvailable:
            # Re-raise as-is (don't wrap)
            raise
        except TranscriptsDisabled:
            raise NoTranscriptAvailable(f"Transcripts are disabled for video {video_id}")
        except VideoUnavailable:
            raise NoTranscriptAvailable(f"Video {video_id} is unavailable")
        except TooManyRequests:
            logger.error(f"Rate limited while fetching transcript for {video_id}")
            raise TranscriptError("YouTube rate limit exceeded, please try again later")
        except Exception as e:
            logger.error(f"Unexpected error getting transcript for {video_id}: {e}")
            raise TranscriptError(f"Failed to get transcript: {e}")
    
    async def get_available_transcript_languages(self, video_id: str) -> List[Dict]:
        """
        Get list of available transcript languages for a video.
        
        Args:
            video_id: YouTube video ID
            
        Returns:
            List of dictionaries:
            [
                {
                    'language': str,
                    'language_code': str,
                    'is_generated': bool,
                    'is_translatable': bool
                },
                ...
            ]
        """
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            languages = []
            for transcript in transcript_list:
                languages.append({
                    'language': transcript.language,
                    'language_code': transcript.language_code,
                    'is_generated': transcript.is_generated,
                    'is_translatable': transcript.is_translatable
                })
            
            return languages
        
        except Exception as e:
            logger.error(f"Error getting available languages for {video_id}: {e}")
            return []
    
    async def _try_manual_transcripts(
        self,
        transcript_list,
        languages: List[str]
    ) -> Tuple[Optional[str], Optional[any]]:
        """Try to get manual transcript in preferred languages."""
        for lang in languages:
            try:
                transcript = transcript_list.find_manually_created_transcript([lang])
                text = self._format_transcript(transcript.fetch())
                return self.clean_transcript(text), transcript
            except NoTranscriptFound:
                continue
        return None, None
    
    async def _try_auto_generated_transcripts(
        self,
        transcript_list,
        languages: List[str]
    ) -> Tuple[Optional[str], Optional[any]]:
        """Try to get auto-generated transcript in preferred languages."""
        for lang in languages:
            try:
                transcript = transcript_list.find_generated_transcript([lang])
                text = self._format_transcript(transcript.fetch())
                return self.clean_transcript(text), transcript
            except NoTranscriptFound:
                continue
        return None, None
    
    async def _try_any_manual_transcript(
        self,
        transcript_list
    ) -> Tuple[Optional[str], Optional[any]]:
        """Try to get any manually created transcript."""
        try:
            for transcript in transcript_list:
                if not transcript.is_generated:
                    text = self._format_transcript(transcript.fetch())
                    return self.clean_transcript(text), transcript
        except Exception as e:
            logger.debug(f"No manual transcripts available: {e}")
        return None, None
    
    async def _try_any_auto_generated_transcript(
        self,
        transcript_list
    ) -> Tuple[Optional[str], Optional[any]]:
        """Try to get any auto-generated transcript."""
        try:
            for transcript in transcript_list:
                if transcript.is_generated:
                    text = self._format_transcript(transcript.fetch())
                    return self.clean_transcript(text), transcript
        except Exception as e:
            logger.debug(f"No auto-generated transcripts available: {e}")
        return None, None
    
    def _format_transcript(self, transcript_entries: List[Dict]) -> str:
        """
        Format transcript entries into plain text.
        
        Args:
            transcript_entries: List of transcript entries from API
            [{'text': 'Hello', 'start': 0.0, 'duration': 1.5}, ...]
            
        Returns:
            Formatted transcript text
        """
        # Join all text entries with spaces
        text = ' '.join(entry['text'] for entry in transcript_entries)
        return text
    
    @staticmethod
    def clean_transcript(text: str) -> str:
        """
        Clean and normalize transcript text.
        
        Removes:
        - Extra whitespace
        - Music/sound effect tags like [Music], [Applause]
        - Timestamps if present
        - Special characters that might interfere with processing
        
        Args:
            text: Raw transcript text
            
        Returns:
            Cleaned transcript text
        """
        if not text:
            return ""
        
        # Remove common sound effect tags
        text = re.sub(r'\[Music\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[Applause\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[Laughter\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[.*?\]', '', text)  # Remove any remaining bracketed content
        
        # Remove timestamps (e.g., "00:01:23" or "1:23")
        text = re.sub(r'\d{1,2}:\d{2}(?::\d{2})?', '', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Remove repeated punctuation
        text = re.sub(r'([.!?])\1+', r'\1', text)
        
        # Fix common auto-caption issues
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        
        return text
    
    @staticmethod
    def calculate_transcript_quality_score(metadata: Dict) -> float:
        """
        Calculate a quality score for a transcript.
        
        Scoring criteria:
        - Manual transcripts score higher than auto-generated
        - Preferred language scores higher
        - Translatable transcripts score slightly higher
        
        Args:
            metadata: Transcript metadata
            
        Returns:
            Quality score (0.0 to 1.0)
        """
        score = 0.5  # Base score
        
        # Type scoring
        if metadata.get('type') == 'manual':
            score += 0.3
        else:
            score += 0.1
        
        # Language scoring
        preferred_langs = settings.YOUTUBE_PREFERRED_TRANSCRIPT_LANGUAGES
        if metadata.get('language') in preferred_langs:
            score += 0.2
        
        # Translatable bonus
        if metadata.get('is_translatable'):
            score += 0.05
        
        return min(score, 1.0)


# ========================================
# Helper Functions
# ========================================

def get_transcript_service() -> TranscriptService:
    """
    Get or create transcript service instance.
    
    Returns:
        TranscriptService instance
    """
    return TranscriptService()

