import pytest
import fakeredis
from unittest.mock import patch, MagicMock

@pytest.fixture(scope='session')
def test_user_profile():
    return {
        "phone_hash": "abc123def456",
        "name": "Alice",
        "email": "alice@ourskylight.com",
        "children": [
            {"name": "Emma", "age": 8},
            {"name": "Jack", "age": 6}
        ],
        "settings": {"privacy_notices": True, "preferred_language": "en", "timezone": "UTC"},
        "metadata": {"created": "2025-07-10T12:00:00", "last_seen": "2025-07-10T12:00:00", "onboarding_complete": True, "message_count": 5}
    }

@pytest.fixture
def mock_redis_client(monkeypatch):
    fake_redis = fakeredis.FakeStrictRedis()
    monkeypatch.setattr('services.redis_service.get_redis_client', lambda: fake_redis)
    return fake_redis

@pytest.fixture
def mock_openai_responses(monkeypatch):
    mock_openai = MagicMock()
    mock_openai.Completion.create.return_value = {'choices': [{'text': 'Test transcription'}]}
    monkeypatch.setattr('openai.Completion', mock_openai.Completion)
    return mock_openai

@pytest.fixture
def mock_sendgrid_success(monkeypatch):
    mock_send = MagicMock(return_value=MagicMock(status_code=202))
    monkeypatch.setattr('services.email_service.send_to_skylight_sendgrid', mock_send)
    return mock_send

@pytest.fixture
def mock_sendgrid_failure(monkeypatch):
    mock_send = MagicMock(return_value=MagicMock(status_code=400, body='error'))
    monkeypatch.setattr('services.email_service.send_to_skylight_sendgrid', mock_send)
    return mock_send

@pytest.fixture
def sample_voice_events():
    return [
        {"audio_url": "http://test/audio1.mp3", "transcription": "Schedule soccer at 5pm"},
        {"audio_url": "http://test/audio2.mp3", "transcription": "Doctor appointment for Emma at 3pm"}
    ]
