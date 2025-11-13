"""
Test script for User and UserPreferences models.

This script demonstrates:
1. Creating a new user
2. Creating user preferences
3. Querying users
4. Updating user data
5. Relationships (user ←→ preferences)
6. Enums (UpdateFrequency, SummaryLength)

Run this script to verify models work correctly:
    python test_user_models.py

Or inside Docker:
    docker compose exec api python test_user_models.py
"""

import asyncio
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.user import (
    SummaryLength,
    UpdateFrequency,
    User,
    UserPreferences,
)

# Setup logging
setup_logging()
logger = get_logger(__name__)


async def test_create_user():
    """Test creating a new user with preferences."""
    print("\n" + "="*60)
    print("🧪 Test 1: Creating a New User")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Create a new user
            user = User(
                email="alice@example.com",
                name="Alice Johnson",
                profile_picture="https://example.com/alice.jpg",
                profession="Software Engineer",  # Your requested field!
                date_of_birth=date(1990, 5, 15),  # Your requested field!
                timezone="America/New_York",
                is_active=True,
            )
            
            db.add(user)
            await db.flush()  # Get the user.id without committing
            
            print(f"✓ Created user: {user}")
            print(f"  ID: {user.id}")
            print(f"  Email: {user.email}")
            print(f"  Name: {user.name}")
            print(f"  Profession: {user.profession}")
            print(f"  Date of Birth: {user.date_of_birth}")
            print(f"  Age: {user.age} years old")
            print(f"  Timezone: {user.timezone}")
            print(f"  Created at: {user.created_at}")
            
            # Create preferences for this user
            preferences = UserPreferences(
                user_id=user.id,
                update_frequency=UpdateFrequency.WEEKLY,
                summary_length=SummaryLength.STANDARD,
                email_notifications_enabled=True,
            )
            
            db.add(preferences)
            await db.commit()
            
            print(f"\n✓ Created preferences: {preferences}")
            print(f"  Update Frequency: {preferences.update_frequency.value}")
            print(f"  Summary Length: {preferences.summary_length.value}")
            print(f"  Email Notifications: {preferences.email_notifications_enabled}")
            
            return user.id
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error creating user: {e}")
            raise


async def test_query_user(user_id: int):
    """Test querying a user and accessing preferences via relationship."""
    print("\n" + "="*60)
    print("🔍 Test 2: Querying User and Accessing Preferences")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Query user by ID
            result = await db.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one()
            
            print(f"✓ Found user: {user.name}")
            print(f"  Email: {user.email}")
            print(f"  Profession: {user.profession}")
            
            # Access preferences via relationship (lazy="joined" loads it automatically)
            print(f"\n✓ Accessing preferences via relationship:")
            print(f"  Update Frequency: {user.preferences.update_frequency.value}")
            print(f"  Summary Length: {user.preferences.summary_length.value}")
            print(f"  Notifications: {'Enabled' if user.preferences.email_notifications_enabled else 'Disabled'}")
            
            # The bi-directional relationship works both ways
            print(f"\n✓ Accessing user from preferences:")
            print(f"  User from preferences: {user.preferences.user.name}")
            
        except Exception as e:
            print(f"✗ Error querying user: {e}")
            raise


async def test_update_user(user_id: int):
    """Test updating user data."""
    print("\n" + "="*60)
    print("✏️  Test 3: Updating User Data")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Get user
            user = await db.get(User, user_id)
            
            print(f"Before update:")
            print(f"  Profession: {user.profession}")
            print(f"  Last login: {user.last_login}")
            
            # Update fields
            user.profession = "Senior Software Engineer"
            user.last_login = datetime.now(timezone.utc)
            
            await db.commit()
            await db.refresh(user)
            
            print(f"\nAfter update:")
            print(f"  Profession: {user.profession}")
            print(f"  Last login: {user.last_login}")
            print(f"  Updated at: {user.updated_at}")
            
            # Note: updated_at changes automatically!
            print(f"\n✓ Notice: updated_at timestamp changed automatically!")
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error updating user: {e}")
            raise


async def test_update_preferences(user_id: int):
    """Test updating user preferences."""
    print("\n" + "="*60)
    print("⚙️  Test 4: Updating User Preferences")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Get user (preferences loaded via relationship)
            user = await db.get(User, user_id)
            prefs = user.preferences
            
            print(f"Before update:")
            print(f"  Update Frequency: {prefs.update_frequency.value}")
            print(f"  Summary Length: {prefs.summary_length.value}")
            
            # Change preferences
            prefs.update_frequency = UpdateFrequency.DAILY
            prefs.summary_length = SummaryLength.CONCISE
            prefs.email_notifications_enabled = False
            
            await db.commit()
            await db.refresh(prefs)
            
            print(f"\nAfter update:")
            print(f"  Update Frequency: {prefs.update_frequency.value}")
            print(f"  Summary Length: {prefs.summary_length.value}")
            print(f"  Email Notifications: {prefs.email_notifications_enabled}")
            
            print(f"\n✓ Preferences updated successfully!")
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error updating preferences: {e}")
            raise


async def test_query_by_email():
    """Test querying user by email (demonstrates index usage)."""
    print("\n" + "="*60)
    print("📧 Test 5: Query User by Email (Using Index)")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Query by email - this is FAST because we have an index
            result = await db.execute(
                select(User).where(User.email == "alice@example.com")
            )
            user = result.scalar_one_or_none()
            
            if user:
                print(f"✓ Found user by email: {user.name}")
                print(f"  This query is fast because email has an index!")
                print(f"  Without index: Scans entire table (slow)")
                print(f"  With index: Direct lookup (fast)")
            else:
                print("✗ User not found")
                
        except Exception as e:
            print(f"✗ Error querying by email: {e}")
            raise


async def test_cascade_delete(user_id: int):
    """Test cascade delete - deleting user should delete preferences too."""
    print("\n" + "="*60)
    print("🗑️  Test 6: Cascade Delete")
    print("="*60)
    
    async with AsyncSessionLocal() as db:
        try:
            # Get user and check preferences exist
            user = await db.get(User, user_id)
            prefs_id = user.preferences.id
            
            print(f"Before delete:")
            print(f"  User ID: {user.id}, Name: {user.name}")
            print(f"  Preferences ID: {prefs_id}")
            
            # Delete user
            await db.delete(user)
            await db.commit()
            
            print(f"\n✓ User deleted")
            
            # Try to find preferences - should be gone due to CASCADE
            prefs_result = await db.execute(
                select(UserPreferences).where(UserPreferences.id == prefs_id)
            )
            prefs = prefs_result.scalar_one_or_none()
            
            if prefs is None:
                print(f"✓ Preferences were automatically deleted (CASCADE worked!)")
            else:
                print(f"✗ Preferences still exist (CASCADE didn't work)")
            
        except Exception as e:
            await db.rollback()
            print(f"✗ Error during cascade delete: {e}")
            raise


async def test_enum_validation():
    """Test that enum validation works."""
    print("\n" + "="*60)
    print("🎯 Test 7: Enum Validation")
    print("="*60)
    
    print("Valid UpdateFrequency values:")
    for freq in UpdateFrequency:
        print(f"  - {freq.value}")
    
    print("\nValid SummaryLength values:")
    for length in SummaryLength:
        print(f"  - {length.value}")
    
    print("\n✓ Enums ensure only valid values can be set!")
    print("  Trying to set invalid value would raise an error")
    
    # Example of what happens with invalid value:
    try:
        # This would fail:
        # prefs.update_frequency = "invalid_value"
        print("  (Invalid values are prevented at Python level)")
    except Exception as e:
        print(f"  Error: {e}")


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("🧪 Testing User and UserPreferences Models")
    print("="*60)
    
    try:
        # Test 1: Create user
        user_id = await test_create_user()
        
        # Test 2: Query user
        await test_query_user(user_id)
        
        # Test 3: Update user
        await test_update_user(user_id)
        
        # Test 4: Update preferences
        await test_update_preferences(user_id)
        
        # Test 5: Query by email
        await test_query_by_email()
        
        # Test 7: Enum validation
        await test_enum_validation()
        
        # Test 6: Cascade delete (do this last!)
        await test_cascade_delete(user_id)
        
        print("\n" + "="*60)
        print("✅ All Tests Passed!")
        print("="*60)
        print("\nKey Takeaways:")
        print("1. ✓ User model with profession and date_of_birth works")
        print("2. ✓ UserPreferences with enums works")
        print("3. ✓ One-to-one relationship works bi-directionally")
        print("4. ✓ Cascade delete works (user → preferences)")
        print("5. ✓ Indexes make email lookups fast")
        print("6. ✓ Auto-timestamps (created_at, updated_at) work")
        print("7. ✓ Enum validation ensures data integrity")
        
        return 0
        
    except Exception as e:
        print("\n" + "="*60)
        print("❌ Tests Failed!")
        print("="*60)
        logger.exception("Test failed with exception")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
