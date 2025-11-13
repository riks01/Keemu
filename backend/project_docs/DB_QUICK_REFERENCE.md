# Database Quick Reference Card

## 🎯 Common Patterns

### Using Database in Routes

```python
from fastapi import APIRouter
from sqlalchemy import select
from app.db.deps import DBSession
from app.models.user import User

router = APIRouter()

# Pattern 1: Get single record
@router.get("/users/{user_id}")
async def get_user(user_id: int, db: DBSession):
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# Pattern 2: Get multiple records
@router.get("/users")
async def list_users(db: DBSession, skip: int = 0, limit: int = 100):
    result = await db.execute(
        select(User).offset(skip).limit(limit)
    )
    users = result.scalars().all()
    return users

# Pattern 3: Create record
@router.post("/users")
async def create_user(user_data: UserCreate, db: DBSession):
    user = User(**user_data.dict())
    db.add(user)
    await db.commit()
    await db.refresh(user)  # Get the id and timestamps
    return user

# Pattern 4: Update record
@router.put("/users/{user_id}")
async def update_user(user_id: int, user_data: UserUpdate, db: DBSession):
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404)
    
    for key, value in user_data.dict(exclude_unset=True).items():
        setattr(user, key, value)
    
    await db.commit()
    await db.refresh(user)
    return user

# Pattern 5: Delete record
@router.delete("/users/{user_id}")
async def delete_user(user_id: int, db: DBSession):
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404)
    
    await db.delete(user)
    await db.commit()
    return {"message": "User deleted"}

# Pattern 6: Filter with multiple conditions
@router.get("/users/search")
async def search_users(
    name: str | None = None,
    email: str | None = None,
    db: DBSession = Depends()
):
    query = select(User)
    
    if name:
        query = query.where(User.name.ilike(f"%{name}%"))
    if email:
        query = query.where(User.email == email)
    
    result = await db.execute(query)
    return result.scalars().all()
```

---

## 🔧 Session Operations

```python
# Get single record
user = await db.get(User, user_id)

# Execute query
result = await db.execute(select(User))
users = result.scalars().all()

# Get one or raise
user = result.scalar_one()  # Raises if 0 or >1 results

# Get one or None
user = result.scalar_one_or_none()  # Returns None if not found

# Add new record
db.add(user)

# Add multiple records
db.add_all([user1, user2, user3])

# Delete record
await db.delete(user)

# Commit changes
await db.commit()

# Rollback changes
await db.rollback()

# Refresh from database
await db.refresh(user)

# Flush (send to DB but don't commit)
await db.flush()
```

---

## 📝 Query Patterns

```python
from sqlalchemy import select, and_, or_, func

# Basic select
query = select(User)

# Where clause
query = select(User).where(User.email == "alice@example.com")

# Multiple conditions (AND)
query = select(User).where(
    and_(
        User.is_active == True,
        User.email.like("%@gmail.com")
    )
)

# Multiple conditions (OR)
query = select(User).where(
    or_(
        User.role == "admin",
        User.role == "moderator"
    )
)

# Order by
query = select(User).order_by(User.created_at.desc())

# Limit and offset (pagination)
query = select(User).offset(20).limit(10)

# Count
query = select(func.count(User.id))

# Join
query = select(User).join(Post).where(Post.published == True)

# Distinct
query = select(User.email).distinct()

# Like / ilike (case-insensitive)
query = select(User).where(User.name.ilike("%alice%"))

# In
query = select(User).where(User.id.in_([1, 2, 3]))

# Between
query = select(User).where(User.created_at.between(start_date, end_date))

# Is null / is not null
query = select(User).where(User.deleted_at.is_(None))
query = select(User).where(User.deleted_at.is_not(None))
```

---

## 🏗️ Model Definition

```python
from datetime import datetime
from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel, String255

class User(BaseModel):
    """User model - inherits id, created_at, updated_at from BaseModel"""
    
    __tablename__ = "users"
    
    # Simple fields
    email: Mapped[str] = mapped_column(String255, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)
    
    # Optional field (can be None)
    profile_picture: Mapped[str | None] = mapped_column(String255, default=None)
    
    # Field with comment
    timezone: Mapped[str] = mapped_column(
        String(50),
        default="UTC",
        comment="User's timezone for scheduling"
    )
    
    # Relationship (one-to-many)
    posts: Mapped[list["Post"]] = relationship(
        back_populates="author",
        cascade="all, delete-orphan"
    )
    
    # Relationship (one-to-one)
    preferences: Mapped["UserPreferences"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False
    )

class Post(BaseModel):
    __tablename__ = "posts"
    
    title: Mapped[str] = mapped_column(String255)
    content: Mapped[str]
    
    # Foreign key
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    
    # Relationship
    author: Mapped["User"] = relationship(back_populates="posts")
```

---

## 🧪 Testing with Database

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from app.db.base import Base

@pytest.fixture
async def test_db():
    """Create test database session"""
    # Use in-memory SQLite for testing
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=NullPool,
        echo=False
    )
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session
    async with AsyncSession(engine) as session:
        yield session
    
    # Cleanup
    await engine.dispose()

async def test_create_user(test_db: AsyncSession):
    """Test creating a user"""
    user = User(email="test@example.com", name="Test User")
    test_db.add(user)
    await test_db.commit()
    
    # Verify
    assert user.id is not None
    assert user.created_at is not None
```

---

## 🚨 Common Mistakes

### ❌ Forgetting to await

```python
# Wrong
result = db.execute(select(User))  # Returns coroutine

# Correct
result = await db.execute(select(User))
```

### ❌ Forgetting to commit

```python
# Wrong - changes not saved
user.name = "New Name"
await db.refresh(user)  # Still has old name!

# Correct
user.name = "New Name"
await db.commit()
await db.refresh(user)  # Now has new name
```

### ❌ Accessing relationships after session closed

```python
# Wrong
@router.get("/users/{user_id}")
async def get_user(user_id: int, db: DBSession):
    user = await db.get(User, user_id)
    return user  # Session closes here

# Later in response serialization:
# user.posts  # ERROR: Session is closed!

# Correct - load relationship before returning
@router.get("/users/{user_id}")
async def get_user(user_id: int, db: DBSession):
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.posts))  # Load relationship
    )
    return result.scalar_one()
```

### ❌ Not handling None results

```python
# Wrong
user = result.scalar_one()  # Raises if not found

# Correct
user = result.scalar_one_or_none()
if not user:
    raise HTTPException(status_code=404, detail="User not found")
```

---

## 📚 Useful Commands

```bash
# Start database
make up

# Database shell
make db-shell

# Check health
curl http://localhost:8000/health

# View logs
make logs-api

# Run migrations (later)
make migrate

# Create migration (later)
make migration msg="add users table"

# Test connection
python test_db_connection.py
```

---

## 🔗 Key Imports

```python
# Base classes
from app.db.base import BaseModel, String255, String100

# Dependencies
from app.db.deps import DBSession, DBTransaction

# SQLAlchemy
from sqlalchemy import select, and_, or_, func, String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncSession

# FastAPI
from fastapi import APIRouter, Depends, HTTPException
```

---

## 💡 Tips

1. **Always use UTC for timestamps** - Convert to user timezone in the application layer
2. **Use indexes on frequently queried fields** - `index=True` in mapped_column
3. **Use unique constraints** - `unique=True` for emails, usernames, etc.
4. **Use CASCADE for related deletes** - `ondelete="CASCADE"` in ForeignKey
5. **Load relationships explicitly** - Use `selectinload()` or `joinedload()`
6. **Use transactions for multi-step operations** - `async with DBTransaction(db)`
7. **Add comments to columns** - `comment="..."` helps with database documentation
8. **Test database code** - Use in-memory SQLite for fast tests

---

**Quick Reference Version:** 1.0  
**Last Updated:** Task 2.1 Complete
