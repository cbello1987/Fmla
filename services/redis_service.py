import os
import json
import hashlib
from datetime import datetime
import redis
from utils.logging import log_structured

_redis_client = None
def get_redis_client():
    global _redis_client
    if _redis_client:
        return _redis_client
    try:
        redis_url = os.environ.get('REDIS_URL')
        if not redis_url:
            log_structured('ERROR', 'REDIS_URL not set', None)
            return None
        _redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        _redis_client.ping()
        return _redis_client
    except Exception as e:
        log_structured('ERROR', 'Redis connection failed', None, error=str(e)[:100])
        return None

def hash_phone_number(phone):
    # Normalize phone number: remove spaces, dashes, and leading +
    normalized = str(phone).replace(' ', '').replace('-', '')
    if normalized.startswith('+'):
        normalized = normalized[1:]
    salt = os.getenv('PHONE_HASH_SALT', 'sven_family_salt_2025')
    return hashlib.sha256((normalized + salt).encode()).hexdigest()[:16]

def delete_user_data(phone_number, correlation_id=None):
    redis_client = get_redis_client()
    if not redis_client:
        log_structured('ERROR', 'Redis unavailable for delete_user_data', correlation_id)
        return False
    try:
        phone_hash = hash_phone_number(phone_number)
        redis_client.delete(f"sven:user:{phone_hash}:profile")
        redis_client.delete(f"pending:{phone_hash}")
        log_structured('INFO', 'Deleted user data', correlation_id, phone_hash=phone_hash)
        return True
    except Exception as e:
        log_structured('ERROR', 'Delete user data failed', correlation_id, error=str(e)[:100])
        return False

def store_pending_event(phone_number, event_data, correlation_id=None):
    redis_client = get_redis_client()
    if not redis_client:
        log_structured('ERROR', 'Redis unavailable for store_pending_event', correlation_id)
        return
    try:
        phone_hash = hash_phone_number(phone_number)
        key = f"pending:{phone_hash}"
        redis_client.setex(key, 300, json.dumps(event_data))
        log_structured('INFO', 'Stored pending event', correlation_id, phone_hash=phone_hash)
    except Exception as e:
        log_structured('ERROR', 'Failed to store pending event', correlation_id, error=str(e))

def get_pending_event(phone_number, correlation_id=None):
    redis_client = get_redis_client()
    if not redis_client:
        log_structured('ERROR', 'Redis unavailable for get_pending_event', correlation_id)
        return None
    try:
        phone_hash = hash_phone_number(phone_number)
        key = f"pending:{phone_hash}"
        data = redis_client.get(key)
        return json.loads(data) if data else None
    except Exception as e:
        log_structured('ERROR', 'Failed to get pending event', correlation_id, error=str(e))
        return None

def clear_pending_event(phone_number, correlation_id=None):
    redis_client = get_redis_client()
    if not redis_client:
        log_structured('ERROR', 'Redis unavailable for clear_pending_event', correlation_id)
        return
    try:
        phone_hash = hash_phone_number(phone_number)
        key = f"pending:{phone_hash}"
        redis_client.delete(key)
        log_structured('INFO', 'Cleared pending event', correlation_id, phone_hash=phone_hash)
    except Exception as e:
        log_structured('ERROR', 'Failed to clear pending event', correlation_id, error=str(e))

def store_user_email(phone_number, email_address, correlation_id=None):
    redis_client = get_redis_client()
    if not redis_client:
        log_structured('ERROR', 'Redis unavailable for store_user_email', correlation_id)
        return False
    try:
        phone_hash = hash_phone_number(phone_number)
        profile = get_user_profile(phone_number, correlation_id)
        if not profile:
            profile = standard_user_profile(phone_hash)
        profile['email'] = email_address
        profile['metadata']['last_seen'] = datetime.now().isoformat()
        redis_client.setex(f"sven:user:{phone_hash}:profile", 365 * 24 * 3600, json.dumps(profile))
        log_structured('INFO', 'Stored user email', correlation_id, phone_hash=phone_hash, email=email_address)
        return True
    except Exception as e:
        log_structured('ERROR', 'Failed to store email', correlation_id, error=str(e))
        return False

def get_user_skylight_email(phone_number, correlation_id=None):
    redis_client = get_redis_client()
    if not redis_client:
        log_structured('ERROR', 'Redis unavailable for get_user_skylight_email', correlation_id)
        return os.getenv('DEFAULT_SKYLIGHT_EMAIL')
    try:
        phone_hash = hash_phone_number(phone_number)
        user_data = redis_client.get(f"sven:user:{phone_hash}:profile")
        if user_data:
            return json.loads(user_data).get('email')
        return None
    except Exception as e:
        log_structured('ERROR', 'Failed to get user skylight email', correlation_id, error=str(e))
        return None

def standard_user_profile(phone_hash):
    now = datetime.now().isoformat()
    return {
        "phone_hash": phone_hash,
        "name": None,
        "email": None,
        "children": [],
        "settings": {
            "privacy_notices": False,
            "preferred_language": "en",
            "timezone": "UTC"
        },
        "metadata": {
            "created": now,
            "last_seen": now,
            "onboarding_complete": False,
            "message_count": 0
        }
    }

def get_user_profile(phone_number, correlation_id=None):
    redis_client = get_redis_client()
    if not redis_client:
        log_structured('ERROR', 'Redis unavailable for get_user_profile', correlation_id)
        phone_hash = hash_phone_number(phone_number)
        return standard_user_profile(phone_hash)
    try:
        phone_hash = hash_phone_number(phone_number)
        data = redis_client.get(f"sven:user:{phone_hash}:profile")
        if data:
            return json.loads(data)
        return standard_user_profile(phone_hash)
    except Exception as e:
        log_structured('ERROR', 'Failed to get user profile', correlation_id, error=str(e))
        phone_hash = hash_phone_number(phone_number)
        return standard_user_profile(phone_hash)

def store_user_name(phone_number, name, correlation_id=None):
    redis_client = get_redis_client()
    if not redis_client:
        log_structured('ERROR', 'Redis unavailable for store_user_name', correlation_id)
        return False
    try:
        phone_hash = hash_phone_number(phone_number)
        profile = get_user_profile(phone_number, correlation_id)
        if not profile:
            profile = standard_user_profile(phone_hash)
        profile['name'] = name
        profile['metadata']['last_seen'] = datetime.now().isoformat()
        redis_client.setex(f"sven:user:{phone_hash}:profile", 365 * 24 * 3600, json.dumps(profile))
        log_structured('INFO', 'Stored user name', correlation_id, phone_hash=phone_hash, name=name)
        return True
    except Exception as e:
        log_structured('ERROR', 'Failed to store user name', correlation_id, error=str(e))
        return False
