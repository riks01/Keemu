"""
Blog/RSS service for discovering, parsing, and extracting content from blogs and RSS feeds.

This module provides a comprehensive service for blog/RSS integration, featuring:
- Automatic RSS feed discovery using rss-digger
- Fast RSS/Atom feed parsing using fastfeedparser
- Multi-stage article extraction (trafilatura, newspaper4k, readability-lxml, BeautifulSoup)
- Quality scoring to select best extraction method
- Robots.txt compliance
- Politeness delays and conditional GET support
"""

import re
import logging
import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import time

import requests
import trafilatura
from newspaper import Article as NewspaperArticle
from readability import Document
from bs4 import BeautifulSoup
import fastfeedparser
import lxml.html

from app.core.config import settings

logger = logging.getLogger(__name__)


# ========================================
# Custom Exceptions
# ========================================


class BlogServiceError(Exception):
    """Base exception for blog service errors."""
    pass


class FeedNotFoundError(BlogServiceError):
    """Raised when RSS feed cannot be found or accessed."""
    pass


class ArticleExtractionError(BlogServiceError):
    """Raised when article extraction fails for all methods."""
    pass


class RobotsTxtForbiddenError(BlogServiceError):
    """Raised when robots.txt forbids scraping."""
    pass


# ========================================
# Blog Service
# ========================================


class BlogService:
    """
    Service for interacting with blogs and RSS feeds.
    
    Provides methods for:
    - RSS feed discovery from blog URLs
    - RSS/Atom feed parsing
    - Multi-stage article extraction with quality scoring
    - Robots.txt compliance
    - Content cleaning and normalization
    
    Example:
        >>> blog_service = BlogService()
        >>> feed_url = await blog_service.discover_feed("https://example.com/blog")
        >>> articles = await blog_service.parse_feed(feed_url)
        >>> content = await blog_service.extract_article(articles[0]['url'])
    """

    USER_AGENT = "KeeMU-Bot/1.0 (Content Intelligence Assistant; +https://keemu.app/bot)"
    REQUEST_TIMEOUT = 10  # seconds
    MIN_WORD_COUNT = 100
    MAX_WORD_COUNT = 50000
    OPTIMAL_MIN_WORDS = 200
    OPTIMAL_MAX_WORDS = 10000

    def __init__(self):
        """Initialize Blog service."""
        self._robots_cache: Dict[str, Tuple[RobotFileParser, float]] = {}
        self._robots_cache_ttl = 3600  # 1 hour
        logger.info("Blog service initialized successfully")
    
    # ========================================
    # RSS Feed Discovery
    # ========================================
    
    def discover_feed(self, blog_url: str) -> Optional[str]:
        """
        Discover RSS/Atom feed URL from a blog homepage.
        
        Uses multiple strategies:
        1. Look for <link rel="alternate"> tags in HTML
        2. Check common feed locations (/feed, /rss, /atom.xml, etc.)
        3. Parse HTML for feed links
        
        Args:
            blog_url: Blog homepage URL
            
        Returns:
            RSS feed URL if found, None otherwise
            
        Raises:
            BlogServiceError: If URL cannot be accessed
        """
        try:
            blog_url = self._normalize_url(blog_url)
            logger.info(f"Discovering RSS feed for: {blog_url}")
            
            # Try to fetch the page
            response = requests.get(
                blog_url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=self.REQUEST_TIMEOUT,
                allow_redirects=True
            )
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Strategy 1: Look for <link rel="alternate"> tags
            feed_links = soup.find_all('link', attrs={'rel': 'alternate'})
            for link in feed_links:
                link_type = link.get('type', '').lower()
                if 'rss' in link_type or 'atom' in link_type or 'xml' in link_type:
                    feed_url = link.get('href')
                    if feed_url:
                        feed_url = urljoin(blog_url, feed_url)
                        if self._validate_feed_url(feed_url):
                            logger.info(f"Found feed via <link> tag: {feed_url}")
                            return feed_url
            
            # Strategy 2: Check common feed locations
            parsed = urlparse(blog_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            
            common_paths = [
                '/feed',
                '/feed/',
                '/rss',
                '/rss/',
                '/atom.xml',
                '/feed.xml',
                '/rss.xml',
                '/index.xml',
                '/blog/feed',
                '/blog/rss',
            ]
            
            for path in common_paths:
                feed_url = urljoin(base_url, path)
                if self._validate_feed_url(feed_url):
                    logger.info(f"Found feed at common location: {feed_url}")
                    return feed_url
            
            # Strategy 3: Look for links in HTML that might be feeds
            for a_tag in soup.find_all('a', href=True):
                href = a_tag.get('href', '').lower()
                if any(keyword in href for keyword in ['feed', 'rss', 'atom', '.xml']):
                    feed_url = urljoin(blog_url, a_tag['href'])
                    if self._validate_feed_url(feed_url):
                        logger.info(f"Found feed via HTML link: {feed_url}")
                        return feed_url
            
            logger.warning(f"No RSS feed found for: {blog_url}")
            return None
            
        except requests.RequestException as e:
            logger.error(f"Error fetching blog URL {blog_url}: {e}")
            raise BlogServiceError(f"Failed to fetch blog URL: {e}")
        except Exception as e:
            logger.error(f"Error discovering feed for {blog_url}: {e}")
            raise BlogServiceError(f"Feed discovery failed: {e}")
    
    def _validate_feed_url(self, feed_url: str) -> bool:
        """
        Validate that a URL is actually an RSS/Atom feed.
        
        Args:
            feed_url: URL to validate
            
        Returns:
            True if valid feed, False otherwise
        """
        try:
            response = requests.head(
                feed_url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=5,
                allow_redirects=True
            )
            
            # Check if successful
            if response.status_code != 200:
                return False
            
            # Check content type
            content_type = response.headers.get('Content-Type', '').lower()
            valid_types = ['xml', 'rss', 'atom', 'feed']
            if any(vtype in content_type for vtype in valid_types):
                return True
            
            # If content-type is not conclusive, try to fetch and parse a bit
            response = requests.get(
                feed_url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=5,
                stream=True
            )
            
            # Read first 1KB to check if it's XML
            chunk = response.raw.read(1024).decode('utf-8', errors='ignore')
            return '<?xml' in chunk or '<rss' in chunk or '<feed' in chunk
            
        except Exception as e:
            logger.debug(f"Failed to validate feed URL {feed_url}: {e}")
            return False
    
    # ========================================
    # Feed Parsing
    # ========================================
    
    def parse_feed(
        self,
        feed_url: str,
        max_entries: int = 50,
        since_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Parse RSS/Atom feed and extract article metadata.
        
        Args:
            feed_url: URL of RSS/Atom feed
            max_entries: Maximum number of entries to return
            since_date: Only return entries published after this date
            
        Returns:
            List of article metadata dictionaries with keys:
            - title: Article title
            - url: Article URL
            - published: Publication date (datetime)
            - author: Author name (if available)
            - summary: Article summary/excerpt
            - guid: Unique identifier
            
        Raises:
            FeedNotFoundError: If feed cannot be fetched or parsed
        """
        try:
            logger.info(f"Parsing feed: {feed_url}")
            
            # Fetch feed content
            response = requests.get(
                feed_url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=self.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            # Parse with fastfeedparser
            feed = fastfeedparser.parse(response.content)
            
            if not feed or not hasattr(feed, 'entries'):
                raise FeedNotFoundError(f"Invalid feed format: {feed_url}")
            
            articles = []
            for entry in feed.entries[:max_entries]:
                try:
                    # Extract publication date
                    published = None
                    # Try parsed date tuples first
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        try:
                            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        except (TypeError, ValueError):
                            pass
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        try:
                            published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                        except (TypeError, ValueError):
                            pass
                    
                    # Fallback to parsing date strings
                    if not published:
                        date_str = entry.get('published') or entry.get('updated')
                        if date_str:
                            published = self._parse_date(date_str)
                    
                    # Skip if before since_date
                    if since_date and published and published < since_date:
                        continue
                    
                    # Extract article data
                    article = {
                        'title': entry.get('title', '').strip(),
                        'url': entry.get('link', '').strip(),
                        'published': published,
                        'author': entry.get('author', '').strip(),
                        'summary': self._clean_html(entry.get('summary', '')),
                        'guid': entry.get('id', entry.get('link', '')),
                    }
                    
                    # Only add if we have at minimum title and URL
                    if article['title'] and article['url']:
                        articles.append(article)
                
                except Exception as e:
                    logger.warning(f"Error parsing feed entry: {e}")
                    continue
            
            logger.info(f"Parsed {len(articles)} articles from feed")
            return articles
            
        except requests.RequestException as e:
            logger.error(f"Error fetching feed {feed_url}: {e}")
            raise FeedNotFoundError(f"Failed to fetch feed: {e}")
        except ValueError as e:
            # fastfeedparser raises ValueError for invalid XML
            logger.error(f"Error parsing feed {feed_url}: {e}")
            raise FeedNotFoundError(f"Invalid feed format: {feed_url}")
        except Exception as e:
            logger.error(f"Error parsing feed {feed_url}: {e}")
            raise FeedNotFoundError(f"Failed to parse feed: {e}")
    
    # ========================================
    # Article Extraction (Multi-Stage)
    # ========================================
    
    def extract_article(self, url: str) -> Optional[Dict]:
        """
        Extract article content using multi-stage extraction pipeline.
        
        Tries multiple extraction methods and returns the best result based on quality scoring:
        1. trafilatura (primary - best for articles)
        2. newspaper4k (fallback 1 - general purpose)
        3. readability-lxml (fallback 2 - Mozilla algorithm)
        4. BeautifulSoup (fallback 3 - manual extraction)
        
        Args:
            url: Article URL
            
        Returns:
            Dictionary with article data:
            - title: Article title
            - content: Full article text (cleaned)
            - author: Author name (if available)
            - published_date: Publication date (if available)
            - language: Detected language
            - word_count: Number of words
            - images: List of image URLs
            - excerpt: Short summary
            - extraction_method: Method used for extraction
            - quality_score: Quality score (0-1)
            
        Raises:
            ArticleExtractionError: If all extraction methods fail
        """
        try:
            logger.info(f"Extracting article: {url}")
            
            results = []
            
            # Method 1: trafilatura
            try:
                result = self._extract_with_trafilatura(url)
                if result:
                    quality = self._score_quality(result)
                    results.append({
                        "method": "trafilatura",
                        "quality": quality,
                        "data": result
                    })
                    logger.debug(f"trafilatura extraction quality: {quality:.2f}")
            except Exception as e:
                logger.debug(f"trafilatura extraction failed: {e}")
            
            # Method 2: newspaper4k
            try:
                result = self._extract_with_newspaper(url)
                if result:
                    quality = self._score_quality(result)
                    results.append({
                        "method": "newspaper4k",
                        "quality": quality,
                        "data": result
                    })
                    logger.debug(f"newspaper4k extraction quality: {quality:.2f}")
            except Exception as e:
                logger.debug(f"newspaper4k extraction failed: {e}")
            
            # Method 3: readability-lxml
            try:
                result = self._extract_with_readability(url)
                if result:
                    quality = self._score_quality(result)
                    results.append({
                        "method": "readability",
                        "quality": quality,
                        "data": result
                    })
                    logger.debug(f"readability extraction quality: {quality:.2f}")
            except Exception as e:
                logger.debug(f"readability extraction failed: {e}")
            
            # Method 4: BeautifulSoup
            try:
                result = self._extract_with_bs4(url)
                if result:
                    quality = self._score_quality(result)
                    results.append({
                        "method": "beautifulsoup",
                        "quality": quality,
                        "data": result
                    })
                    logger.debug(f"BeautifulSoup extraction quality: {quality:.2f}")
            except Exception as e:
                logger.debug(f"BeautifulSoup extraction failed: {e}")
            
            # Select best result
            if not results:
                raise ArticleExtractionError(f"All extraction methods failed for: {url}")
            
            best = max(results, key=lambda x: x["quality"])
            best_data = best["data"]
            best_data['extraction_method'] = best["method"]
            best_data['quality_score'] = best["quality"]
            
            logger.info(
                f"Best extraction method: {best['method']} "
                f"(quality: {best['quality']:.2f}, words: {best_data.get('word_count', 0)})"
            )
            
            return best_data
            
        except ArticleExtractionError:
            raise
        except Exception as e:
            logger.error(f"Error extracting article {url}: {e}")
            raise ArticleExtractionError(f"Article extraction failed: {e}")
    
    def _extract_with_trafilatura(self, url: str) -> Optional[Dict]:
        """Extract article using trafilatura."""
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        
        # Extract with metadata
        result = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            output_format='json',
            with_metadata=True
        )
        
        if not result:
            return None
        
        import json
        data = json.loads(result)
        
        return {
            'title': data.get('title', ''),
            'content': data.get('text', ''),
            'author': data.get('author', ''),
            'published_date': self._parse_date(data.get('date')),
            'language': data.get('language', ''),
            'word_count': len(data.get('text', '').split()),
            'images': data.get('images', []),
            'excerpt': data.get('excerpt', '')[:500],
            'url': url,
        }
    
    def _extract_with_newspaper(self, url: str) -> Optional[Dict]:
        """Extract article using newspaper4k."""
        article = NewspaperArticle(url)
        article.download()
        article.parse()
        
        if not article.text:
            return None
        
        return {
            'title': article.title,
            'content': article.text,
            'author': ', '.join(article.authors) if article.authors else '',
            'published_date': article.publish_date,
            'language': article.meta_lang or '',
            'word_count': len(article.text.split()),
            'images': article.images if hasattr(article, 'images') else [],
            'excerpt': article.text[:500] if article.text else '',
            'url': url,
        }
    
    def _extract_with_readability(self, url: str) -> Optional[Dict]:
        """Extract article using readability-lxml."""
        response = requests.get(
            url,
            headers={"User-Agent": self.USER_AGENT},
            timeout=self.REQUEST_TIMEOUT
        )
        response.raise_for_status()
        
        doc = Document(response.content)
        title = doc.title()
        html_content = doc.summary()
        
        if not html_content:
            return None
        
        # Extract text from HTML
        soup = BeautifulSoup(html_content, 'lxml')
        text = soup.get_text(separator='\n', strip=True)
        
        if not text:
            return None
        
        return {
            'title': title,
            'content': text,
            'author': '',
            'published_date': None,
            'language': '',
            'word_count': len(text.split()),
            'images': [],
            'excerpt': text[:500],
            'url': url,
        }
    
    def _extract_with_bs4(self, url: str) -> Optional[Dict]:
        """Extract article using BeautifulSoup (last resort)."""
        response = requests.get(
            url,
            headers={"User-Agent": self.USER_AGENT},
            timeout=self.REQUEST_TIMEOUT
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'lxml')
        
        # Try to find title
        title = ''
        if soup.title:
            title = soup.title.string or ''
        elif soup.find('h1'):
            title = soup.find('h1').get_text(strip=True)
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
            script.decompose()
        
        # Try to find main content
        content = ''
        # Look for article tag first
        article_tag = soup.find('article')
        if article_tag:
            content = article_tag.get_text(separator='\n', strip=True)
        # Look for main tag
        elif soup.find('main'):
            content = soup.find('main').get_text(separator='\n', strip=True)
        # Look for div with common content class names
        else:
            for class_name in ['content', 'post-content', 'entry-content', 'article-content']:
                content_div = soup.find('div', class_=re.compile(class_name, re.I))
                if content_div:
                    content = content_div.get_text(separator='\n', strip=True)
                    break
        
        if not content:
            # Last resort: get all paragraph text
            paragraphs = soup.find_all('p')
            content = '\n\n'.join(p.get_text(strip=True) for p in paragraphs)
        
        if not content:
            return None
        
        return {
            'title': title,
            'content': content,
            'author': '',
            'published_date': None,
            'language': '',
            'word_count': len(content.split()),
            'images': [],
            'excerpt': content[:500],
            'url': url,
        }
    
    def _score_quality(self, article_data: Dict) -> float:
        """
        Score article extraction quality (0-1).
        
        Factors:
        - Word count (prefer 200-10,000 words)
        - Has title
        - Has author/date metadata
        - Content structure (paragraphs)
        """
        score = 0.0
        
        # Word count (40% weight)
        word_count = article_data.get('word_count', 0)
        if word_count < self.MIN_WORD_COUNT:
            score += 0.0
        elif word_count < self.OPTIMAL_MIN_WORDS:
            score += 0.2 * (word_count / self.OPTIMAL_MIN_WORDS)
        elif word_count <= self.OPTIMAL_MAX_WORDS:
            score += 0.4
        elif word_count <= self.MAX_WORD_COUNT:
            ratio = (self.MAX_WORD_COUNT - word_count) / (self.MAX_WORD_COUNT - self.OPTIMAL_MAX_WORDS)
            score += 0.4 * ratio
        
        # Has title (20% weight)
        if article_data.get('title'):
            score += 0.2
        
        # Has author (15% weight)
        if article_data.get('author'):
            score += 0.15
        
        # Has publication date (15% weight)
        if article_data.get('published_date'):
            score += 0.15
        
        # Content quality - check for paragraph structure (10% weight)
        content = article_data.get('content', '')
        if '\n\n' in content or '\n' in content:
            score += 0.1
        
        return min(score, 1.0)
    
    # ========================================
    # Robots.txt Compliance
    # ========================================
    
    def check_robots_txt(self, url: str) -> bool:
        """
        Check if URL is allowed by robots.txt.
        
        Args:
            url: URL to check
            
        Returns:
            True if allowed, False if forbidden
            
        Raises:
            RobotsTxtForbiddenError: If explicitly forbidden by robots.txt
        """
        try:
            parsed = urlparse(url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
            
            # Check cache
            now = time.time()
            if domain in self._robots_cache:
                robot_parser, cached_time = self._robots_cache[domain]
                if now - cached_time < self._robots_cache_ttl:
                    can_fetch = robot_parser.can_fetch(self.USER_AGENT, url)
                    if not can_fetch:
                        raise RobotsTxtForbiddenError(f"robots.txt forbids access to: {url}")
                    return can_fetch
            
            # Fetch and parse robots.txt
            robots_url = urljoin(domain, '/robots.txt')
            robot_parser = RobotFileParser()
            robot_parser.set_url(robots_url)
            
            try:
                robot_parser.read()
                self._robots_cache[domain] = (robot_parser, now)
            except Exception as e:
                logger.debug(f"Could not read robots.txt for {domain}: {e}")
                # If robots.txt doesn't exist or can't be read, allow by default
                return True
            
            can_fetch = robot_parser.can_fetch(self.USER_AGENT, url)
            if not can_fetch:
                raise RobotsTxtForbiddenError(f"robots.txt forbids access to: {url}")
            
            return can_fetch
            
        except RobotsTxtForbiddenError:
            raise
        except Exception as e:
            logger.warning(f"Error checking robots.txt for {url}: {e}")
            # On error, allow by default (be lenient)
            return True
    
    # ========================================
    # URL Validation and Utilities
    # ========================================
    
    def validate_blog_url(self, url: str) -> bool:
        """
        Validate blog URL format.
        
        Args:
            url: URL to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            url = url.strip()
            if not url:
                return False
            
            # Must start with http:// or https://
            if not url.startswith(('http://', 'https://')):
                return False
            
            parsed = urlparse(url)
            
            # Must have a valid domain
            if not parsed.netloc or '.' not in parsed.netloc:
                return False
            
            return True
            
        except Exception:
            return False
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL (add scheme, remove trailing slash, etc.)."""
        url = url.strip()
        
        # Add https:// if no scheme
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Remove trailing slash (but keep it for domain-only URLs)
        parsed = urlparse(url)
        if url.endswith('/') and (parsed.path not in ('', '/')):
            url = url.rstrip('/')
        elif url.endswith('/') and parsed.path == '/':
            # Remove trailing slash for domain-only URLs
            url = url.rstrip('/')
        
        return url
    
    def _clean_html(self, html_text: str) -> str:
        """Clean HTML tags from text."""
        if not html_text:
            return ''
        
        soup = BeautifulSoup(html_text, 'lxml')
        return soup.get_text(separator=' ', strip=True)
    
    def _parse_date(self, date_string: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime object."""
        if not date_string:
            return None
        
        try:
            from dateutil import parser
            return parser.parse(date_string)
        except Exception:
            return None
    
    def get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc
    
    def calculate_read_time(self, word_count: int, wpm: int = 200) -> int:
        """
        Calculate reading time in minutes.
        
        Args:
            word_count: Number of words
            wpm: Words per minute (default: 200)
            
        Returns:
            Estimated reading time in minutes
        """
        if word_count <= 0:
            return 0
        return max(1, round(word_count / wpm))

