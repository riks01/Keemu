"""
Unit tests for Reddit service.

Tests cover:
- Subreddit name extraction and validation
- Subreddit metadata fetching
- Post fetching with various filters
- Comment extraction
- Content formatting
- Error handling
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch

from praw.exceptions import RedditAPIException
from prawcore.exceptions import NotFound, Forbidden

from app.services.reddit import (
    RedditService,
    RedditAPIError,
    SubredditNotFoundError,
    RedditContentNotFoundError,
)


# ========================================
# Fixtures
# ========================================


@pytest.fixture
def mock_reddit():
    """Mock PRAW Reddit client."""
    with patch('app.services.reddit.praw.Reddit') as mock:
        yield mock


@pytest.fixture
def reddit_service(mock_reddit):
    """Create RedditService instance with mocked PRAW."""
    with patch.dict('os.environ', {
        'REDDIT_CLIENT_ID': 'test_client_id',
        'REDDIT_CLIENT_SECRET': 'test_client_secret',
        'REDDIT_USER_AGENT': 'test_user_agent',
    }):
        service = RedditService(
            client_id='test_client_id',
            client_secret='test_client_secret',
            user_agent='test_user_agent',
        )
        return service


@pytest.fixture
def mock_subreddit():
    """Mock PRAW Subreddit object."""
    subreddit = Mock()
    subreddit.display_name = 'python'
    subreddit.title = 'Python Programming'
    subreddit.public_description = 'News about Python programming'
    subreddit.subscribers = 1000000
    subreddit.created_utc = 1234567890
    subreddit.over18 = False
    subreddit.subreddit_type = 'public'
    subreddit.icon_img = 'https://example.com/icon.png'
    subreddit.banner_img = 'https://example.com/banner.png'
    return subreddit


@pytest.fixture
def mock_submission():
    """Mock PRAW Submission object."""
    submission = Mock()
    submission.id = 'abc123'
    submission.title = 'Test Post Title'
    submission.author = Mock()
    submission.author.__str__ = Mock(return_value='testuser')
    submission.subreddit = Mock()
    submission.subreddit.__str__ = Mock(return_value='python')
    submission.created_utc = 1234567890
    submission.score = 100
    submission.upvote_ratio = 0.95
    submission.num_comments = 50
    submission.permalink = '/r/python/comments/abc123/test_post/'
    submission.url = 'https://reddit.com/r/python/comments/abc123/'
    submission.is_self = True
    submission.selftext = 'This is a test post content.'
    submission.over_18 = False
    submission.spoiler = False
    submission.stickied = False
    submission.locked = False
    submission.link_flair_text = 'Discussion'
    submission.gilded = 2
    submission.total_awards_received = 5
    return submission


@pytest.fixture
def mock_comment():
    """Mock PRAW Comment object."""
    comment = Mock()
    comment.id = 'comment123'
    comment.author = Mock()
    comment.author.__str__ = Mock(return_value='commenter1')
    comment.body = 'This is a test comment.'
    comment.score = 25
    comment.created_utc = 1234567900
    comment.is_submitter = False
    comment.stickied = False
    comment.gilded = 0
    comment.total_awards_received = 1
    comment.depth = 0
    return comment


# ========================================
# Test Initialization
# ========================================


def test_reddit_service_initialization_success(mock_reddit):
    """Test successful initialization with credentials."""
    service = RedditService(
        client_id='test_id',
        client_secret='test_secret',
        user_agent='test_agent',
    )
    
    assert service.client_id == 'test_id'
    assert service.client_secret == 'test_secret'
    assert service.user_agent == 'test_agent'
    assert service._reddit is not None


def test_reddit_service_initialization_missing_credentials():
    """Test initialization fails without credentials."""
    with pytest.raises(ValueError, match='Reddit credentials are required'):
        RedditService(client_id=None, client_secret=None, user_agent=None)


# ========================================
# Test Subreddit Name Extraction
# ========================================


def test_extract_subreddit_name_direct(reddit_service):
    """Test extracting subreddit name from direct name."""
    assert reddit_service.extract_subreddit_name('python') == 'python'
    assert reddit_service.extract_subreddit_name('learnpython') == 'learnpython'


def test_extract_subreddit_name_with_r_prefix(reddit_service):
    """Test extracting subreddit name with r/ prefix."""
    assert reddit_service.extract_subreddit_name('r/python') == 'python'
    assert reddit_service.extract_subreddit_name('/r/python') == 'python'


def test_extract_subreddit_name_from_url(reddit_service):
    """Test extracting subreddit name from URL."""
    assert reddit_service.extract_subreddit_name(
        'https://reddit.com/r/python'
    ) == 'python'
    assert reddit_service.extract_subreddit_name(
        'https://www.reddit.com/r/python/'
    ) == 'python'
    assert reddit_service.extract_subreddit_name(
        'http://reddit.com/r/learnpython/hot'
    ) == 'learnpython'


def test_extract_subreddit_name_invalid_format(reddit_service):
    """Test error on invalid subreddit format."""
    with pytest.raises(ValueError, match='Invalid subreddit format'):
        reddit_service.extract_subreddit_name('py')  # Too short
    
    with pytest.raises(ValueError, match='Invalid subreddit format'):
        reddit_service.extract_subreddit_name('this_is_way_too_long_name')  # Too long
    
    with pytest.raises(ValueError, match='Invalid subreddit format'):
        reddit_service.extract_subreddit_name('invalid-name')  # Has dash


def test_extract_subreddit_name_invalid_url(reddit_service):
    """Test error on invalid URL."""
    with pytest.raises(ValueError, match='Could not extract subreddit name from URL'):
        reddit_service.extract_subreddit_name('https://reddit.com/invalid/path')


# ========================================
# Test Subreddit Validation
# ========================================


def test_validate_subreddit_url_valid(reddit_service):
    """Test validating valid subreddit URLs."""
    is_valid, name = reddit_service.validate_subreddit_url('r/python')
    assert is_valid is True
    assert name == 'python'
    
    is_valid, name = reddit_service.validate_subreddit_url('https://reddit.com/r/python')
    assert is_valid is True
    assert name == 'python'


def test_validate_subreddit_url_invalid(reddit_service):
    """Test validating invalid subreddit URLs."""
    is_valid, name = reddit_service.validate_subreddit_url('invalid-format')
    assert is_valid is False
    assert name is None


# ========================================
# Test Get Subreddit By Name
# ========================================


def test_get_subreddit_by_name_success(reddit_service, mock_subreddit):
    """Test successfully fetching subreddit metadata."""
    reddit_service._reddit.subreddit = Mock(return_value=mock_subreddit)
    
    result = reddit_service.get_subreddit_by_name('python')
    
    assert result['name'] == 'python'
    assert result['title'] == 'Python Programming'
    assert result['description'] == 'News about Python programming'
    assert result['subscribers'] == 1000000
    assert result['over18'] is False
    assert result['public'] is True
    assert 'url' in result


def test_get_subreddit_by_name_not_found(reddit_service):
    """Test error when subreddit not found."""
    reddit_service._reddit.subreddit = Mock(side_effect=NotFound(Mock()))
    
    with pytest.raises(SubredditNotFoundError, match='Subreddit not found'):
        reddit_service.get_subreddit_by_name('nonexistent')


def test_get_subreddit_by_name_private(reddit_service):
    """Test error when subreddit is private."""
    reddit_service._reddit.subreddit = Mock(side_effect=Forbidden(Mock()))
    
    with pytest.raises(SubredditNotFoundError, match='private, banned, or quarantined'):
        reddit_service.get_subreddit_by_name('private_sub')


def test_get_subreddit_by_name_api_error(reddit_service):
    """Test error on Reddit API exception."""
    reddit_service._reddit.subreddit = Mock(
        side_effect=RedditAPIException(Mock())
    )
    
    with pytest.raises(RedditAPIError, match='Reddit API error'):
        reddit_service.get_subreddit_by_name('python')


# ========================================
# Test Get Subreddit Posts
# ========================================


def test_get_subreddit_posts_hot(reddit_service, mock_submission):
    """Test fetching hot posts from subreddit."""
    mock_subreddit = Mock()
    mock_subreddit.hot = Mock(return_value=[mock_submission])
    reddit_service._reddit.subreddit = Mock(return_value=mock_subreddit)
    
    posts = reddit_service.get_subreddit_posts('python', limit=10, sort='hot')
    
    assert len(posts) == 1
    assert posts[0]['post_id'] == 'abc123'
    assert posts[0]['title'] == 'Test Post Title'
    assert posts[0]['score'] == 100
    mock_subreddit.hot.assert_called_once_with(limit=10)


def test_get_subreddit_posts_top(reddit_service, mock_submission):
    """Test fetching top posts with time filter."""
    mock_subreddit = Mock()
    mock_subreddit.top = Mock(return_value=[mock_submission])
    reddit_service._reddit.subreddit = Mock(return_value=mock_subreddit)
    
    posts = reddit_service.get_subreddit_posts(
        'python', limit=50, time_filter='week', sort='top'
    )
    
    assert len(posts) == 1
    mock_subreddit.top.assert_called_once_with(time_filter='week', limit=50)


def test_get_subreddit_posts_new(reddit_service, mock_submission):
    """Test fetching new posts."""
    mock_subreddit = Mock()
    mock_subreddit.new = Mock(return_value=[mock_submission])
    reddit_service._reddit.subreddit = Mock(return_value=mock_subreddit)
    
    posts = reddit_service.get_subreddit_posts('python', limit=25, sort='new')
    
    assert len(posts) == 1
    mock_subreddit.new.assert_called_once_with(limit=25)


def test_get_subreddit_posts_invalid_sort(reddit_service):
    """Test error on invalid sort method."""
    mock_subreddit = Mock()
    reddit_service._reddit.subreddit = Mock(return_value=mock_subreddit)
    
    with pytest.raises(ValueError, match='Invalid sort method'):
        reddit_service.get_subreddit_posts('python', sort='invalid')


def test_get_subreddit_posts_not_found(reddit_service):
    """Test error when subreddit not found."""
    reddit_service._reddit.subreddit = Mock(side_effect=NotFound(Mock()))
    
    with pytest.raises(SubredditNotFoundError):
        reddit_service.get_subreddit_posts('nonexistent')


# ========================================
# Test Get Post Details
# ========================================


def test_get_post_details_success(reddit_service, mock_submission):
    """Test successfully fetching post details."""
    reddit_service._reddit.submission = Mock(return_value=mock_submission)
    
    post = reddit_service.get_post_details('abc123')
    
    assert post['post_id'] == 'abc123'
    assert post['title'] == 'Test Post Title'
    assert post['score'] == 100
    assert post['num_comments'] == 50


def test_get_post_details_not_found(reddit_service):
    """Test error when post not found."""
    reddit_service._reddit.submission = Mock(side_effect=NotFound(Mock()))
    
    with pytest.raises(RedditContentNotFoundError, match='Post not found'):
        reddit_service.get_post_details('nonexistent')


# ========================================
# Test Get Post Comments
# ========================================


def test_get_post_comments_success(reddit_service, mock_submission, mock_comment):
    """Test successfully fetching post comments."""
    # Setup mock comments
    mock_submission.comments = Mock()
    mock_submission.comments.replace_more = Mock()
    mock_submission.comments.__getitem__ = Mock(return_value=[mock_comment])
    
    reddit_service._reddit.submission = Mock(return_value=mock_submission)
    
    comments = reddit_service.get_post_comments('abc123', comment_limit=20)
    
    assert len(comments) == 1
    assert comments[0]['comment_id'] == 'comment123'
    assert comments[0]['body'] == 'This is a test comment.'
    assert comments[0]['score'] == 25


def test_get_post_comments_not_found(reddit_service):
    """Test error when post not found for comments."""
    reddit_service._reddit.submission = Mock(side_effect=NotFound(Mock()))
    
    with pytest.raises(RedditContentNotFoundError):
        reddit_service.get_post_comments('nonexistent')


# ========================================
# Test Content Formatting
# ========================================


def test_format_post_content_self_post(reddit_service):
    """Test formatting self post content."""
    post = {
        'title': 'Test Title',
        'subreddit': 'python',
        'author': 'testuser',
        'created_utc': datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        'score': 100,
        'num_comments': 50,
        'link_flair_text': 'Discussion',
        'is_self': True,
        'selftext': 'This is the post content.',
        'url': '',
    }
    
    formatted = reddit_service.format_post_content(post)
    
    assert 'Title: Test Title' in formatted
    assert 'Subreddit: r/python' in formatted
    assert 'Author: u/testuser' in formatted
    assert 'Score: 100' in formatted
    assert 'Flair: Discussion' in formatted
    assert 'This is the post content.' in formatted


def test_format_post_content_link_post(reddit_service):
    """Test formatting link post content."""
    post = {
        'title': 'Cool Article',
        'subreddit': 'programming',
        'author': 'poster',
        'created_utc': datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        'score': 200,
        'num_comments': 75,
        'link_flair_text': '',
        'is_self': False,
        'selftext': '',
        'url': 'https://example.com/article',
        'post_hint': 'link',
    }
    
    formatted = reddit_service.format_post_content(post)
    
    assert 'Title: Cool Article' in formatted
    assert 'Link: https://example.com/article' in formatted
    assert 'Type: link' in formatted


# ========================================
# Test Comment Parsing
# ========================================


def test_parse_comment_tree(reddit_service):
    """Test parsing and filtering comment tree."""
    comments = [
        {'comment_id': '1', 'score': 100, 'depth': 0},
        {'comment_id': '2', 'score': 50, 'depth': 1},
        {'comment_id': '3', 'score': 75, 'depth': 0},
        {'comment_id': '4', 'score': 25, 'depth': 2},
        {'comment_id': '5', 'score': 10, 'depth': 3},
    ]
    
    # Filter to depth 1
    filtered = reddit_service.parse_comment_tree(comments, max_depth=1)
    
    assert len(filtered) == 3  # Only depth 0 and 1
    assert filtered[0]['comment_id'] == '1'  # Highest score first
    assert filtered[1]['comment_id'] == '3'
    assert filtered[2]['comment_id'] == '2'


# ========================================
# Test Engagement Scoring
# ========================================


def test_calculate_engagement_score(reddit_service):
    """Test engagement score calculation."""
    post = {
        'score': 100,
        'num_comments': 50,
        'total_awards_received': 10,
    }
    
    score = reddit_service.calculate_engagement_score(post)
    
    # (100 * 0.6) + (50 * 0.3) + (10 * 0.1) = 60 + 15 + 1 = 76
    assert score == 76.0


def test_calculate_engagement_score_missing_fields(reddit_service):
    """Test engagement score with missing fields."""
    post = {'score': 50}  # Missing comments and awards
    
    score = reddit_service.calculate_engagement_score(post)
    
    # (50 * 0.6) + (0 * 0.3) + (0 * 0.1) = 30
    assert score == 30.0


# ========================================
# Test Comment Formatting
# ========================================


def test_format_comments_for_storage(reddit_service):
    """Test formatting comments for storage."""
    comments = [
        {
            'comment_id': '1',
            'author': 'user1',
            'body': 'Great post!',
            'score': 50,
        },
        {
            'comment_id': '2',
            'author': 'user2',
            'body': 'I agree.',
            'score': 25,
        },
    ]
    
    formatted = reddit_service.format_comments_for_storage(comments)
    
    assert '[Comment 1 - Score: 50]' in formatted
    assert 'Author: u/user1' in formatted
    assert 'Great post!' in formatted
    assert '[Comment 2 - Score: 25]' in formatted
    assert 'I agree.' in formatted


def test_format_comments_for_storage_empty(reddit_service):
    """Test formatting empty comment list."""
    formatted = reddit_service.format_comments_for_storage([])
    
    assert formatted == '[No comments]'

