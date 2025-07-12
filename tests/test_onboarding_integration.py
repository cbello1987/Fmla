import pytest
from unittest.mock import patch, MagicMock
from flask import Flask
from services.user_context_service import UserContextService
from services.user_manager import UserManager
from services.message_processor import MessageProcessor
from services.onboarding_state_manager import OnboardingStateManager, OnboardingState
import json

@pytest.fixture
def client():
    from app import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def mock_redis(monkeypatch):
    mock_redis = MagicMock()
    monkeypatch.setattr('services.redis_service.get_redis_client', lambda: mock_redis)
    monkeypatch.setattr('services.redis_service.hash_phone_number', lambda phone: 'hashed_' + phone[-4:])
    return mock_redis

@pytest.fixture
def onboarding_mgr():
    return OnboardingStateManager()

@pytest.fixture
def user_mgr():
    return UserManager()

@pytest.fixture
def user_context():
    return UserContextService()

@pytest.fixture
def msg_proc():
    return MessageProcessor()

def simulate_sms(client, phone, body):
    return client.post('/sms', data={'From': phone, 'Body': body})

def test_full_onboarding_flow(client, mock_redis):
    phone = '+1234567890'
    # 1. User says hi (should prompt for name)
    mock_redis.get.return_value = None
    resp = simulate_sms(client, phone, 'hi')
    assert b"What's your first name" in resp.data
    # 2. User provides name
    profile = {'name': 'Carlos'}
    mock_redis.get.return_value = json.dumps(profile)
    resp = simulate_sms(client, phone, 'Carlos')
    assert b"Nice to meet you, Carlos" in resp.data
    # 3. User provides email
    profile = {'name': 'Carlos', 'email': 'carlos@family.com'}
    mock_redis.get.return_value = json.dumps(profile)
    resp = simulate_sms(client, phone, 'setup email carlos@family.com')
    assert b"onboarding complete" in resp.data or b"Welcome back" in resp.data

def test_typo_in_name(client, mock_redis):
    phone = '+1234567891'
    mock_redis.get.return_value = None
    resp = simulate_sms(client, phone, 'hiiiii')
    assert b"What's your first name" in resp.data
    # User sends typo name
    profile = {'name': 'C@rl0s'}
    mock_redis.get.return_value = json.dumps(profile)
    resp = simulate_sms(client, phone, 'C@rl0s')
    assert b"Nice to meet you" in resp.data


def test_invalid_email(client, mock_redis):
    phone = '+1234567892'
    profile = {'name': 'Maria'}
    mock_redis.get.return_value = json.dumps(profile)
    resp = simulate_sms(client, phone, 'setup email not-an-email')
    assert b"invalid email" in resp.data or b"try again" in resp.data


def test_returning_user_mid_onboarding(client, mock_redis):
    phone = '+1234567893'
    # User has name but no email
    profile = {'name': 'Ana'}
    mock_redis.get.return_value = json.dumps(profile)
    resp = simulate_sms(client, phone, 'hi')
    assert b"set up your email" in resp.data or b"email" in resp.data
    # User provides email
    profile = {'name': 'Ana', 'email': 'ana@family.com'}
    mock_redis.get.return_value = json.dumps(profile)
    resp = simulate_sms(client, phone, 'setup email ana@family.com')
    assert b"onboarding complete" in resp.data or b"Welcome back" in resp.data


def test_name_repetition_bug(client, mock_redis):
    phone = '+1234567894'
    # User has already provided name
    profile = {'name': 'Carlos'}
    mock_redis.get.return_value = json.dumps(profile)
    resp = simulate_sms(client, phone, 'Carlos')
    # Should NOT ask for name again
    assert b"set up your email" in resp.data or b"email" in resp.data
