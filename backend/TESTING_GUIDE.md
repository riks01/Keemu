# Testing Guide for KeeMU Backend

This guide covers all testing strategies, how to run tests, and best practices for the KeeMU backend.

---

## 📋 Table of Contents

1. [Test Structure](#test-structure)
2. [Running Tests](#running-tests)
3. [Test Types](#test-types)
4. [Writing Tests](#writing-tests)
5. [CI/CD Integration](#cicd-integration)
6. [Troubleshooting](#troubleshooting)

---

## 📁 Test Structure

```
tests/
├── conftest.py                    # Global fixtures and configuration
├── integration/                   # Integration tests (require DB, Redis, etc.)
│   ├── __init__.py
│   ├── test_api_endpoints.py     # API endpoint integration tests
│   ├── test_rag_pipeline.py      # RAG system end-to-end tests
│   └── test_database_operations.py # Complex DB queries and transactions
├── models/                        # Model tests
│   ├── test_user_models.py
│   ├── test_content_models.py
│   └── test_rag_models.py
├── services/                      # Service layer tests
│   ├── test_blog_service.py
│   ├── test_chunker.py
│   ├── test_embedder.py
│   ├── test_rag_retrieval.py
│   └── test_rag_generation.py
└── tasks/                         # Celery task tests
    ├── test_embedding_tasks.py
    └── test_youtube_tasks.py
```

---

## 🚀 Running Tests

### Quick Start

```bash
# Run all unit tests (fastest)
pytest tests/ -v

# Run unit tests with coverage
pytest tests/ -v --cov=app --cov-report=html

# Run specific test file
pytest tests/services/test_blog_service.py -v

# Run specific test function
pytest tests/services/test_blog_service.py::test_blog_discovery -v

# Run tests matching pattern
pytest tests/ -v -k "blog"
```

### Integration Tests

Integration tests require real database and Redis connections.

```bash
# Run integration tests
pytest tests/integration/ -v --run-integration

# Run all tests including integration
pytest tests/ -v --run-integration

# Run specific integration test
pytest tests/integration/test_api_endpoints.py -v --run-integration
```

### Docker Environment

Running tests inside Docker ensures consistency:

```bash
# Run unit tests in Docker
docker compose exec api pytest tests/ -v

# Run integration tests in Docker
docker compose exec api pytest tests/integration/ -v --run-integration

# Run with coverage
docker compose exec api pytest tests/ -v --cov=app --cov-report=html

# View coverage report
open backend/htmlcov/index.html
```

---

## 🧪 Test Types

### 1. Unit Tests

**Purpose:** Test individual components in isolation

**Characteristics:**
- Fast (milliseconds)
- No external dependencies
- Mocked external services
- Database operations use test fixtures

**Location:** `tests/models/`, `tests/services/`, `tests/tasks/`

**Example:**
```python
@pytest.mark.asyncio
async def test_content_chunker():
    """Test content chunking in isolation."""
    chunker = ContentChunker()
    chunks = chunker.chunk_content("Test content", ContentSourceType.BLOG)
    assert len(chunks) > 0
```

### 2. Integration Tests

**Purpose:** Test multiple components working together

**Characteristics:**
- Slower (seconds)
- Real database connections
- Real Redis connections
- May mock external APIs (Anthropic, YouTube, etc.)

**Location:** `tests/integration/`

**Run with:** `pytest tests/integration/ -v --run-integration`

**Example:**
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_rag_pipeline(client: AsyncClient):
    """Test complete RAG pipeline from query to response."""
    response = await client.post("/api/v1/chat/...", json={...})
    assert response.status_code == 200
```

### 3. End-to-End Tests

**Purpose:** Test complete user workflows

**Characteristics:**
- Slowest (seconds to minutes)
- All systems operational
- May consume API credits
- Usually skipped in CI

**Location:** `tests/integration/` (marked with `@pytest.mark.skipif`)

**Example:**
```python
@pytest.mark.skipif(True, reason="Requires API key and consumes credits")
@pytest.mark.asyncio
async def test_full_rag_with_claude(client: AsyncClient):
    """Test RAG with actual Claude API call."""
    # This test costs money, run manually
```

---

## ✍️ Writing Tests

### Test Naming Convention

```python
# Good test names (descriptive and specific)
def test_user_registration_with_valid_email()
def test_content_chunking_with_youtube_timestamps()
def test_hybrid_retrieval_returns_top_k_results()

# Bad test names (vague)
def test_user()
def test_chunking()
def test_retrieval()
```

### Using Fixtures

```python
@pytest.mark.asyncio
async def test_with_user(test_user: User):
    """Fixtures are automatically provided by pytest."""
    assert test_user.email == "test@example.com"
```

### Async Tests

```python
# Always use pytest.mark.asyncio for async tests
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

### Mocking External Services

```python
from unittest.mock import patch, Mock

@pytest.mark.asyncio
async def test_with_mocked_api():
    """Mock external APIs to avoid real calls."""
    with patch('app.services.youtube.YouTube') as mock_youtube:
        mock_youtube.return_value.search.return_value = [...]
        result = await youtube_service.search("test")
        assert result is not None
```

### Database Tests

```python
@pytest.mark.asyncio
async def test_database_operation(db_session: AsyncSession):
    """Use db_session fixture for database tests."""
    user = User(email="test@example.com", ...)
    db_session.add(user)
    await db_session.commit()
    
    # Test your logic
    assert user.id is not None
```

---

## 🎯 Test Markers

We use pytest markers to categorize tests:

```python
@pytest.mark.asyncio        # Async test
@pytest.mark.integration    # Integration test (requires --run-integration)
@pytest.mark.slow           # Slow test (can be skipped for quick runs)
@pytest.mark.skipif(...)    # Conditionally skip test
```

### Custom Markers

Defined in `conftest.py`:

```python
markers = [
    "integration: mark test as integration test",
    "slow: mark test as slow running",
]
```

### Using Markers

```bash
# Run only integration tests
pytest tests/ -v -m integration --run-integration

# Run everything except slow tests
pytest tests/ -v -m "not slow"

# Run only async tests
pytest tests/ -v -m asyncio
```

---

## 🔧 Common Fixtures

### Available Fixtures (from `conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `db_session` | function | Clean database session for each test |
| `client` | function | AsyncClient for API testing |
| `test_user` | function | Test user with preferences |
| `inactive_user` | function | Inactive test user |
| `auth_headers` | function | JWT auth headers for test user |
| `sample_user_data` | function | Sample registration data |
| `sample_login_data` | function | Sample login credentials |

### Using Fixtures

```python
@pytest.mark.asyncio
async def test_with_authenticated_client(client: AsyncClient, auth_headers: dict):
    """Use client + auth_headers for protected endpoints."""
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
```

---

## 📊 Coverage Reports

### Generate Coverage Report

```bash
# Terminal report
pytest tests/ -v --cov=app --cov-report=term-missing

# HTML report (more detailed)
pytest tests/ -v --cov=app --cov-report=html
open htmlcov/index.html

# XML report (for CI)
pytest tests/ -v --cov=app --cov-report=xml
```

### Coverage Goals

- **Overall:** 80%+ coverage
- **Critical paths:** 90%+ coverage
  - Authentication
  - RAG pipeline
  - Database operations
- **Nice to have:** 70%+ coverage
  - Utility functions
  - Error handlers

---

## 🔄 CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: ankane/pgvector:latest
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      
      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install poetry
          poetry install
      
      - name: Run unit tests
        run: poetry run pytest tests/ -v --cov=app
      
      - name: Run integration tests
        run: poetry run pytest tests/integration/ -v --run-integration
        env:
          DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost/test_db
          REDIS_URL: redis://localhost:6379/0
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## 🐛 Troubleshooting

### Common Issues

#### 1. Database Connection Errors

**Problem:** `psycopg2.OperationalError: could not connect to server`

**Solution:**
```bash
# Ensure PostgreSQL is running
docker compose ps postgres

# Restart if needed
docker compose restart postgres

# Check DATABASE_URL in .env
echo $DATABASE_URL
```

#### 2. Redis Connection Errors

**Problem:** `redis.exceptions.ConnectionError: Error connecting to Redis`

**Solution:**
```bash
# Ensure Redis is running
docker compose ps redis

# Restart if needed
docker compose restart redis

# Check REDIS_URL in .env
echo $REDIS_URL
```

#### 3. Async Test Errors

**Problem:** `RuntimeError: Event loop is closed`

**Solution:**
```python
# Always use @pytest.mark.asyncio
@pytest.mark.asyncio
async def test_something():
    ...
```

#### 4. Fixture Not Found

**Problem:** `fixture 'xxx' not found`

**Solution:**
- Check fixture is defined in `conftest.py`
- Check fixture name spelling
- Ensure `conftest.py` is in correct location

#### 5. Import Errors

**Problem:** `ModuleNotFoundError: No module named 'app'`

**Solution:**
```bash
# Ensure you're in the backend directory
cd backend/

# Install dependencies
poetry install

# Run tests with poetry
poetry run pytest tests/ -v
```

#### 6. Integration Tests Hanging

**Problem:** Tests hang indefinitely

**Solution:**
- Check database is accessible
- Check Redis is accessible
- Look for async operations without proper timeouts
- Use `pytest -v -s` to see print statements
- Add `pytest-timeout` and set timeout:
  ```python
  @pytest.mark.timeout(30)  # 30 seconds max
  async def test_something():
      ...
  ```

---

## 🎓 Best Practices

### 1. Test Isolation

```python
# Good: Each test is independent
@pytest.mark.asyncio
async def test_create_user(db_session):
    user = User(...)
    db_session.add(user)
    await db_session.commit()
    # Test completes, session is rolled back

# Bad: Tests depend on each other
test_order = []  # Global state - avoid!
```

### 2. Descriptive Assertions

```python
# Good: Clear failure messages
assert len(results) > 0, "Expected at least one result from retrieval"
assert user.is_active is True, f"User {user.email} should be active"

# Bad: No context
assert len(results) > 0
assert user.is_active
```

### 3. Arrange-Act-Assert Pattern

```python
@pytest.mark.asyncio
async def test_something():
    # Arrange: Set up test data
    user = User(email="test@example.com")
    
    # Act: Perform the action
    result = await some_function(user)
    
    # Assert: Verify the result
    assert result is not None
```

### 4. Mock External Dependencies

```python
# Good: Mock external APIs
@patch('app.services.external_api.call')
async def test_with_mock(mock_call):
    mock_call.return_value = {"data": "test"}
    result = await my_function()
    assert result == {"data": "test"}

# Bad: Make real API calls in tests (slow, unreliable, costs money)
async def test_real_api_call():
    result = await anthropic_client.create(...)  # Don't do this!
```

### 5. Use Fixtures for Common Setup

```python
# Good: Reusable fixture
@pytest_asyncio.fixture
async def user_with_content(db_session):
    # Complex setup
    user = ...
    channel = ...
    content = ...
    return {"user": user, "channel": channel, "content": content}

async def test_1(user_with_content):
    # Reuse setup
    pass

async def test_2(user_with_content):
    # Reuse setup
    pass
```

---

## 📚 Additional Resources

- **pytest docs:** https://docs.pytest.org/
- **pytest-asyncio:** https://pytest-asyncio.readthedocs.io/
- **FastAPI testing:** https://fastapi.tiangolo.com/tutorial/testing/
- **SQLAlchemy testing:** https://docs.sqlalchemy.org/en/20/orm/session_transaction.html

---

## 🎯 Quick Reference

```bash
# Common Commands
pytest tests/ -v                                    # Run all tests
pytest tests/ -v -k "blog"                          # Run tests matching "blog"
pytest tests/ -v --run-integration                  # Run integration tests
pytest tests/ -v --cov=app --cov-report=html        # Coverage report
pytest tests/ -v -x                                 # Stop on first failure
pytest tests/ -v -s                                 # Show print statements
pytest tests/ -v --pdb                              # Drop into debugger on failure
pytest tests/ -v --lf                               # Run last failed tests
pytest tests/ -v --markers                          # Show available markers

# Docker Commands
docker compose exec api pytest tests/ -v            # Run in Docker
docker compose exec api pytest tests/ -v -s         # With output
docker compose exec api bash                        # Enter container shell
```

---

## ✅ Test Checklist

Before committing:
- [ ] All unit tests pass
- [ ] Integration tests pass (if applicable)
- [ ] Coverage is maintained or improved
- [ ] New features have tests
- [ ] Tests are well-named and documented
- [ ] No skipped tests without good reason
- [ ] Linting passes (`black`, `isort`, `flake8`)

---

## 🆘 Getting Help

If tests are failing and you're stuck:
1. Read the error message carefully
2. Check this troubleshooting guide
3. Run tests with `-v -s` for more output
4. Use `--pdb` to debug interactively
5. Check Docker logs: `docker compose logs api`
6. Ask for help with full error output

Happy Testing! 🎉

