import pytest
from flask import Flask
from flask.testing import FlaskClient
from unittest.mock import patch
from services.user_manager import UserManager

@pytest.fixture
def client(monkeypatch):
    from app import app
    app.config['TESTING'] = True
    return app.test_client()

def test_new_user_onboarding(client, mock_redis_client):
    phone = "+15551234567"
    data = {"From": phone, "Body": "hi"}
    response = client.post("/sms", data=data)
    assert b"Welcome to S.V.E.N." in response.data

def test_returning_user_flow(client, mock_redis_client):
    phone = "+15551234567"
    mgr = UserManager()
    mgr.update_profile(phone, {"name": "Alice", "onboarding_complete": True})
    data = {"From": phone, "Body": "menu"}
    response = client.post("/sms", data=data)
    assert b"Here's your menu" in response.data

def test_email_setup_flow(client, mock_redis_client):
    phone = "+15551234567"
    data = {"From": phone, "Body": "setup email alice@ourskylight.com"}
    response = client.post("/sms", data=data)
    assert b"Great! Your email" in response.data

def test_invalid_email_flow(client, mock_redis_client):
    phone = "+15551234567"
    data = {"From": phone, "Body": "setup email notanemail"}
    response = client.post("/sms", data=data)
    assert b"doesn't look like a valid email" in response.data

def test_expense_processing(client, mock_redis_client):
    phone = "+15551234567"
    data = {"From": phone, "Body": "Uber $20 to airport"}
    response = client.post("/sms", data=data)
    assert b"Hey" in response.data

def test_error_handling(client, monkeypatch):
    monkeypatch.setattr('services.user_manager.UserManager.get_profile', lambda self, phone: 1/0)
    phone = "+15551234567"
    data = {"From": phone, "Body": "menu"}
    response = client.post("/sms", data=data)
    assert b"Service temporarily unavailable" in response.data
