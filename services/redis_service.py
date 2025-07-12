
import os
import json
import hashlib
from datetime import datetime
import redis
import time
import threading
from utils.logging import log_structured
from services.config import SVENConfig


# Redis connection pool and health monitoring
_redis_pool = None
_pool_lock = threading.Lock()
_MAX_POOL_SIZE = 10
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.2  # seconds

def _init_redis_pool():
    global _redis_pool
    with _pool_lock:
        if _redis_pool is not None:
            return _redis_pool
        redis_url = os.environ.get('REDIS_URL')
        if not redis_url:
            log_structured('ERROR', 'REDIS_URL not set', None)
            return None
        try:
            _redis_pool = redis.ConnectionPool.from_url(
                redis_url,
                max_connections=_MAX_POOL_SIZE,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # Test connection
            client = redis.Redis(connection_pool=_redis_pool)
            client.ping()
            log_structured('INFO', 'Redis connection pool initialized', None)
            return _redis_pool
        except Exception as e:
            log_structured('ERROR', 'Failed to initialize Redis pool', None, error=str(e)[:100])
            _redis_pool = None
            return None

def get_redis_client():
    pool = _init_redis_pool()
    if not pool:
        return None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            client = redis.Redis(connection_pool=pool)
            # Health check
            client.ping()
            return client
        except redis.ConnectionError as e:
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            log_structured('WARN', f'Redis connection failed, retrying in {delay:.2f}s', None, error=str(e))
            time.sleep(delay)
        except Exception as e:
            log_structured('ERROR', 'Unexpected Redis error', None, error=str(e))
            break
    log_structured('ERROR', 'Redis pool exhausted or unavailable', None)
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
        redis_client.setex(key, SVENConfig.get_redis_ttl('event'), json.dumps(event_data))
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
        redis_client.setex(f"sven:user:{phone_hash}:profile", SVENConfig.get_redis_ttl('profile'), json.dumps(profile))
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
        key = f"sven:user:{phone_hash}:profile"
        profile = get_user_profile(phone_number, correlation_id)
        if not profile:
            profile = standard_user_profile(phone_hash)
        profile['name'] = name
        profile['metadata']['last_seen'] = datetime.now().isoformat()
        serialized = None
        try:
            serialized = json.dumps(profile)
        except Exception as ser_e:
            log_structured('ERROR', 'JSON serialization failed in store_user_name', correlation_id, error=str(ser_e), profile=str(profile))
            return False
        log_structured('DEBUG', 'Saving user profile to Redis', correlation_id, key=key, profile=profile)
        redis_client.setex(key, SVENConfig.get_redis_ttl('profile'), serialized)
        log_structured('INFO', 'Stored user name', correlation_id, phone_hash=phone_hash, name=name, key=key)
        # Immediately verify write
        verify = redis_client.get(key)
        if not verify:
            log_structured('ERROR', 'Verification failed: profile not found after setex', correlation_id, key=key)
            return False
        try:
            verify_profile = json.loads(verify)
        except Exception as ver_e:
            log_structured('ERROR', 'Verification JSON decode failed', correlation_id, error=str(ver_e), data=verify)
            return False
        if verify_profile.get('name') != name:
            log_structured('ERROR', 'Verification failed: name mismatch after setex', correlation_id, expected=name, actual=verify_profile.get('name'))
            return False
        return True
    except Exception as e:
        log_structured('ERROR', 'Failed to store user name', correlation_id, error=str(e))
        return False
