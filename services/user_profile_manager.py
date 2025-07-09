import os
import json
import hashlib
from datetime import datetime, timedelta
import redis

class UserProfileManager:
    def __init__(self, redis_url=None, salt=None):
        self.redis_url = redis_url or os.getenv('REDIS_URL')
        self.salt = salt or os.getenv('PHONE_HASH_SALT', 'sven_family_salt_2025')
        self.ttl_seconds = 365 * 24 * 3600  # 1 year
        self.redis_client = self._get_redis_client()

    def _get_redis_client(self):
        if not self.redis_url:
            raise ValueError('REDIS_URL not set')
        return redis.from_url(self.redis_url, decode_responses=True)

    def _hash_phone(self, phone):
        normalized = str(phone).replace(' ', '').replace('-', '')
        if normalized.startswith('+'):
            normalized = normalized[1:]
        return hashlib.sha256((normalized + self.salt).encode()).hexdigest()[:16]

    def _profile_key(self, phone):
        return f"user:{self._hash_phone(phone)}:profile"

    def get_user_profile(self, phone):
        key = self._profile_key(phone)
        data = self.redis_client.get(key)
        if data:
            return json.loads(data)
        return None

    def create_user_profile(self, phone, email=None, name=None):
        profile = {
            'phone': phone,
            'email': email,
            'name': name,
            'last_seen': datetime.now().isoformat(),
            'message_count': 0,
            'onboarding_complete': False
        }
        self.save_user_profile(phone, profile)
        return profile

    def save_user_profile(self, phone, profile):
        key = self._profile_key(phone)
        self.redis_client.setex(key, self.ttl_seconds, json.dumps(profile))

    def update_last_seen(self, phone):
        profile = self.get_user_profile(phone) or self.create_user_profile(phone)
        profile['last_seen'] = datetime.now().isoformat()
        self.save_user_profile(phone, profile)

    def increment_message_count(self, phone):
        profile = self.get_user_profile(phone) or self.create_user_profile(phone)
        profile['message_count'] = profile.get('message_count', 0) + 1
        self.save_user_profile(phone, profile)

    def set_onboarding_complete(self, phone, complete=True):
        profile = self.get_user_profile(phone) or self.create_user_profile(phone)
        profile['onboarding_complete'] = complete
        self.save_user_profile(phone, profile)
