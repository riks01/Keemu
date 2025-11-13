# KeeMU Backend - Content Intelligence Assistant

Production-ready backend for KeeMU, an AI-powered content aggregation and intelligence platform.

## 🚀 Features

- **Content Collection**: Automated monitoring of YouTube channels, Reddit communities, and blogs
- **Intelligent Processing**: RAG-powered chat interface for exploring content
- **Smart Summarization**: AI-generated summaries using Claude Haiku 3.5
- **Local Embeddings**: Cost-effective embeddings using google/embeddinggemma-300m
- **Scalable Architecture**: Async processing with Celery, Redis, and PostgreSQL
- **Production Ready**: Docker-based deployment with health checks and monitoring

## 🏗️ Architecture

```
├── FastAPI Application (REST API)
├── PostgreSQL + pgvector (Data & Vector Storage)
├── Redis (Cache & Message Broker)
├── Celery Workers (Background Processing)
├── Celery Beat (Scheduled Tasks)
└── Flower (Task Monitoring)
```

## 📋 Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)
- API Keys (see [API_SETUP_GUIDE.md](../API_SETUP_GUIDE.md))

## 🛠️ Quick Start

### 1. Clone and Setup Environment

```bash
cd backend

# Copy environment template
cp env.template .env

# Edit .env with your API keys
nano .env
```

### 2. Start with Docker Compose

```bash
# Build and start all services
docker-compose up --build

# Or run in detached mode
docker-compose up -d --build
```

### 3. Verify Services

- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Flower (Celery Monitor)**: http://localhost:5555
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

### 4. Check Health

```bash
curl http://localhost:8000/health
```

## 💻 Local Development (without Docker)

### Install Dependencies

```bash
# Install Poetry (if not installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Activate virtual environment
poetry shell
```

### Setup Database

```bash
# Start only database services
docker-compose up postgres redis -d

# Run migrations
alembic upgrade head
```

### Run Application

```bash
# Start API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start Celery worker (in another terminal)
celery -A app.workers.celery_app worker --loglevel=info

# Start Celery beat (in another terminal)
celery -A app.workers.celery_app beat --loglevel=info
```

## 📁 Project Structure

```
backend/
├── app/
│   ├── api/                 # API endpoints
│   │   └── v1/
│   │       ├── auth.py      # Authentication routes
│   │       ├── sources.py   # Content source management
│   │       ├── summaries.py # Summary endpoints
│   │       └── chat.py      # RAG chat interface
│   ├── core/                # Core configuration
│   │   ├── config.py        # Settings management
│   │   ├── logging.py       # Structured logging
│   │   └── security.py      # JWT & OAuth
│   ├── models/              # SQLAlchemy models
│   │   ├── user.py
│   │   ├── content.py
│   │   └── conversation.py
│   ├── schemas/             # Pydantic schemas
│   │   ├── user.py
│   │   ├── content.py
│   │   └── chat.py
│   ├── services/            # Business logic
│   │   ├── auth/            # Authentication service
│   │   ├── collectors/      # Content collectors
│   │   │   ├── youtube.py
│   │   │   ├── reddit.py
│   │   │   └── blog.py
│   │   ├── processors/      # Content processing
│   │   │   ├── chunker.py
│   │   │   ├── embedder.py
│   │   │   └── normalizer.py
│   │   ├── rag/             # RAG system
│   │   │   ├── retriever.py
│   │   │   ├── reranker.py
│   │   │   └── generator.py
│   │   └── summaries/       # Summary generation
│   ├── workers/             # Celery tasks
│   │   ├── celery_app.py
│   │   ├── collection.py
│   │   ├── processing.py
│   │   └── summarization.py
│   ├── db/                  # Database utilities
│   │   ├── session.py
│   │   └── base.py
│   ├── utils/               # Helper functions
│   └── main.py              # FastAPI application
├── alembic/                 # Database migrations
├── tests/                   # Test suite
├── docker/                  # Docker configs
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml           # Dependencies
└── README.md
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_auth.py

# Run with verbose output
pytest -v
```

## 📊 Monitoring

### Celery Tasks

Access Flower dashboard: http://localhost:5555

### Logs

```bash
# View API logs
docker-compose logs -f api

# View Celery worker logs
docker-compose logs -f celery_worker

# View all logs
docker-compose logs -f
```

### Database

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U keemu_user -d keemu_db

# Check vector extension
docker-compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

## 🔧 Configuration

All configuration is managed through environment variables (see `env.template`).

### Key Configuration Areas

- **Cost/Performance**: Toggle between local/cloud models
- **Vector Database**: Switch between pgvector and Pinecone
- **Processing**: Adjust batch sizes and chunk sizes
- **Rate Limiting**: Configure API rate limits
- **Features**: Enable/disable email notifications, analytics, etc.

## 📈 Performance Optimization

### Local Embeddings

Using `google/embeddinggemma-300m` saves ~$0.13 per million tokens compared to OpenAI embeddings.

### Batch Processing

Configured batch sizes for optimal throughput:
- Embeddings: 32 items/batch
- Content collection: 50 items/batch

### Caching

Redis caching for:
- Frequently accessed summaries
- User sessions
- Rate limiting

## 🐛 Troubleshooting

### Port Already in Use

```bash
# Check what's using the port
lsof -i :8000

# Stop conflicting service or change port in docker-compose.yml
```

### Database Connection Issues

```bash
# Ensure PostgreSQL is ready
docker-compose ps postgres

# Check logs
docker-compose logs postgres
```

### Celery Tasks Not Running

```bash
# Check Redis connection
docker-compose exec redis redis-cli ping

# Restart Celery worker
docker-compose restart celery_worker
```

### Model Download Issues

First run will download the embedding model (~300MB). Ensure stable internet connection.

```bash
# Check model cache
docker-compose exec api ls -la /root/.cache/huggingface
```

## 🚢 Deployment

### Production Checklist

- [ ] Change `SECRET_KEY` and `JWT_SECRET_KEY` to strong random values
- [ ] Set `APP_ENV=production` and `DEBUG=false`
- [ ] Configure proper `ALLOWED_ORIGINS`
- [ ] Enable HTTPS/TLS
- [ ] Set up proper logging aggregation
- [ ] Configure Sentry for error tracking
- [ ] Set up database backups
- [ ] Configure resource limits in docker-compose
- [ ] Enable rate limiting
- [ ] Set up monitoring and alerts

### Environment-Specific Settings

Create separate `.env` files:
- `.env.development`
- `.env.staging`
- `.env.production`

## 📚 API Documentation

When running in development mode, interactive API documentation is available:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🤝 Contributing

See main project README for contribution guidelines.

## 📝 License

See LICENSE file in project root.

## 📞 Support

For issues and questions, please open a GitHub issue.

---

**Status**: Stage One Development - Backend Infrastructure ✅

**Next**: Stage Two - Frontend Development
