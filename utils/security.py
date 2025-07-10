import re
import html
import hashlib
import os
from services.config import SVENConfig

def normalize_phone(phone):
    # Remove spaces, dashes, parens, leading +, keep only digits
    return re.sub(r'\D', '', str(phone))

def validate_phone(phone):
    norm = normalize_phone(phone)
    return bool(re.match(r'^1?\d{10}$', norm))

def validate_email(email):
    if not SVENConfig.EMAIL_REGEX.match(email):
        return False
    domain = email.split('@')[-1]
    return domain == SVENConfig.SKYLIGHT_DOMAIN

def sanitize_message(msg):
    # Remove HTML tags, scripts, excessive whitespace
    msg = html.unescape(msg)
    msg = re.sub(r'<.*?>', '', msg)
    msg = re.sub(r'<script.*?>.*?</script>', '', msg, flags=re.DOTALL)
    msg = re.sub(r'\s+', ' ', msg)
    return msg.strip()

def validate_file(file, allowed_types, max_size_mb):
    if file.content_type not in allowed_types:
        return False
    if len(file.read()) > max_size_mb * 1024 * 1024:
        return False
    file.seek(0)
    return True

def hash_phone(phone):
    salt = os.getenv('PHONE_HASH_SALT', 'sven_family_salt_2025')
    norm = normalize_phone(phone)
    return hashlib.sha256((norm + salt).encode()).hexdigest()[:16]

# Security headers for Flask
SECURITY_HEADERS = {
    'Content-Security-Policy': "default-src 'self'",
    'Strict-Transport-Security': 'max-age=63072000; includeSubDomains; preload',
    'X-Frame-Options': 'DENY',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'geolocation=(), microphone=()'
}

def add_security_headers(response):
    for k, v in SECURITY_HEADERS.items():
        response.headers[k] = v
    return response
