# Troubleshooting Guide

## Common Issues and Solutions

### 1. API Endpoints Hang / Take Too Long

**Symptoms:**
- Registration or login endpoints don't respond
- curl commands hang indefinitely
- Pytest hangs during collection

**Root Cause:**
Database locks from interrupted tests or transactions.

**Diagnosis:**
```bash
# Check for hanging transactions
docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT pid, state, wait_event_type, wait_event, query FROM pg_stat_activity WHERE datname='keemu_db' AND state != 'idle';"
```

**Solution:**
```bash
# 1. Kill all hanging database connections
docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'keemu_db' AND pid != pg_backend_pid() AND state != 'idle';"

# 2. Restart API service
docker compose restart api

# 3. Verify it works
curl http://localhost:8000/health
```

**Prevention:**
- Always use Ctrl+C properly to stop tests
- Don't force-kill (Ctrl+Z) pytest
- Restart services after test failures

---

### 2. Pytest Hangs During Collection

**Symptoms:**
```
collecting ... collected 26 items
```
Then hangs indefinitely.

**Root Cause:**
- Database connections hanging
- Test fixtures trying to create transactions that conflict

**Solution:**
1. Kill hanging database connections (see above)
2. Restart all services:
   ```bash
   docker compose down
   docker compose up -d
   ```
3. Try simpler test approach:
   ```bash
   # Test one file at a time
   docker compose exec api pytest tests/test_auth.py::TestLogin -v
   ```

**Alternative:**
Use manual testing via Swagger UI instead of automated tests.

---

### 3. Database Migration Issues

**Symptoms:**
- `alembic current` shows no version
- Tables exist but `alembic_version` table missing

**Solution:**
```bash
# Check current migration state
docker compose exec api alembic current

# If empty, stamp with current head
docker compose exec api alembic stamp head

# Apply migrations
docker compose exec api alembic upgrade head
```

---

### 4. Import Errors After Code Changes

**Symptoms:**
```
ImportError: No module named 'app'
ModuleNotFoundError: cannot import name...
```

**Solution:**
```bash
# Clear Python bytecode cache
docker compose exec api find /app -type d -name __pycache__ -exec rm -rf {} +

# Restart API
docker compose restart api
```

**Better Solution:**
Rebuild the container:
```bash
docker compose down
docker compose build api
docker compose up -d
```

---

### 5. "Email already registered" Error

**Symptoms:**
Can't register test users because they already exist.

**Solution:**
```bash
# Clear test data
docker compose exec postgres psql -U keemu_user -d keemu_db -c "TRUNCATE TABLE users, user_preferences, channels, user_subscriptions, content_items RESTART IDENTITY CASCADE;"
```

**For Fresh Start:**
```bash
# Nuclear option: delete all data and restart
docker compose down -v  # -v removes volumes (deletes database)
docker compose up -d
sleep 5  # Wait for services to be ready
```

---

### 6. bcrypt Password Length Error

**Symptoms:**
```
ValueError: password cannot be longer than 72 bytes
```

**Solution:**
Use shorter passwords in tests (bcrypt has a 72-byte limit):
```python
# Good for testing
password = "testpass123"  # 11 bytes

# Bad for testing
password = "a" * 100  # 100 bytes
```

---

### 7. Google OAuth "Invalid token" Error

**Symptoms:**
```
HTTPException: Invalid Google ID token
```

**Checklist:**
- ✅ Is `GOOGLE_CLIENT_ID` set in `.env`?
- ✅ Is the ID token from the correct Google app?
- ✅ Has the token expired? (tokens expire after 1 hour)
- ✅ Is email verified on the Google account?

**Test Google OAuth:**
Google OAuth requires a real Google ID token from the frontend. You can't test it with curl alone.

---

## Quick Diagnostic Commands

### Check Service Health
```bash
# Check all services
docker compose ps

# Check API logs
docker compose logs api --tail 50

# Check database connections
docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT count(*) FROM pg_stat_activity WHERE datname='keemu_db';"
```

### Check Database
```bash
# List tables
docker compose exec postgres psql -U keemu_user -d keemu_db -c "\dt"

# Describe users table
docker compose exec postgres psql -U keemu_user -d keemu_db -c "\d users"

# Count users
docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT COUNT(*) FROM users;"
```

### Check API Endpoints
```bash
# Health check
curl http://localhost:8000/health

# OpenAPI spec
curl http://localhost:8000/openapi.json | jq '.paths | keys'

# Swagger UI (in browser)
open http://localhost:8000/docs
```

---

## Emergency Reset

If nothing works, **nuclear option**:

```bash
# 1. Stop everything
docker compose down -v

# 2. Clean Docker
docker system prune -f

# 3. Rebuild from scratch
docker compose build --no-cache

# 4. Start services
docker compose up -d

# 5. Wait for services
sleep 10

# 6. Check health
curl http://localhost:8000/health

# 7. Run migrations if needed
docker compose exec api alembic upgrade head
```

---

## Getting Help

1. **Check logs first:**
   ```bash
   docker compose logs api --tail 100
   ```

2. **Check database state:**
   ```bash
   docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT pid, state, wait_event_type, query FROM pg_stat_activity WHERE datname='keemu_db';"
   ```

3. **Check Python errors:**
   ```bash
   docker compose exec api python -c "from app.main import app; print('OK')"
   ```

4. **Check database connectivity:**
   ```bash
   docker compose exec api python -c "from app.db.session import check_db_health; import asyncio; print(asyncio.run(check_db_health()))"
   ```

---

## Prevention Best Practices

1. **Always use proper shutdown:**
   - Use Ctrl+C (SIGINT) not Ctrl+Z (SIGTSTP)
   - Let tests complete or properly fail
   
2. **Clean up after tests:**
   ```bash
   # After running tests
   docker compose restart api
   ```

3. **Use database transactions properly:**
   - Always commit or rollback
   - Don't leave hanging transactions

4. **Monitor database connections:**
   ```bash
   # Add to your workflow
   docker compose exec postgres psql -U keemu_user -d keemu_db -c "SELECT count(*) as active_connections FROM pg_stat_activity WHERE datname='keemu_db' AND state != 'idle';"
   ```

---

**Last Updated:** October 5, 2025