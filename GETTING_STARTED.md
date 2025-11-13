# Getting Started with KeeMU Development

This guide will walk you through setting up and starting development on the KeeMU backend.

## Prerequisites Checklist

- [x] Docker and Docker Compose installed
- [x] Git installed
- [ ] API keys obtained (see [API_SETUP_GUIDE.md](./API_SETUP_GUIDE.md))
- [ ] Text editor/IDE (VS Code recommended)

## Step 1: Get Your API Keys

Before you can run the application, you'll need some API keys. See **[API_SETUP_GUIDE.md](./API_SETUP_GUIDE.md)** for detailed instructions.

**Minimum Required for Basic Development:**
1. ✅ Anthropic API Key (you have this)
2. ⚠️ Google OAuth Credentials (needed for user login)
3. ⚠️ YouTube Data API Key (needed for YouTube content)

**Optional (can mock initially):**
- Reddit API credentials
- SendGrid API key
- OpenAI API key (for Whisper fallback)

## Step 2: Initial Setup

```bash
# Navigate to backend directory
cd KeeMU/backend

# Copy the environment template
cp env.template .env

# Edit .env and add your API keys
# You can use nano, vim, or any text editor
nano .env
```

**Required changes in `.env`:**
```bash
# Replace these with your actual values:
SECRET_KEY=generate-a-random-32-character-string-here
JWT_SECRET_KEY=generate-another-random-32-character-string-here
ANTHROPIC_API_KEY=your-actual-anthropic-key
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
YOUTUBE_API_KEY=your-youtube-api-key
```

**Generate secret keys:**
```bash
# Quick way to generate random secrets:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Step 3: Start the Application

```bash
# Build and start all services
make up

# Or without make:
docker-compose up -d --build
```

This will start:
- ✅ PostgreSQL database (with pgvector)
- ✅ Redis (for caching and Celery)
- ✅ FastAPI application
- ✅ Celery worker
- ✅ Celery beat (scheduler)
- ✅ Flower (Celery monitoring UI)

## Step 4: Verify Everything Works

```bash
# Check service health
make health

# Or manually:
curl http://localhost:8000/health
```

**Expected response:**
```json
{
  "status": "healthy",
  "app_name": "KeeMU",
  "environment": "development",
  "version": "0.1.0"
}
```

**Access the services:**
- 🌐 API: http://localhost:8000
- 📚 API Docs: http://localhost:8000/docs (Swagger UI)
- 🌸 Flower: http://localhost:5555 (Celery monitoring)

## Step 5: View Logs

```bash
# View all logs
make logs

# View API logs only
make logs-api

# View Celery worker logs
make logs-celery
```

## Development Workflow

### Making Code Changes

1. **Edit code** - Changes are hot-reloaded automatically
2. **Check logs** - `make logs-api` to see if there are errors
3. **Test manually** - Use the Swagger UI at http://localhost:8000/docs
4. **Write tests** - Add tests in the `tests/` directory
5. **Run tests** - `make test`

### Common Commands

```bash
# Start services
make up

# Stop services
make down

# Restart services
make restart

# View logs
make logs

# Open a shell in the API container
make shell

# Open PostgreSQL shell
make db-shell

# Open Redis CLI
make redis-cli

# Run tests
make test

# Run tests with coverage
make test-cov

# Format code
make format

# Check code quality
make lint

# Check health
make health
```

### Database Operations

```bash
# Create a new migration
make migration msg="add user table"

# Apply migrations
make migrate

# Open database shell
make db-shell

# Inside db-shell, check tables:
\dt

# Check if pgvector is installed:
SELECT * FROM pg_extension WHERE extname = 'vector';
```

## Development Stages

### ✅ Stage 1: Project Foundation (Current)
We've completed the initial setup. The basic infrastructure is ready!

### 🚧 Stage 2: Database Models & Authentication (Next)
Next, we'll build:
1. Database schema and SQLAlchemy models
2. Alembic migrations
3. User authentication with Google OAuth
4. JWT token management

### 📅 Stage 3: Content Collection
After that:
1. YouTube video fetching
2. Transcript extraction
3. Reddit post collection
4. Blog/RSS parsing

### 📅 Stage 4: Content Processing & RAG
Then:
1. Content chunking
2. Local embeddings (SentenceTransformers)
3. Vector storage (pgvector)
4. RAG system with Claude

### 📅 Stage 5: Summarization & Scheduling
Finally:
1. Summary generation
2. Email notifications
3. Celery job scheduling

## Troubleshooting

### Port Already in Use

```bash
# Check what's using port 8000
lsof -i :8000

# Kill the process or change port in docker-compose.yml
```

### Services Won't Start

```bash
# Check service status
docker-compose ps

# Check logs for specific service
docker-compose logs postgres
docker-compose logs redis
docker-compose logs api

# Try rebuilding
make down
make build
make up
```

### Database Connection Error

```bash
# Wait for PostgreSQL to be ready (takes ~10-15 seconds on first run)
docker-compose logs postgres

# Look for: "database system is ready to accept connections"
```

### "Module not found" errors

```bash
# Rebuild the containers
docker-compose down
docker-compose up --build
```

### Model Download Issues

The embedding model will download on first run (~300MB). If it fails:

```bash
# Check logs
make logs-api

# Manually download by accessing the container
make shell

# Inside container:
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('google/embeddinggemma-300m')"
```

## Next Steps

Once everything is running:

1. **Explore the API docs**: http://localhost:8000/docs
2. **Check the TODO list**: Review tasks 2-16 in the project
3. **Read the PRD**: Understand the full product vision
4. **Start coding**: We'll begin with database models next!

## Need Help?

- **API Issues**: Check logs with `make logs-api`
- **Database Issues**: Check logs with `docker-compose logs postgres`
- **Celery Issues**: Check Flower UI at http://localhost:5555
- **General Issues**: Check all logs with `make logs`

## Quick Reference

| Service | URL | Purpose |
|---------|-----|---------|
| API | http://localhost:8000 | Main FastAPI application |
| API Docs | http://localhost:8000/docs | Interactive API documentation |
| Flower | http://localhost:5555 | Celery task monitoring |
| PostgreSQL | localhost:5432 | Database |
| Redis | localhost:6379 | Cache & message broker |

---

**Current Status**: ✅ Foundation Complete - Ready for Database Development!

**Next Task**: Database Schema & Models (Task #2)
