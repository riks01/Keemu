"""
Tests for TextSearchService.

This test module verifies:
1. tsvector generation
2. Weighted tsvector generation
3. Query preparation
4. Search functionality
5. Query explanation
6. Text cleaning utilities
"""

import pytest
from app.services.processors.text_search import (
    TextSearchService,
    clean_text_for_search
)


@pytest.mark.asyncio
class TestTextSearchServiceBasics:
    """Test basic TextSearchService functionality."""
    
    def test_initialization(self):
        """Test service initialization."""
        service = TextSearchService()
        assert service.language == "english"
        
        service_custom = TextSearchService(language="spanish")
        assert service_custom.language == "spanish"
    
    async def test_generate_tsvector(self, db_session):
        """Test generating tsvector from text."""
        service = TextSearchService()
        
        text = "React hooks are a powerful feature"
        tsvector = await service.generate_tsvector(db_session, text)
        
        # Should return a tsvector string
        assert tsvector is not None
        assert isinstance(tsvector, str)
        
        # Should contain stemmed words
        # "hooks" → "hook", "powerful" → "power", etc.
        assert "'" in tsvector  # tsvector format uses quotes
    
    async def test_generate_tsvector_empty(self, db_session):
        """Test generating tsvector from empty text."""
        service = TextSearchService()
        
        tsvector = await service.generate_tsvector(db_session, "")
        assert tsvector is None
        
        tsvector = await service.generate_tsvector(db_session, "   ")
        assert tsvector is None
    
    async def test_generate_tsvector_with_weight(self, db_session):
        """Test generating tsvector with different weights."""
        service = TextSearchService()
        
        text = "React hooks"
        
        # Weight A (most important)
        # Format is 'word':positionWEIGHT (e.g., 'react':1A)
        tsvector_a = await service.generate_tsvector(db_session, text, weight="A")
        assert tsvector_a is not None
        assert "A" in tsvector_a  # Should have 'A' weight marker
        assert ":" in tsvector_a  # Should have position markers
        
        # Weight D (least important)
        # Note: PostgreSQL doesn't display weight D in text output (it's the default)
        tsvector_d = await service.generate_tsvector(db_session, text, weight="D")
        assert tsvector_d is not None
        assert ":" in tsvector_d  # Should have position markers
        # Weight D is not displayed in output (it's the default weight)


@pytest.mark.asyncio
class TestWeightedTsvector:
    """Test weighted tsvector generation."""
    
    async def test_generate_weighted_tsvector(self, db_session):
        """Test generating weighted tsvector from multiple fields."""
        service = TextSearchService()
        
        title = "React Hooks Tutorial"
        body = "Hooks allow you to use state in functional components."
        metadata = "react javascript tutorial"
        
        tsvector = await service.generate_weighted_tsvector(
            db_session,
            title=title,
            body=body,
            metadata=metadata
        )
        
        # Should combine all fields
        assert tsvector is not None
        assert isinstance(tsvector, str)
        
        # Should contain words from all fields
        # (stemmed versions)
        assert len(tsvector) > 0
    
    async def test_generate_weighted_tsvector_partial(self, db_session):
        """Test weighted tsvector with some empty fields."""
        service = TextSearchService()
        
        # Only title and body
        tsvector = await service.generate_weighted_tsvector(
            db_session,
            title="React Hooks",
            body="Hooks are great",
            metadata=None
        )
        
        assert tsvector is not None
        
        # Only title
        tsvector = await service.generate_weighted_tsvector(
            db_session,
            title="React Hooks",
            body=None,
            metadata=None
        )
        
        assert tsvector is not None
    
    async def test_generate_weighted_tsvector_all_empty(self, db_session):
        """Test weighted tsvector with all empty fields."""
        service = TextSearchService()
        
        tsvector = await service.generate_weighted_tsvector(
            db_session,
            title="",
            body="",
            metadata=""
        )
        
        # Should return None when all fields are empty
        assert tsvector is None


class TestQueryPreparation:
    """Test search query preparation."""
    
    def test_prepare_simple_query(self):
        """Test preparing simple query."""
        service = TextSearchService()
        
        query = service.prepare_search_query("react hooks")
        
        # Should add prefix matching and AND operator
        assert "react:*" in query
        assert "hooks:*" in query
        assert "&" in query  # AND operator
    
    def test_prepare_query_without_prefix(self):
        """Test preparing query without prefix matching."""
        service = TextSearchService()
        
        query = service.prepare_search_query(
            "react hooks",
            use_prefix_matching=False
        )
        
        # Should not have prefix matching
        assert ":*" not in query
        assert "react" in query
        assert "hooks" in query
        assert "&" in query
    
    def test_prepare_query_with_or(self):
        """Test preparing query with OR operator."""
        service = TextSearchService()
        
        query = service.prepare_search_query("react OR vue")
        
        # Should preserve OR operator
        assert "|" in query  # PostgreSQL OR operator
        assert "react:*" in query
        assert "vue:*" in query
    
    def test_prepare_query_with_and(self):
        """Test preparing query with explicit AND."""
        service = TextSearchService()
        
        query = service.prepare_search_query("react AND hooks")
        
        # Should have AND operator
        assert "&" in query
        assert "react:*" in query
        assert "hooks:*" in query
    
    def test_prepare_query_with_not(self):
        """Test preparing query with NOT operator."""
        service = TextSearchService()
        
        query = service.prepare_search_query("react NOT class")
        
        # Should have NOT operator
        assert "!" in query  # PostgreSQL NOT operator
        assert "react:*" in query
        assert "class:*" in query
    
    def test_prepare_empty_query(self):
        """Test preparing empty query."""
        service = TextSearchService()
        
        query = service.prepare_search_query("")
        assert query == ""
        
        query = service.prepare_search_query("   ")
        assert query == ""
    
    def test_prepare_query_special_characters(self):
        """Test preparing query with special characters."""
        service = TextSearchService()
        
        # Special characters should be removed/handled
        query = service.prepare_search_query("react@hooks#test")
        
        # Should clean special characters
        assert "@" not in query
        assert "#" not in query
        assert "react" in query
        assert "hooks" in query
        assert "test" in query


@pytest.mark.asyncio
class TestSearchFunctionality:
    """Test search functionality."""
    
    async def test_search_basic(self, db_session):
        """Test basic search functionality."""
        service = TextSearchService()
        
        # Generate tsvectors for test documents
        doc1 = "React hooks are a powerful feature"
        doc2 = "Vue composition API is similar to hooks"
        doc3 = "Angular has dependency injection"
        
        tsvector1 = await service.generate_tsvector(db_session, doc1)
        tsvector2 = await service.generate_tsvector(db_session, doc2)
        tsvector3 = await service.generate_tsvector(db_session, doc3)
        
        # Search for "hooks"
        query = "hooks"
        scores = await service.search(
            db_session,
            query,
            [tsvector1, tsvector2, tsvector3]
        )
        
        # Should return scores for all documents
        assert len(scores) == 3
        
        # Documents with "hooks" should have higher scores
        assert scores[0] > 0  # doc1 has "hooks"
        assert scores[1] > 0  # doc2 has "hooks"
        assert scores[2] == 0  # doc3 doesn't have "hooks"
    
    async def test_search_empty_query(self, db_session):
        """Test search with empty query."""
        service = TextSearchService()
        
        doc = "React hooks"
        tsvector = await service.generate_tsvector(db_session, doc)
        
        scores = await service.search(db_session, "", [tsvector])
        
        # Empty query should return zero scores
        assert scores == [0.0]
    
    async def test_search_empty_documents(self, db_session):
        """Test search with empty documents."""
        service = TextSearchService()
        
        scores = await service.search(db_session, "react hooks", [])
        
        # No documents should return empty list
        assert scores == []
    
    async def test_search_relevance_ranking(self, db_session):
        """Test that search ranks by relevance."""
        service = TextSearchService()
        
        # Create documents with different relevance levels
        doc1 = "hooks"  # Single mention (shorter doc)
        doc2 = "hooks and hooks again"  # Multiple mentions (longer doc)
        doc3 = "something else entirely"  # No match
        
        tsvector1 = await service.generate_tsvector(db_session, doc1)
        tsvector2 = await service.generate_tsvector(db_session, doc2)
        tsvector3 = await service.generate_tsvector(db_session, doc3)
        
        scores = await service.search(
            db_session,
            "hooks",
            [tsvector1, tsvector2, tsvector3]
        )
        
        # Note: With normalization=1, shorter documents can rank higher
        # doc1 (shorter, single mention) gets higher score than doc2 (longer, multiple mentions)
        # This is expected behavior with length normalization
        assert scores[0] > 0  # doc1 has match
        assert scores[1] > 0  # doc2 has match  
        assert scores[0] > scores[2]  # doc1 > doc3
        assert scores[1] > scores[2]  # doc2 > doc3
        assert scores[2] == 0  # doc3 has no match


class TestQueryExplanation:
    """Test query explanation."""
    
    def test_explain_simple_query(self):
        """Test explaining a simple query."""
        service = TextSearchService()
        
        explanation = service.explain_query("react hooks")
        
        assert explanation["original"] == "react hooks"
        assert "prepared" in explanation
        assert "tokens" in explanation
        assert "operators" in explanation
        assert "language" in explanation
        
        # Should have two tokens
        assert len(explanation["tokens"]) == 2
        assert "react" in explanation["tokens"]
        assert "hooks" in explanation["tokens"]
    
    def test_explain_complex_query(self):
        """Test explaining a complex query with operators."""
        service = TextSearchService()
        
        explanation = service.explain_query("react OR vue AND hooks")
        
        # Should detect operators
        assert len(explanation["operators"]) > 0
        assert "|" in explanation["operators"]  # OR
        assert "&" in explanation["operators"]  # AND
    
    def test_explain_empty_query(self):
        """Test explaining empty query."""
        service = TextSearchService()
        
        explanation = service.explain_query("")
        
        assert explanation["original"] == ""
        assert explanation["tokens"] == []


class TestTextCleaning:
    """Test text cleaning utilities."""
    
    def test_clean_text_html(self):
        """Test cleaning HTML tags."""
        text = "<p>React <strong>hooks</strong> are great</p>"
        cleaned = clean_text_for_search(text)
        
        assert "<p>" not in cleaned
        assert "<strong>" not in cleaned
        assert "React" in cleaned
        assert "hooks" in cleaned
    
    def test_clean_text_urls(self):
        """Test cleaning URLs."""
        text = "Check out https://react.dev for more info"
        cleaned = clean_text_for_search(text)
        
        assert "https://react.dev" not in cleaned
        assert "Check out" in cleaned
        assert "for more info" in cleaned
    
    def test_clean_text_emails(self):
        """Test cleaning email addresses."""
        text = "Contact us at info@example.com for help"
        cleaned = clean_text_for_search(text)
        
        assert "info@example.com" not in cleaned
        assert "Contact us at" in cleaned
        assert "for help" in cleaned
    
    def test_clean_text_whitespace(self):
        """Test cleaning excessive whitespace."""
        text = "React    hooks   are    great"
        cleaned = clean_text_for_search(text)
        
        # Should normalize to single spaces
        assert "    " not in cleaned
        assert "React hooks are great" == cleaned
    
    def test_clean_text_empty(self):
        """Test cleaning empty text."""
        assert clean_text_for_search("") == ""
        assert clean_text_for_search(None) == ""
    
    def test_clean_text_combined(self):
        """Test cleaning text with multiple issues."""
        text = """
        <div>
            Check out https://example.com for React hooks info.
            Email: test@example.com
            
            
            Multiple    spaces    here
        </div>
        """
        cleaned = clean_text_for_search(text)
        
        # Should remove all problematic content
        assert "<div>" not in cleaned
        assert "https://example.com" not in cleaned
        assert "test@example.com" not in cleaned
        assert "    " not in cleaned
        
        # Should keep useful content
        assert "React hooks info" in cleaned

