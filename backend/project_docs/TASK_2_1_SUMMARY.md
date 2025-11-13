# Sub-Task 2.1 Complete: Database Session Management ✅

## What We Built

We've created the foundational database layer that all our models will use. This is like building the plumbing before adding the fixtures.

### Files Created:

1. **`app/db/base.py`** - Base classes and common functionality
2. **`app/db/session.py`** - Database engine and session management  
3. **`app/db/deps.py`** - FastAPI dependency injection
4. **`app/db/__init__.py`** - Clean imports

---

## Key Concepts Learned

### 1. **SQLAlchemy ORM (Object-Relational Mapping)**

**What is it?**
- Lets you work with database tables as Python objects
- Instead of writing SQL, you use Python classes and methods
- SQLAlchemy translates Python code to SQL automatically

**Example:**
```python
# Without ORM (Raw SQL):
cursor.execute("SELECT * FROM users WHERE email = ?", ("alice@example.com",))
user = cursor.fetchone()

# With ORM (SQLAlchemy):
user = await db.execute(select(User).where(User.email == "alice@example.com"))
```

### 2. **Database Connection Pooling**

**The Problem:**
- Creating a new database connection is slow (~50-100ms)
- If we create/close for every request, we waste time
- Database has limited connections (usually 100-500)

**The Solution:**
- Keep a "pool" of ready-to-use connections
- Reuse connections across requests
- Like a taxi stand vs. calling a new taxi every time

**Our Configuration:**
```python
pool_size=20         # Keep 20 connections ready
max_overflow=10      # Can create 10 more if busy
pool_recycle=3600    # Refresh connections every hour
```

### 3. **Async/Await for Database Operations**

**Why Async?**
- FastAPI is async - doesn't block while waiting
- Can handle multiple requests concurrently
- Much better performance under load

**Performance Example:**
```
Synchronous (blocking):
Request 1: Query (100ms) → blocks thread
Request 2: Waits for Request 1...
Request 3: Waits for Request 2...
Total: 300ms

Asynchronous (non-blocking):
Request 1: Query (100ms) → yields control
Request 2: Query (100ms) → runs concurrently
Request 3: Query (100ms) → runs concurrently  
Total: ~100ms
```

### 4. **Dependency Injection**

**The Old Way (Repetitive):**
```python
@app.get("/users")
async def get_users():
    session = create_session()
    try:
        users = await session.execute(select(User))
        return users.scalars().all()
    finally:
        await session.close()  # Easy to forget!

@app.get("/posts")
async def get_posts():
    session = create_session()  # Repeat the same code
    try:
        posts = await session.execute(select(Post))
        return posts.scalars().all()
    finally:
        await session.close()
```

**The New Way (Clean):**
```python
@app.get("/users")
async def get_users(db: DBSession):  # FastAPI provides it automatically
    users = await db.execute(select(User))
    return users.scalars().all()
    # Session cleaned up automatically

@app.get("/posts")
async def get_posts(db: DBSession):  # Same clean pattern
    posts = await db.execute(select(Post))
    return posts.scalars().all()
```

### 5. **Common Table Attributes Mixin**

Every database table needs some common fields:
- `id`: Unique identifier for each record
- `created_at`: When was this created? (for sorting, auditing)
- `updated_at`: When was this last changed? (for tracking changes)

Instead of repeating these in every model, we use a **Mixin**:

```python
class User(BaseModel):  # Automatically gets id, created_at, updated_at
    __tablename__ = "users"
    name: Mapped[str]
    email: Mapped[str]

class Post(BaseModel):  # Also gets id, created_at, updated_at
    __tablename__ = "posts"
    title: Mapped[str]
    content: Mapped[str]
```

---

## Code Architecture

```
┌─────────────────────────────────────────────────────┐
│                 FastAPI Application                  │
│                   (app/main.py)                      │
└────────────────────┬────────────────────────────────┘
                     │
                     │ Startup: init_db()
                     │ Shutdown: close_db()
                     │
         ┌───────────▼──────────────────────────────┐
         │      Database Engine (Singleton)          │
         │        (app/db/session.py)                │
         │                                            │
         │  ┌──────────────────────────────────┐    │
         │  │    Connection Pool               │    │
         │  │  ┌──────┐ ┌──────┐ ┌──────┐    │    │
         │  │  │ Conn │ │ Conn │ │ Conn │... │    │
         │  │  │  #1  │ │  #2  │ │  #3  │    │    │
         │  │  └──────┘ └──────┘ └──────┘    │    │
         │  └──────────────────────────────────┘    │
         └───────────────┬──────────────────────────┘
                         │
                         │ get_session()
                         │
              ┌──────────▼──────────────┐
              │    Request Handler      │
              │  (Your route function)  │
              │                          │
              │  db: DBSession           │
              │  ↓                       │
              │  user = await db.get()  │
              └──────────────────────────┘
```

---

## Files Explained

### `app/db/base.py` - The Foundation

**What it does:**
- Defines `BaseModel` - parent class for all models
- Adds `id`, `created_at`, `updated_at` to every model
- Provides helper methods like `.dict()` for serialization
- Sets up database naming conventions

**Key Features:**
```python
class BaseModel(Base, CommonTableAttributes):
    """
    Every model inherits from this.
    Automatically provides:
    - id: Primary key
    - created_at: Creation timestamp (UTC)
    - updated_at: Last update timestamp (UTC)
    - dict(): Convert to dictionary
    - __repr__(): Nice string representation
    """
    __abstract__ = True  # This won't create its own table
```

### `app/db/session.py` - Connection Management

**What it does:**
- Creates the database engine (connection to PostgreSQL)
- Manages connection pooling
- Provides session factory
- Handles startup/shutdown

**Key Functions:**
```python
# Called once at app startup
async def init_db():
    """
    - Test database connection
    - Create tables in development
    - Log connection status
    """

# Called for cleanup at shutdown
async def close_db():
    """
    - Close all connections
    - Clean up resources
    """

# Health check for monitoring
async def check_db_health() -> bool:
    """
    - Returns True if database is reachable
    - Used by health endpoint
    """
```

### `app/db/deps.py` - Dependency Injection

**What it does:**
- Provides `get_db()` for FastAPI routes
- Handles session lifecycle automatically
- Provides `DBSession` type annotation

**How to Use:**
```python
from app.db.deps import DBSession
from fastapi import APIRouter

router = APIRouter()

@router.get("/users/{user_id}")
async def get_user(user_id: int, db: DBSession):
    #                              ↑
    #                    FastAPI injects this automatically
    
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
    # Session automatically closed after this function
```

---

## Integration with FastAPI

We updated `app/main.py` to initialize the database on startup:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    from app.db.session import init_db
    await init_db()
    
    yield  # App runs here
    
    # Shutdown: Close database
    from app.db.session import close_db
    await close_db()
```

And enhanced the health check endpoint:

```python
@app.get("/health")
async def health_check():
    from app.db.session import check_db_health
    
    db_healthy = await check_db_health()
    
    return {
        "status": "healthy" if db_healthy else "unhealthy",
        "database": "connected" if db_healthy else "disconnected",
        ...
    }
```

---

## What's Next?

**Sub-Task 2.2: User & UserPreferences Models**

Now that we have the foundation, we'll create our first real models:
- `User` table (id, email, name, profile_picture, **profession**, **date_of_birth**, timezone, etc.)
- `UserPreferences` table (update_frequency, summary_length, notifications, etc.)

These will inherit from `BaseModel` and automatically get:
- Primary keys
- Timestamps
- All the helper methods we built

---

## Testing Our Work

### 1. **Test Database Connection**

Start the application:
```bash
cd KeeMU/backend
make up
```

Check health endpoint:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "app_name": "KeeMU",
  "environment": "development",
  "version": "0.1.0",
  "database": "connected"
}
```

### 2. **Check Logs**

```bash
make logs-api
```

You should see:
```
initializing_database
database_connection_successful
database_tables_created
```

### 3. **Verify PostgreSQL**

```bash
make db-shell
```

Inside PostgreSQL:
```sql
-- Check pgvector is installed
SELECT * FROM pg_extension WHERE extname = 'vector';

-- List tables (none yet, we'll create them next)
\dt
```

---

## Common Issues & Solutions

### Issue: "database connection failed"

**Possible causes:**
1. PostgreSQL not running
2. Wrong credentials in `.env`
3. Database not created

**Solution:**
```bash
# Check if PostgreSQL is running
make health

# Check PostgreSQL logs
docker-compose logs postgres

# Restart services
make restart
```

### Issue: "asyncpg.exceptions.InvalidCatalogNameError"

**Cause:** Database doesn't exist

**Solution:**
```bash
# Connect to postgres and create database
docker-compose exec postgres psql -U keemu_user -c "CREATE DATABASE keemu_db;"
```

### Issue: "ImportError: No module named app"

**Cause:** Python can't find the app package

**Solution:**
```bash
# Make sure you're in the backend directory
cd KeeMU/backend

# Rebuild containers
make down
make up
```

---

## Key Takeaways

✅ **Database connection pooling** improves performance by reusing connections

✅ **Async operations** allow handling many concurrent requests efficiently

✅ **Dependency injection** keeps code clean and DRY (Don't Repeat Yourself)

✅ **Base models** provide common functionality to all models

✅ **Proper lifecycle management** ensures resources are cleaned up

✅ **Health checks** help monitor system status

---

## Questions to Consider

1. **Why use UTC for timestamps?**
   - Avoids timezone confusion
   - Easy to convert to user's timezone in application
   - Consistent across servers in different locations

2. **Why separate session management from models?**
   - Separation of concerns
   - Easy to test models without database
   - Can swap database without changing models

3. **Why async instead of sync?**
   - Better performance under load
   - FastAPI is built for async
   - Can handle more concurrent users

4. **Why connection pooling?**
   - Creating connections is slow (~50-100ms each)
   - Reusing is fast (~0.1ms)
   - Database has limited connections

---

**Status:** ✅ Sub-Task 2.1 Complete

**Next:** Sub-Task 2.2 - User & UserPreferences Models

**Your Notes:**
(Space for you to add observations, questions, or learnings)
