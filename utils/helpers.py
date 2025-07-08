import uuid

from twilio.request_validator import RequestValidator
import os


def verify_webhook_signature(request):
    """Verify Twilio webhook signature for security"""
    if os.getenv('FLASK_ENV') == 'development':
        return True  # Skip in dev
    validator = RequestValidator(os.getenv('TWILIO_AUTH_TOKEN'))
    signature = request.headers.get('X-Twilio-Signature', '')
    url = request.url
    params = request.form.to_dict()
    if not validator.validate(url, params, signature):
        print("WARNING: Invalid Twilio signature detected!")
        return False
    return True

def get_correlation_id():
    """Generate unique request ID for tracing"""
    return str(uuid.uuid4())[:8]

def sanitize_input(text, max_length=5000):
    """Validate and sanitize user input"""
    if not text:
        return ""
    if len(text) > max_length:
        raise ValueError(f"Input too long: {len(text)} chars (max {max_length})")
    return text.strip()[:max_length]

def sanitize_family_input(text, max_length=500):
    """Sanitize input for family data"""
    if not text:
        return ""
    text = text.replace('<', '').replace('>', '')
    return text.strip()[:max_length]
