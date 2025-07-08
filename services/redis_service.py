import os
import json
import hashlib
from datetime import datetime
import redis
from utils.logging import log_structured

def get_redis_client():
    try:
        redis_url = os.environ.get('REDIS_URL')
        if not redis_url:
            return None
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        client.ping()
        return client
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

def delete_user_data(phone_number):
    redis_client = get_redis_client()
    if not redis_client:
        return False
    try:
        phone_hash = hash_phone_number(phone_number)
        redis_client.delete(f"user:{phone_hash}:profile")
        redis_client.delete(f"user:{phone_hash}:trips")
        redis_client.delete(f"family:{phone_hash}:profile")
        redis_client.delete(f"family:{phone_hash}:events")
        redis_client.delete(f"pending:{phone_hash}")
        return True
    except Exception as e:
        log_structured('ERROR', 'Delete user data failed', None, error=str(e)[:100])
        return False

def store_pending_event(phone_number, event_data, correlation_id):
    redis_client = get_redis_client()
    if not redis_client:
        return
    try:
        phone_hash = hash_phone_number(phone_number)
        key = f"pending:{phone_hash}"
        redis_client.setex(key, 300, json.dumps(event_data))
        log_structured('INFO', 'Stored pending event', correlation_id)
    except Exception as e:
        log_structured('ERROR', 'Failed to store pending event', correlation_id, error=str(e))

def get_pending_event(phone_number):
    redis_client = get_redis_client()
    if not redis_client:
        return None
    try:
        phone_hash = hash_phone_number(phone_number)
        key = f"pending:{phone_hash}"
        data = redis_client.get(key)
        return json.loads(data) if data else None
    except Exception as e:
        log_structured('ERROR', 'Failed to get pending event', None, error=str(e))
        return None

def clear_pending_event(phone_number):
    redis_client = get_redis_client()
    if not redis_client:
        return
    try:
        phone_hash = hash_phone_number(phone_number)
        key = f"pending:{phone_hash}"
        redis_client.delete(key)
    except:
        pass

def store_user_email(phone_number, email_address):
    redis_client = get_redis_client()
    if not redis_client:
        return False
    try:
        phone_hash = hash_phone_number(phone_number)
        user_data = {
            'skylight_email': email_address,
            'setup_date': datetime.now().isoformat()
        }
        redis_client.setex(f"user:{phone_hash}:profile", 30 * 24 * 3600, json.dumps(user_data))
        return True
    except Exception as e:
        log_structured('ERROR', 'Failed to store email', None, error=str(e))
        return False

def get_user_skylight_email(phone_number):
    redis_client = get_redis_client()
    if not redis_client:
        return os.getenv('DEFAULT_SKYLIGHT_EMAIL')
    try:
        phone_hash = hash_phone_number(phone_number)
        user_data = redis_client.get(f"user:{phone_hash}:profile")
        if user_data:
            return json.loads(user_data).get('skylight_email')
        return None
    except:
        return None

def get_user_profile(phone_number):
    redis_client = get_redis_client()
    if not redis_client:
        return {}
    try:
        phone_hash = hash_phone_number(phone_number)
        data = redis_client.get(f"user:{phone_hash}:profile")
        return json.loads(data) if data else {}
    except Exception as e:
        log_structured('ERROR', 'Failed to get user profile', None, error=str(e))
        return {}

def store_user_name(phone_number, name):
    redis_client = get_redis_client()
    if not redis_client:
        return False
    try:
        phone_hash = hash_phone_number(phone_number)
        profile = get_user_profile(phone_number)
        profile['name'] = name
        profile['setup_date'] = datetime.now().isoformat()
        redis_client.setex(f"user:{phone_hash}:profile", 30 * 24 * 3600, json.dumps(profile))
        return True
    except Exception as e:
        log_structured('ERROR', 'Failed to store user name', None, error=str(e))
        return False
