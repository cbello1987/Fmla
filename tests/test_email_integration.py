import pytest
from unittest.mock import patch
from services.email_service import send_to_skylight_sendgrid

@patch('services.email_service.sendgrid')
def test_sendgrid_success(mock_sendgrid, mock_sendgrid_success):
    mock_sendgrid.SendGridAPIClient.return_value.send.return_value.status_code = 202
    status = send_to_skylight_sendgrid("to@ourskylight.com", "subject", "body")
    assert status.status_code == 202

@patch('services.email_service.sendgrid')
def test_sendgrid_failure(mock_sendgrid, mock_sendgrid_failure):
    mock_sendgrid.SendGridAPIClient.return_value.send.return_value.status_code = 400
    mock_sendgrid.SendGridAPIClient.return_value.send.return_value.body = 'error'
    status = send_to_skylight_sendgrid("to@ourskylight.com", "subject", "body")
    assert status.status_code == 400
    assert status.body == 'error'

@pytest.mark.parametrize("email,valid", [
    ("test@ourskylight.com", True),
    ("bademail", False),
    ("@nope.com", False),
])
def test_email_format(email, valid):
    from services.user_manager import UserManager
    mgr = UserManager()
    assert mgr.validate_email(email) == valid
