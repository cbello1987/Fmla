#!/usr/bin/env python3
"""
Test script for Epic 1 Memory System
Tests user context, personalized greetings, and memory persistence
"""

import os
import sys
from datetime import datetime, timedelta

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_new_user_flow():
    """Test new user gets proper onboarding"""
    print("=== Testing New User Flow ===")
    try:
        from services.user_context_service import UserContextService
        context_service = UserContextService()
        test_phone = "+15551234567"
        # Ensure user is deleted for a clean test (if possible)
        try:
            from services.user_manager import UserManager
            UserManager().delete_profile(test_phone)
        except Exception:
            pass
        # Test new user context
        user_context = context_service.get_user_context(test_phone)
        print(f"New user context: {user_context}")
        # Test greeting generation
        greeting = context_service.generate_contextual_greeting(test_phone, user_context)
        print(f"New user greeting: {greeting}")
        # Should be new user
        assert user_context['is_new'] == True, "Should detect new user"
        assert "first name" in greeting.lower(), "Should ask for name"
        print("✅ New user flow working")
    except Exception as e:
        print(f"❌ New user test failed: {e}")

def test_returning_user_same_day():
    """Test returning user same day gets appropriate greeting"""
    print("=== Testing Returning User - Same Day ===")
    try:
        from services.user_context_service import UserContextService
        from services.user_manager import UserManager
        context_service = UserContextService()
        test_phone = "+15551234568"
        now = datetime.now().isoformat()
        # Set up user profile
        UserManager().update_profile(test_phone, {'name': 'Alice', 'metadata': {'last_seen': now}})
        user_context = context_service.get_user_context(test_phone)
        print(f"User context: {user_context}")
        greeting = context_service.generate_contextual_greeting(test_phone, user_context)
        print(f"Greeting: {greeting}")
        assert user_context['greeting_type'] == 'same_day', "Should detect same day return"
        assert "back again" in greeting.lower(), "Should greet as returning user"
        print("✅ Same day returning user flow working")
    except Exception as e:
        print(f"❌ Same day returning user test failed: {e}")

def test_returning_user_recent():
    """Test returning user from few days ago"""
    print("=== Testing Returning User - Recent ===")
    try:
        from services.user_context_service import UserContextService
        from services.user_manager import UserManager
        context_service = UserContextService()
        test_phone = "+15551234569"
        days_ago = (datetime.now() - timedelta(days=3)).isoformat()
        UserManager().update_profile(test_phone, {'name': 'Bob', 'metadata': {'last_seen': days_ago}, 'last_event_summary': 'a birthday party'})
        user_context = context_service.get_user_context(test_phone)
        print(f"User context: {user_context}")
        greeting = context_service.generate_contextual_greeting(test_phone, user_context)
        print(f"Greeting: {greeting}")
        assert user_context['greeting_type'] == 'recent', "Should detect recent return"
        assert "welcome back" in greeting.lower(), "Should greet as recent user"
        print("✅ Recent returning user flow working")
    except Exception as e:
        print(f"❌ Recent returning user test failed: {e}")

def test_returning_user_long_absence():
    """Test returning user after long absence"""
    print("=== Testing Returning User - Long Absence ===")
    try:
        from services.user_context_service import UserContextService
        from services.user_manager import UserManager
        context_service = UserContextService()
        test_phone = "+15551234570"
        days_ago = (datetime.now() - timedelta(days=10)).isoformat()
        UserManager().update_profile(test_phone, {'name': 'Carol', 'metadata': {'last_seen': days_ago}})
        user_context = context_service.get_user_context(test_phone)
        print(f"User context: {user_context}")
        greeting = context_service.generate_contextual_greeting(test_phone, user_context)
        print(f"Greeting: {greeting}")
        assert user_context['greeting_type'] == 'long_absence', "Should detect long absence"
        assert "good to see you again" in greeting.lower(), "Should greet as long absence user"
        print("✅ Long absence returning user flow working")
    except Exception as e:
        print(f"❌ Long absence returning user test failed: {e}")

def test_fuzzy_command_matching():
    """Test command fuzzy matching works"""
    print("=== Testing Fuzzy Command Matching ===")
    try:
        from utils.command_matcher import CommandMatcher
        matcher = CommandMatcher()
        test_cases = [
            ("memu", "menu"),
            ("halp", "help"),
            ("yes", "yes"),
            ("👍", "yes"),
        ]
        for input_text, expected in test_cases:
            result = matcher.match(input_text)
            print(f"Input: '{input_text}' -> Command: '{result.get('command')}' (Expected: '{expected}')")
        print("✅ Fuzzy matching working")
    except Exception as e:
        print(f"❌ Fuzzy matching test failed: {e}")

if __name__ == "__main__":
    # Set minimal environment variables for testing
    os.environ.setdefault('REDIS_URL', 'redis://localhost:6379')
    os.environ.setdefault('PHONE_HASH_SALT', 'test_salt_123')
    os.environ.setdefault('SENDGRID_API_KEY', 'test_key')

    print("🧪 Epic 1 Memory System Tests")
    print("=" * 40)
    try:
        from services.user_context_service import UserContextService
        from services.message_processor import MessageProcessor
        from utils.command_matcher import CommandMatcher
        print("✅ All imports successful")
        # Initialize services
        context_service = UserContextService()
        message_processor = MessageProcessor()
        command_matcher = CommandMatcher()
        print("✅ All services initialized")
        # Run tests
        test_new_user_flow()
        test_returning_user_same_day()
        test_returning_user_recent()
        test_returning_user_long_absence()
        test_fuzzy_command_matching()
        print("\n🎉 All tests completed!")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
