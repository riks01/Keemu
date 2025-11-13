# Sub-Task 2.2 Complete: User & UserPreferences Models ✅

## What We Built

We created comprehensive User and UserPreferences models with all the features you requested!

### Models Created:

1. **`User`** - Core user account information  
   - OAuth fields (email, name, profile_picture)
   - **YOUR FIELDS:** profession, date_of_birth 🎯
   - System fields: timezone, is_active, last_login
   - Auto fields: id, created_at, updated_at (from BaseModel)

2. **`UserPreferences`** - User settings
   - Update frequency (DAILY, WEEKLY, etc.)
   - Summary length (CONCISE, STANDARD, DETAILED)
   - Email notifications toggle
   - One-to-one relationship with User

3. **Enums** - Type-safe choice fields
   - `UpdateFrequency` - How often user wants digests
   - `SummaryLength` - Preferred summary detail level

---

## Files Created/Modified

### New Files:
- `app/models/__init__.py` (30 lines) - Model exports
- `app/models/user.py` (663 lines) - User & UserPreferences models
- `alembic.ini` (79 lines) - Alembic configuration
- `alembic/env.py` (213 lines) - Migration environment
- `alembic/script.py.mako` (26 lines) - Migration template
- `alembic/versions/2025-10-03_2302-*.py` - Initial migration
- `test_user_models.py` (334 lines) - Comprehensive model tests

### Database Tables Created:
```sql
-- users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    profile_picture VARCHAR(255),
    profession VARCHAR(100),           -- YOUR FIELD!
    date_of_birth DATE,                 -- YOUR FIELD!
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX ix_users_email ON users(email);

-- user_preferences table
CREATE TABLE user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    update_frequency VARCHAR NOT NULL DEFAULT 'weekly',
    summary_length VARCHAR NOT NULL DEFAULT 'standard',
    email_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

---

## Key Concepts Learned

### 1. **SQLAlchemy Models**

**What they are:**
- Python classes that represent database tables
- Each instance = one row in the table
- Columns defined with type annotations

**Example:**
```python
class User(BaseModel):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String255, unique=True)
    name: Mapped[str] = mapped_column(String100)
```

**Benefits:**
- Type safety (IDE autocomplete, type checking)
- ORM magic (Python objects ↔ SQL automatically)
- Relationships (user.preferences works!)

### 2. **Enums for Choice Fields**

**What's an Enum?**
- Predefined set of allowed values
- Like a dropdown menu in the database

**Why use them?**
```python
# Without Enum (BAD):
user.update_frequency = "daiy"  # Typo! Goes into DB unnoticed

# With Enum (GOOD):
user.update_frequency = UpdateFrequency.DAILY
user.update_frequency = "daiy"  # ERROR at Python level!
```

**Database Benefits:**
- CHECK constraint prevents invalid values
- Self-documenting code
- IDE autocomplete shows all options

### 3. **Relationships**

**One-to-One Relationship:**
```
User (1) ←→ (1) UserPreferences
```

**How it works:**
```python
# In User model:
preferences: Mapped["UserPreferences"] = relationship(
    back_populates="user",
    uselist=False,  # Single object, not a list
    cascade="all, delete-orphan"
)

# In UserPreferences model:
user: Mapped["User"] = relationship(
    back_populates="preferences"
)
```

**Usage:**
```python
user = await db.get(User, 1)
print(user.preferences.update_frequency)  # Access preferences
print(user.preferences.user.email)  # Go back to user
```

**Cascade Delete:**
```python
await db.delete(user)  # Deletes user
await db.commit()      # Preferences auto-deleted too!
```

### 4. **Foreign Keys**

**What's a Foreign Key?**
- Column that references another table's primary key
- Creates a link between tables

**Example:**
```python
user_id: Mapped[int] = mapped_column(
    ForeignKey("users.id", ondelete="CASCADE")
)
```

**What this does:**
1. Links preferences to a specific user
2. Database enforces the link (can't reference non-existent user)
3. `ondelete="CASCADE"`: When user deleted → preferences deleted too

### 5. **Nullable vs Non-nullable**

**Nullable (Optional):**
```python
profession: Mapped[str | None] = mapped_column(nullable=True)
# Can be: "Engineer" or None
# Database: NULL is allowed
```

**Non-nullable (Required):**
```python
email: Mapped[str] = mapped_column(nullable=False)
# Must have a value
# Database: NOT NULL constraint
# INSERT without email → ERROR
```

### 6. **Indexes**

**What's an Index?**
- Like a phone book index
- Makes lookups MUCH faster

**Example:**
```python
email: Mapped[str] = mapped_column(String255, unique=True, index=True)
```

**Performance:**
```
Without Index:
SELECT * FROM users WHERE email = 'alice@example.com';
→ Scans 1,000,000 rows: ~500ms

With Index:
SELECT * FROM users WHERE email = 'alice@example.com';
→ Direct lookup: ~2ms
```

**When to use indexes:**
- ✅ Columns you query frequently (email, username)
- ✅ Foreign keys
- ✅ Columns in WHERE clauses
- ❌ Don't over-index (slows down writes)

### 7. **Unique Constraints**

```python
email: Mapped[str] = mapped_column(unique=True)
```

**What it does:**
- No two users can have the same email
- Database enforces this
- Trying to insert duplicate → ERROR

**Why it matters:**
- Email is our login identifier
- Can't have two accounts with same email
- Prevents data integrity issues

### 8. **Alembic Migrations**

**What are Migrations?**
- Version control for your database schema
- Track changes over time
- Apply changes safely

**Workflow:**
```bash
# 1. Make changes to models
# (Edit app/models/user.py)

# 2. Generate migration
alembic revision --autogenerate -m "description"

# 3. Review migration file
# (Check alembic/versions/*.py)

# 4. Apply migration
alembic upgrade head

# 5. Rollback if needed
alembic downgrade -1
```

**Benefits:**
- Team collaboration (share schema changes)
- Deploy safely (test migrations in staging)
- Rollback if something breaks
- Track history (what changed when)

---

## Your Requested Fields

### 📝 **Profession Field**

```python
profession: Mapped[str | None] = mapped_column(
    String100,
    nullable=True,
    default=None,
    comment="User's profession/occupation"
)
```

**Use Cases:**
1. **Content Recommendations:** Show industry-specific content
   ```python
   if user.profession == "Software Engineer":
       recommend_tech_blogs()
   ```

2. **RAG Context:** Better answers
   ```python
   prompt = f"As a {user.profession}, here's what you need to know..."
   ```

3. **Analytics:** Understand your users
   ```python
   SELECT profession, COUNT(*) FROM users GROUP BY profession;
   # Software Engineer: 1250
   # Product Manager: 850
   # Student: 600
   ```

### 📅 **Date of Birth Field**

```python
date_of_birth: Mapped[date | None] = mapped_column(
    Date,
    nullable=True,
    default=None,
    comment="User's date of birth"
)
```

**Use Cases:**
1. **Age Calculation:**
   ```python
   age = user.age  # Uses @property method
   # age = 34
   ```

2. **Birthday Features:**
   ```python
   if is_birthday_today(user.date_of_birth):
       send_birthday_email()
   ```

3. **Age-Appropriate Content:**
   ```python
   if user.age < 18:
       filter_mature_content()
   ```

**Privacy Note:**
- Sensitive information
- Store securely
- Never display publicly
- User can choose not to provide

---

## Database Schema Visualization

```
┌─────────────────────────────────┐
│           users                  │
├─────────────────────────────────┤
│ id (PK)          SERIAL          │
│ email            VARCHAR UNIQUE  │◄─── Indexed for fast lookups
│ name             VARCHAR         │
│ profile_picture  VARCHAR         │
│ profession       VARCHAR         │◄─── YOUR FIELD
│ date_of_birth    DATE            │◄─── YOUR FIELD  
│ timezone         VARCHAR         │
│ is_active        BOOLEAN         │
│ last_login       TIMESTAMP       │
│ created_at       TIMESTAMP       │◄─── Auto-managed
│ updated_at       TIMESTAMP       │◄─── Auto-updated
└─────────────────────────────────┘
         │
         │ One-to-One
         │
         ▼
┌─────────────────────────────────┐
│      user_preferences            │
├─────────────────────────────────┤
│ id (PK)          SERIAL          │
│ user_id (FK)     INTEGER UNIQUE │◄─── Links to users.id
│ update_frequency ENUM            │◄─── CHECK constraint
│ summary_length   ENUM            │◄─── CHECK constraint
│ email_notifications_enabled BOOL│
│ created_at       TIMESTAMP       │
│ updated_at       TIMESTAMP       │
└─────────────────────────────────┘
```

---

## Common Usage Patterns

### Create a New User

```python
from datetime import date
from app.models.user import User, UserPreferences, UpdateFrequency, SummaryLength

async with AsyncSessionLocal() as db:
    # Create user
    user = User(
        email="alice@example.com",
        name="Alice Johnson",
        profession="Software Engineer",
        date_of_birth=date(1990, 5, 15),
        timezone="America/New_York"
    )
    db.add(user)
    await db.flush()  # Get user.id
    
    # Create preferences
    prefs = UserPreferences(
        user_id=user.id,
        update_frequency=UpdateFrequency.WEEKLY,
        summary_length=SummaryLength.STANDARD
    )
    db.add(prefs)
    await db.commit()
```

### Query User by Email

```python
from sqlalchemy import select

async with AsyncSessionLocal() as db:
    result = await db.execute(
        select(User).where(User.email == "alice@example.com")
    )
    user = result.scalar_one_or_none()
    
    if user:
        # Access preferences via relationship
        print(user.preferences.update_frequency)
```

### Update User

```python
async with AsyncSessionLocal() as db:
    user = await db.get(User, 1)
    
    user.profession = "Senior Software Engineer"
    user.last_login = datetime.now(timezone.utc)
    
    await db.commit()
    # updated_at changes automatically!
```

### Update Preferences

```python
async with AsyncSessionLocal() as db:
    user = await db.get(User, 1)
    
    user.preferences.update_frequency = UpdateFrequency.DAILY
    user.preferences.summary_length = SummaryLength.CONCISE
    
    await db.commit()
```

---

## Testing

### Run the Test Suite

```bash
# Inside Docker
docker compose exec api python test_user_models.py

# Expected output:
# ✓ Created user with profession and DOB
# ✓ Relationship works (user.preferences)
# ✓ Updates work (profession, preferences)
# ✓ Cascade delete works
# ✓ Enum validation works
# ✅ All Tests Passed!
```

### What the Tests Verify

1. ✓ User creation with all fields
2. ✓ UserPreferences creation
3. ✓ Relationships work bi-directionally
4. ✓ Enums accept only valid values
5. ✓ Updates work (including auto-timestamps)
6. ✓ Query by email uses index
7. ✓ Cascade delete removes preferences

---

## Migration Management

### View Migration History

```bash
docker compose exec api alembic history

# Output:
# <base> -> b599d122034a (head), add users and user_preferences tables
```

### Check Current Version

```bash
docker compose exec api alembic current

# Output:
# INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
# INFO  [alembic.runtime.migration] Will assume transactional DDL.
# b599d122034a (head)
```

### Create New Migration

```bash
# After changing models:
docker compose exec api alembic revision --autogenerate -m "add new field"

# Apply it:
docker compose exec api alembic upgrade head

# Rollback if needed:
docker compose exec api alembic downgrade -1
```

---

## What's Next?

**Sub-Task 2.3: ContentSource Model** (Next)

We'll create the ContentSource model for:
- YouTube channels
- Reddit communities  
- Blogs/RSS feeds

This will have a **one-to-many** relationship with User:
```
User (1) ←→ (Many) ContentSource
One user can follow many sources
```

---

## Key Takeaways

✅ **User model** with profession and date_of_birth works perfectly

✅ **UserPreferences** with enums ensures data integrity

✅ **One-to-one relationship** connects them bi-directionally

✅ **Cascade delete** keeps database clean

✅ **Indexes** make queries fast

✅ **Alembic migrations** manage schema changes safely

✅ **Type annotations** provide IDE autocomplete and type checking

✅ **Auto-timestamps** track creation and updates

✅ **Enums** prevent invalid data at multiple levels

---

## Troubleshooting

### Issue: "unique constraint violation"

**Problem:** Trying to create user with existing email

**Solution:**
```python
# Check if user exists first
result = await db.execute(
    select(User).where(User.email == email)
)
existing = result.scalar_one_or_none()

if existing:
    # Update existing user
else:
    # Create new user
```

### Issue: "foreign key constraint violation"

**Problem:** Trying to create preferences for non-existent user

**Solution:**
```python
# Always flush after creating user
db.add(user)
await db.flush()  # Get user.id

# Now create preferences
prefs = UserPreferences(user_id=user.id)
db.add(prefs)
await db.commit()
```

### Issue: "can't access preferences after commit"

**Problem:** Session closed, lazy loading fails

**Solution:**
```python
# Use lazy="joined" in relationship (already done!)
# Or explicitly load:
result = await db.execute(
    select(User)
    .where(User.id == user_id)
    .options(selectinload(User.preferences))
)
```

---

## Database Commands

### Verify Tables Exist

```bash
docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public';"

# Output:
#     tablename     
# ------------------
#  alembic_version
#  users
#  user_preferences
```

### Describe Users Table

```bash
docker compose exec postgres psql -U keemu_user -d keemu_db -c "\d users"

# Shows all columns, types, constraints, indexes
```

### Count Users

```bash
docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT COUNT(*) FROM users;"
```

---

## Questions & Answers

**Q: Why separate User and UserPreferences tables?**

**A:** Several reasons:
1. **Organization:** Identity vs settings
2. **Performance:** Don't always need preferences
3. **Flexibility:** Easy to add more preference fields
4. **Clarity:** Clear separation of concerns

**Q: Why are profession and date_of_birth nullable?**

**A:** 
1. Not required for core functionality
2. Users can choose not to provide
3. Can be filled in later
4. Privacy-conscious design

**Q: What happens if I try to set an invalid enum value?**

**A:** Error at multiple levels:
```python
# Python level:
prefs.update_frequency = "invalid"  # Type error!

# Database level:
# CHECK constraint rejects it

# Both prevent bad data!
```

**Q: How do I add a new field to User?**

**A:**
1. Add field to model: `new_field: Mapped[str]`
2. Generate migration: `alembic revision --autogenerate -m "add new_field"`
3. Review migration file
4. Apply: `alembic upgrade head`

**Q: Can I have users without preferences?**

**A:** Technically yes, but you shouldn't:
- Create preferences when creating user
- Relationship expects it to exist
- Use defaults for initial values

---

**Status:** ✅ Sub-Task 2.2 Complete

**Next:** Sub-Task 2.3 - ContentSource Model

**Your Learning:** You now understand:
- SQLAlchemy models and relationships
- Enums for type-safe choices
- Foreign keys and constraints
- Indexes for performance
- Alembic migrations
- Your custom fields (profession, DOB) in action!

**Great job getting this far! The foundation is solid!** 🎉
