"""
Simple test script to verify database connection works.

Run this script to test that:
1. Database engine is created successfully
2. Connection pool is working
3. Can execute queries
4. Session management works

Usage:
    python test_db_connection.py
"""

import asyncio

import pytest
from sqlalchemy import text

from app.core.logging import get_logger, setup_logging
from app.db.session import check_db_health, engine

# Setup logging
setup_logging()
logger = get_logger(__name__)


@pytest.mark.skip(reason="Standalone integration script, not a pytest test. Run with: python test_db_connection.py")
async def test_connection():
    """Test basic database connectivity."""
    print("\n" + "="*60)
    print("🔧 Testing Database Connection")
    print("="*60 + "\n")
    
    # Test 1: Engine creation
    print("✓ Database engine created successfully")
    print(f"  Engine: {engine}")
    print(f"  Pool size: {engine.pool.size()}")
    
    # Test 2: Simple query
    print("\n📊 Testing simple query...")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1 as number"))
            row = result.fetchone()
            assert row[0] == 1
            print("✓ Query executed successfully")
            print(f"  Result: {row[0]}")
    except Exception as e:
        print(f"✗ Query failed: {e}")
        return False
    
    # Test 3: PostgreSQL version
    print("\n🐘 Checking PostgreSQL version...")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print("✓ PostgreSQL connection verified")
            print(f"  Version: {version[:50]}...")
    except Exception as e:
        print(f"✗ Version check failed: {e}")
        return False
    
    # Test 4: pgvector extension
    print("\n🔌 Checking pgvector extension...")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT * FROM pg_extension WHERE extname = 'vector'")
            )
            extension = result.fetchone()
            if extension:
                print("✓ pgvector extension is installed")
                print(f"  Version: {extension[1]}")
            else:
                print("⚠ pgvector extension not found (will be needed for RAG)")
    except Exception as e:
        print(f"✗ Extension check failed: {e}")
    
    # Test 5: Connection pool
    print("\n🏊 Testing connection pool...")
    try:
        # Get multiple connections concurrently
        tasks = []
        for i in range(5):
            task = asyncio.create_task(test_concurrent_query(i))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        print(f"✓ Connection pool handled {len(results)} concurrent queries")
        print(f"  All results: {all(results)}")
    except Exception as e:
        print(f"✗ Connection pool test failed: {e}")
        return False
    
    # Test 6: Health check function
    print("\n💚 Testing health check function...")
    is_healthy = await check_db_health()
    if is_healthy:
        print("✓ Health check passed")
    else:
        print("✗ Health check failed")
        return False
    
    # Test 7: Check current database
    print("\n🗄️  Checking current database...")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT current_database()"))
            db_name = result.fetchone()[0]
            print(f"✓ Connected to database: {db_name}")
    except Exception as e:
        print(f"✗ Database check failed: {e}")
    
    print("\n" + "="*60)
    print("✅ All database tests passed!")
    print("="*60 + "\n")
    
    return True


@pytest.mark.skip(reason="Standalone integration script, not a pytest test. Run with: python test_db_connection.py")
async def test_concurrent_query(query_id: int) -> bool:
    """Test concurrent database access."""
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(f"SELECT {query_id} as id, pg_sleep(0.1)")
            )
            row = result.fetchone()
            return row[0] == query_id
    except Exception as e:
        logger.error(f"Concurrent query {query_id} failed: {e}")
        return False


async def cleanup():
    """Cleanup database connections."""
    print("\n🧹 Cleaning up connections...")
    await engine.dispose()
    print("✓ Connections closed\n")


async def main():
    """Main test function."""
    try:
        success = await test_connection()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        logger.exception("Test failed with exception")
        return 1
    finally:
        await cleanup()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
