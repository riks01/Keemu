"""
Unit tests for BlogService.

Tests cover:
- RSS feed discovery
- Feed parsing
- Multi-stage article extraction
- Quality scoring
- Robots.txt compliance
- URL validation
- Content cleaning
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
import requests

from app.services.blog_service import (
    BlogService,
    BlogServiceError,
    FeedNotFoundError,
    ArticleExtractionError,
    RobotsTxtForbiddenError
)


# ========================================
# Fixtures
# ========================================


@pytest.fixture
def blog_service():
    """Create BlogService instance."""
    return BlogService()


@pytest.fixture
def mock_rss_feed():
    """Mock RSS feed XML."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
    <channel>
        <title>Example Blog</title>
        <link>https://example.com/blog</link>
        <description>A test blog</description>
        <item>
            <title>Test Article 1</title>
            <link>https://example.com/blog/article-1</link>
            <description>This is a test article</description>
            <author>John Doe</author>
            <pubDate>Mon, 01 Nov 2025 10:00:00 +0000</pubDate>
            <guid>https://example.com/blog/article-1</guid>
        </item>
        <item>
            <title>Test Article 2</title>
            <link>https://example.com/blog/article-2</link>
            <description>Another test article</description>
            <author>Jane Smith</author>
            <pubDate>Sun, 31 Oct 2025 15:00:00 +0000</pubDate>
            <guid>https://example.com/blog/article-2</guid>
        </item>
    </channel>
</rss>"""


@pytest.fixture
def mock_atom_feed():
    """Mock Atom feed XML."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
    <title>Example Blog</title>
    <link href="https://example.com/blog"/>
    <updated>2025-11-01T10:00:00Z</updated>
    <entry>
        <title>Test Article</title>
        <link href="https://example.com/blog/article"/>
        <id>https://example.com/blog/article</id>
        <updated>2025-11-01T10:00:00Z</updated>
        <summary>Test summary</summary>
        <author><name>John Doe</name></author>
    </entry>
</feed>"""


@pytest.fixture
def mock_blog_html_with_feed():
    """Mock blog HTML with feed link."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Example Blog</title>
    <link rel="alternate" type="application/rss+xml" href="/feed" title="RSS Feed">
</head>
<body>
    <h1>Welcome to Example Blog</h1>
</body>
</html>"""


@pytest.fixture
def mock_article_html():
    """Mock article HTML."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Test Article Title</title>
</head>
<body>
    <article>
        <h1>Test Article Title</h1>
        <p>This is the first paragraph of the article. It contains some interesting information.</p>
        <p>This is the second paragraph. It has more content to make the article substantial.</p>
        <p>Third paragraph continues the story. We need enough words to test word count scoring.</p>
        <p>Fourth paragraph adds even more content. Quality articles need good length.</p>
        <p>Fifth paragraph wraps things up nicely. This should give us a decent word count.</p>
    </article>
</body>
</html>"""


# ========================================
# URL Validation Tests
# ========================================


def test_validate_blog_url_valid(blog_service):
    """Test validation of valid blog URLs."""
    assert blog_service.validate_blog_url("https://example.com/blog") is True
    assert blog_service.validate_blog_url("http://blog.example.com") is True
    assert blog_service.validate_blog_url("https://www.example.com") is True


def test_validate_blog_url_invalid(blog_service):
    """Test validation of invalid URLs."""
    assert blog_service.validate_blog_url("not-a-url") is False
    assert blog_service.validate_blog_url("") is False
    assert blog_service.validate_blog_url("ftp://example.com") is False
    assert blog_service.validate_blog_url("https://") is False


def test_normalize_url(blog_service):
    """Test URL normalization."""
    assert blog_service._normalize_url("example.com") == "https://example.com"
    assert blog_service._normalize_url("https://example.com/") == "https://example.com"
    assert blog_service._normalize_url("  https://example.com  ") == "https://example.com"


def test_get_domain(blog_service):
    """Test domain extraction."""
    assert blog_service.get_domain("https://example.com/blog/post") == "example.com"
    assert blog_service.get_domain("http://blog.example.com/feed") == "blog.example.com"


# ========================================
# Feed Discovery Tests
# ========================================


@patch('requests.get')
def test_discover_feed_via_link_tag(mock_get, blog_service, mock_blog_html_with_feed):
    """Test feed discovery via <link> tag."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = mock_blog_html_with_feed.encode('utf-8')
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    # Mock feed validation
    with patch.object(blog_service, '_validate_feed_url', return_value=True):
        feed_url = blog_service.discover_feed("https://example.com/blog")
        assert feed_url == "https://example.com/feed"


@patch('requests.get')
def test_discover_feed_common_location(mock_get, blog_service):
    """Test feed discovery at common locations."""
    # Mock blog page without feed link
    mock_response_blog = Mock()
    mock_response_blog.status_code = 200
    mock_response_blog.content = b"<html><body>Blog</body></html>"
    mock_response_blog.raise_for_status = Mock()
    
    mock_get.return_value = mock_response_blog
    
    # Mock feed validation to return True for /feed
    def mock_validate(url):
        return "/feed" in url
    
    with patch.object(blog_service, '_validate_feed_url', side_effect=mock_validate):
        feed_url = blog_service.discover_feed("https://example.com/blog")
        assert feed_url == "https://example.com/feed"


@patch('requests.get')
def test_discover_feed_not_found(mock_get, blog_service):
    """Test feed discovery when no feed exists."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = b"<html><body>Blog without feed</body></html>"
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    with patch.object(blog_service, '_validate_feed_url', return_value=False):
        feed_url = blog_service.discover_feed("https://example.com/blog")
        assert feed_url is None


@patch('requests.get')
def test_discover_feed_request_error(mock_get, blog_service):
    """Test feed discovery with request error."""
    mock_get.side_effect = requests.RequestException("Connection error")
    
    with pytest.raises(BlogServiceError, match="Failed to fetch blog URL"):
        blog_service.discover_feed("https://example.com/blog")


@patch('requests.head')
def test_validate_feed_url_by_content_type(mock_head, blog_service):
    """Test feed URL validation by content type."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {'Content-Type': 'application/rss+xml'}
    mock_head.return_value = mock_response
    
    assert blog_service._validate_feed_url("https://example.com/feed") is True


@patch('requests.head')
@patch('requests.get')
def test_validate_feed_url_by_content(mock_get, mock_head, blog_service):
    """Test feed URL validation by content inspection."""
    # HEAD doesn't give conclusive content-type
    mock_head_response = Mock()
    mock_head_response.status_code = 200
    mock_head_response.headers = {'Content-Type': 'text/html'}
    mock_head.return_value = mock_head_response
    
    # GET returns XML content
    mock_get_response = Mock()
    mock_get_response.raw.read = Mock(return_value=b'<?xml version="1.0"?><rss>')
    mock_get.return_value = mock_get_response
    
    assert blog_service._validate_feed_url("https://example.com/feed") is True


# ========================================
# Feed Parsing Tests
# ========================================


@patch('requests.get')
def test_parse_feed_rss(mock_get, blog_service, mock_rss_feed):
    """Test parsing RSS 2.0 feed."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = mock_rss_feed.encode('utf-8')
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    articles = blog_service.parse_feed("https://example.com/feed")
    
    assert len(articles) == 2
    assert articles[0]['title'] == "Test Article 1"
    assert articles[0]['url'] == "https://example.com/blog/article-1"
    assert articles[0]['author'] == "John Doe"
    assert isinstance(articles[0]['published'], datetime)


@patch('requests.get')
def test_parse_feed_atom(mock_get, blog_service, mock_atom_feed):
    """Test parsing Atom feed."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = mock_atom_feed.encode('utf-8')
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    articles = blog_service.parse_feed("https://example.com/feed")
    
    assert len(articles) >= 1
    assert articles[0]['title'] == "Test Article"
    assert articles[0]['url'] == "https://example.com/blog/article"


@patch('requests.get')
def test_parse_feed_with_since_date(mock_get, blog_service, mock_rss_feed):
    """Test parsing feed with date filter."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = mock_rss_feed.encode('utf-8')
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    # Only articles from Nov 1 onwards
    since_date = datetime(2025, 11, 1, tzinfo=timezone.utc)
    articles = blog_service.parse_feed("https://example.com/feed", since_date=since_date)
    
    assert len(articles) == 1
    assert articles[0]['title'] == "Test Article 1"


@patch('requests.get')
def test_parse_feed_max_entries(mock_get, blog_service, mock_rss_feed):
    """Test parsing feed with max entries limit."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = mock_rss_feed.encode('utf-8')
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    articles = blog_service.parse_feed("https://example.com/feed", max_entries=1)
    
    assert len(articles) == 1


@patch('requests.get')
def test_parse_feed_request_error(mock_get, blog_service):
    """Test feed parsing with request error."""
    mock_get.side_effect = requests.RequestException("Connection error")
    
    with pytest.raises(FeedNotFoundError, match="Failed to fetch feed"):
        blog_service.parse_feed("https://example.com/feed")


@patch('requests.get')
def test_parse_feed_invalid_feed(mock_get, blog_service):
    """Test parsing invalid feed content."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = b"Not a valid feed"
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    with pytest.raises(FeedNotFoundError, match="Invalid feed format"):
        blog_service.parse_feed("https://example.com/feed")


# ========================================
# Article Extraction Tests
# ========================================


@patch.object(BlogService, '_extract_with_trafilatura')
def test_extract_article_trafilatura_success(mock_trafilatura, blog_service):
    """Test article extraction with trafilatura success."""
    mock_article = {
        'title': 'Test Article',
        'content': ' '.join(['word'] * 500),  # 500 words
        'author': 'John Doe',
        'published_date': datetime.now(),
        'language': 'en',
        'word_count': 500,
        'images': [],
        'excerpt': 'Test excerpt',
        'url': 'https://example.com/article'
    }
    mock_trafilatura.return_value = mock_article
    
    result = blog_service.extract_article("https://example.com/article")
    
    assert result is not None
    assert result['extraction_method'] == 'trafilatura'
    assert result['word_count'] == 500
    assert 'quality_score' in result


@patch.object(BlogService, '_extract_with_trafilatura')
@patch.object(BlogService, '_extract_with_newspaper')
def test_extract_article_fallback_to_newspaper(mock_newspaper, mock_trafilatura, blog_service):
    """Test article extraction falls back to newspaper4k."""
    mock_trafilatura.side_effect = Exception("Trafilatura failed")
    
    mock_article = {
        'title': 'Test Article',
        'content': ' '.join(['word'] * 300),
        'author': '',
        'published_date': None,
        'language': 'en',
        'word_count': 300,
        'images': [],
        'excerpt': 'Test',
        'url': 'https://example.com/article'
    }
    mock_newspaper.return_value = mock_article
    
    result = blog_service.extract_article("https://example.com/article")
    
    assert result is not None
    assert result['extraction_method'] == 'newspaper4k'


@patch.object(BlogService, '_extract_with_trafilatura')
@patch.object(BlogService, '_extract_with_newspaper')
@patch.object(BlogService, '_extract_with_readability')
def test_extract_article_fallback_to_readability(
    mock_readability, mock_newspaper, mock_trafilatura, blog_service
):
    """Test article extraction falls back to readability."""
    mock_trafilatura.side_effect = Exception("Failed")
    mock_newspaper.side_effect = Exception("Failed")
    
    mock_article = {
        'title': 'Test Article',
        'content': ' '.join(['word'] * 250),
        'author': '',
        'published_date': None,
        'language': '',
        'word_count': 250,
        'images': [],
        'excerpt': 'Test',
        'url': 'https://example.com/article'
    }
    mock_readability.return_value = mock_article
    
    result = blog_service.extract_article("https://example.com/article")
    
    assert result is not None
    assert result['extraction_method'] == 'readability'


@patch.object(BlogService, '_extract_with_trafilatura')
@patch.object(BlogService, '_extract_with_newspaper')
@patch.object(BlogService, '_extract_with_readability')
@patch.object(BlogService, '_extract_with_bs4')
def test_extract_article_fallback_to_bs4(
    mock_bs4, mock_readability, mock_newspaper, mock_trafilatura, blog_service
):
    """Test article extraction falls back to BeautifulSoup."""
    mock_trafilatura.side_effect = Exception("Failed")
    mock_newspaper.side_effect = Exception("Failed")
    mock_readability.side_effect = Exception("Failed")
    
    mock_article = {
        'title': 'Test Article',
        'content': ' '.join(['word'] * 200),
        'author': '',
        'published_date': None,
        'language': '',
        'word_count': 200,
        'images': [],
        'excerpt': 'Test',
        'url': 'https://example.com/article'
    }
    mock_bs4.return_value = mock_article
    
    result = blog_service.extract_article("https://example.com/article")
    
    assert result is not None
    assert result['extraction_method'] == 'beautifulsoup'


@patch.object(BlogService, '_extract_with_trafilatura')
@patch.object(BlogService, '_extract_with_newspaper')
@patch.object(BlogService, '_extract_with_readability')
@patch.object(BlogService, '_extract_with_bs4')
def test_extract_article_all_methods_fail(
    mock_bs4, mock_readability, mock_newspaper, mock_trafilatura, blog_service
):
    """Test article extraction when all methods fail."""
    mock_trafilatura.side_effect = Exception("Failed")
    mock_newspaper.side_effect = Exception("Failed")
    mock_readability.side_effect = Exception("Failed")
    mock_bs4.side_effect = Exception("Failed")
    
    with pytest.raises(ArticleExtractionError, match="All extraction methods failed"):
        blog_service.extract_article("https://example.com/article")


@patch('requests.get')
def test_extract_with_bs4(mock_get, blog_service, mock_article_html):
    """Test BeautifulSoup extraction method."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = mock_article_html.encode('utf-8')
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    result = blog_service._extract_with_bs4("https://example.com/article")
    
    assert result is not None
    assert result['title'] == 'Test Article Title'
    assert len(result['content']) > 0
    assert result['word_count'] > 0


# ========================================
# Quality Scoring Tests
# ========================================


def test_score_quality_optimal_article(blog_service):
    """Test quality scoring for optimal article."""
    article = {
        'title': 'Great Article',
        'content': ' '.join(['word'] * 1000),  # 1000 words
        'author': 'John Doe',
        'published_date': datetime.now(),
        'word_count': 1000,
    }
    
    score = blog_service._score_quality(article)
    assert score > 0.8  # Should be high quality


def test_score_quality_no_metadata(blog_service):
    """Test quality scoring for article without metadata."""
    article = {
        'title': '',
        'content': ' '.join(['word'] * 500),
        'author': '',
        'published_date': None,
        'word_count': 500,
    }
    
    score = blog_service._score_quality(article)
    assert 0.3 < score < 0.5  # Moderate quality


def test_score_quality_too_short(blog_service):
    """Test quality scoring for too-short article."""
    article = {
        'title': 'Short',
        'content': 'short text',
        'author': '',
        'published_date': None,
        'word_count': 50,
    }
    
    score = blog_service._score_quality(article)
    assert score < 0.3  # Low quality


def test_score_quality_too_long(blog_service):
    """Test quality scoring for too-long article."""
    article = {
        'title': 'Very Long Article',
        'content': ' '.join(['word'] * 60000),
        'author': 'Author',
        'published_date': datetime.now(),
        'word_count': 60000,
    }
    
    score = blog_service._score_quality(article)
    assert score < 0.8  # Penalized for excessive length


def test_score_quality_with_paragraphs(blog_service):
    """Test quality scoring bonus for paragraph structure."""
    article = {
        'title': 'Article',
        'content': 'Paragraph 1\n\nParagraph 2\n\nParagraph 3',
        'author': '',
        'published_date': None,
        'word_count': 300,
    }
    
    score = blog_service._score_quality(article)
    assert score > blog_service._score_quality({
        'title': 'Article',
        'content': 'No paragraphs just one block',
        'author': '',
        'published_date': None,
        'word_count': 300,
    })


# ========================================
# Robots.txt Tests
# ========================================


@patch('urllib.robotparser.RobotFileParser.read')
@patch('urllib.robotparser.RobotFileParser.can_fetch')
def test_check_robots_txt_allowed(mock_can_fetch, mock_read, blog_service):
    """Test robots.txt check when access is allowed."""
    mock_can_fetch.return_value = True
    
    result = blog_service.check_robots_txt("https://example.com/blog/post")
    assert result is True


@patch('urllib.robotparser.RobotFileParser.read')
@patch('urllib.robotparser.RobotFileParser.can_fetch')
def test_check_robots_txt_forbidden(mock_can_fetch, mock_read, blog_service):
    """Test robots.txt check when access is forbidden."""
    mock_can_fetch.return_value = False
    
    with pytest.raises(RobotsTxtForbiddenError, match="robots.txt forbids access"):
        blog_service.check_robots_txt("https://example.com/admin")


@patch('urllib.robotparser.RobotFileParser.read')
def test_check_robots_txt_no_file(mock_read, blog_service):
    """Test robots.txt check when file doesn't exist."""
    mock_read.side_effect = Exception("File not found")
    
    # Should allow by default when robots.txt doesn't exist
    result = blog_service.check_robots_txt("https://example.com/blog/post")
    assert result is True


@patch('urllib.robotparser.RobotFileParser.read')
@patch('urllib.robotparser.RobotFileParser.can_fetch')
def test_check_robots_txt_caching(mock_can_fetch, mock_read, blog_service):
    """Test robots.txt result caching."""
    mock_can_fetch.return_value = True
    
    # First call
    blog_service.check_robots_txt("https://example.com/blog/post1")
    assert mock_read.call_count == 1
    
    # Second call to same domain should use cache
    blog_service.check_robots_txt("https://example.com/blog/post2")
    assert mock_read.call_count == 1  # Not called again


# ========================================
# Utility Function Tests
# ========================================


def test_clean_html(blog_service):
    """Test HTML cleaning."""
    html = "<p>This is <b>bold</b> text</p>"
    cleaned = blog_service._clean_html(html)
    assert cleaned == "This is bold text"


def test_clean_html_empty(blog_service):
    """Test cleaning empty HTML."""
    assert blog_service._clean_html("") == ""
    assert blog_service._clean_html(None) == ""


def test_parse_date_valid(blog_service):
    """Test date parsing with valid date."""
    date_str = "2025-11-01T10:00:00Z"
    parsed = blog_service._parse_date(date_str)
    assert isinstance(parsed, datetime)
    assert parsed.year == 2025
    assert parsed.month == 11


def test_parse_date_invalid(blog_service):
    """Test date parsing with invalid date."""
    assert blog_service._parse_date("not-a-date") is None
    assert blog_service._parse_date(None) is None


def test_calculate_read_time(blog_service):
    """Test reading time calculation."""
    assert blog_service.calculate_read_time(200) == 1  # 1 minute
    assert blog_service.calculate_read_time(400) == 2  # 2 minutes
    assert blog_service.calculate_read_time(1000) == 5  # 5 minutes
    assert blog_service.calculate_read_time(0) == 0


def test_calculate_read_time_custom_wpm(blog_service):
    """Test reading time with custom WPM."""
    assert blog_service.calculate_read_time(300, wpm=300) == 1
    assert blog_service.calculate_read_time(600, wpm=300) == 2

