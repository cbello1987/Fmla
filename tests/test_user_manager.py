import pytest
from services.user_manager import UserManager

@pytest.mark.usefixtures("mock_redis_client")
def test_profile_creation_and_update(test_user_profile):
    mgr = UserManager()
    phone = "+15551234567"
    # Create profile
    profile = mgr.get_profile(phone)
    assert profile["name"] is None
    # Update profile
    mgr.update_profile(phone, {"name": "Alice", "email": "alice@ourskylight.com"})
    updated = mgr.get_profile(phone)
    assert updated["name"] == "Alice"
    assert updated["email"] == "alice@ourskylight.com"

@pytest.mark.usefixtures("mock_redis_client")
def test_onboarding_flow(test_user_profile):
    mgr = UserManager()
    phone = "+15551234567"
    mgr.update_profile(phone, {"onboarding_complete": False})
    assert not mgr.is_onboarding_complete(phone)
    mgr.mark_onboarding_complete(phone)
    assert mgr.is_onboarding_complete(phone)

@pytest.mark.usefixtures("mock_redis_client")
def test_email_validation():
    mgr = UserManager()
    assert mgr.validate_email("test@ourskylight.com")
    assert not mgr.validate_email("not-an-email")
