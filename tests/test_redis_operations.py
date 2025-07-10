import pytest
from services.redis_service import get_redis_client, store_user_email, get_user_profile, delete_user_data

@pytest.mark.usefixtures("mock_redis_client")
def test_redis_store_and_retrieve(test_user_profile):
    phone = "+15551234567"
    email = "alice@ourskylight.com"
    store_user_email(phone, email)
    profile = get_user_profile(phone)
    assert profile["email"] == email

@pytest.mark.usefixtures("mock_redis_client")
def test_redis_delete_user(test_user_profile):
    phone = "+15551234567"
    store_user_email(phone, "alice@ourskylight.com")
    assert get_user_profile(phone)["email"] == "alice@ourskylight.com"
    delete_user_data(phone)
    assert get_user_profile(phone)["email"] is None

@pytest.mark.usefixtures("mock_redis_client")
def test_redis_connection_failure(monkeypatch):
    monkeypatch.setattr('services.redis_service.get_redis_client', lambda: None)
    assert get_redis_client() is None
