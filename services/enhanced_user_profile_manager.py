import os
import json
import re
from datetime import datetime, timedelta
from typing import Optional
from services.redis_service import get_redis_client, hash_phone_number
from utils.logging import log_structured

class EnhancedUserProfileManager:
    def __init__(self, correlation_id=None):
        self.redis_client = get_redis_client()
        self.correlation_id = correlation_id
        self.profile_ttl = 365 * 24 * 3600  # 1 year

    def _profile_key(self, phone):
        return f"user:{hash_phone_number(phone)}:profile"

    def get_user_profile(self, phone):
        try:
            data = self.redis_client.get(self._profile_key(phone))
            return json.loads(data) if data else {}
        except Exception as e:
            log_structured('ERROR', 'Failed to get user profile', self.correlation_id, error=str(e))
            return {}

    def save_user_profile(self, phone, profile):
        try:
            self.redis_client.setex(self._profile_key(phone), self.profile_ttl, json.dumps(profile))
        except Exception as e:
            log_structured('ERROR', 'Failed to save user profile', self.correlation_id, error=str(e))

    def add_child_to_profile(self, phone, child_name, age=None):
        profile = self.get_user_profile(phone)
        if 'children' not in profile:
            profile['children'] = []
        child_entry = {'name': child_name}
        if age:
            child_entry['age'] = age
        profile['children'].append(child_entry)
        self.save_user_profile(phone, profile)
        log_structured('INFO', 'Added child to profile', self.correlation_id, child=child_entry)

    def extract_name_from_message(self, message) -> Optional[str]:
        # Look for patterns like "I'm Carlos", "I am Carlos", "My name is Carlos"
        patterns = [
            r"i['’`]?m ([A-Za-zÀ-ÿ'\- ]+)",
            r"i am ([A-Za-zÀ-ÿ'\- ]+)",
            r"my name is ([A-Za-zÀ-ÿ'\- ]+)",
            r"this is ([A-Za-zÀ-ÿ'\- ]+)",
        ]
        for pat in patterns:
            match = re.search(pat, message, re.IGNORECASE)
            if match:
                name = match.group(1).strip().split()[0]
                return name
        return None

    def mark_onboarding_complete(self, phone):
        profile = self.get_user_profile(phone)
        profile['onboarding_complete'] = True
        self.save_user_profile(phone, profile)
        log_structured('INFO', 'Onboarding marked complete', self.correlation_id, phone=phone)

    def get_days_since_last_seen(self, phone) -> int:
        profile = self.get_user_profile(phone)
        last_seen = profile.get('last_seen')
        if not last_seen:
            return 9999
        try:
            last_seen_dt = datetime.fromisoformat(last_seen)
            days = (datetime.now() - last_seen_dt).days
            return days
        except Exception as e:
            log_structured('ERROR', 'Failed to parse last_seen', self.correlation_id, error=str(e))
            return 9999

    def update_last_seen(self, phone):
        profile = self.get_user_profile(phone)
        profile['last_seen'] = datetime.now().isoformat()
        self.save_user_profile(phone, profile)

    def generate_personalized_greeting(self, phone) -> str:
        profile = self.get_user_profile(phone)
        name = profile.get('name')
        days = self.get_days_since_last_seen(phone)
        if name:
            if days == 0:
                greeting = f"Hey {name}! Good to see you again today."
            elif days < 7:
                greeting = f"Hey {name}! Welcome back."
            else:
                greeting = f"Hi {name}, it's been a while!"
        else:
            if days == 0:
                greeting = "Hi there! Good to see you again today."
            elif days < 7:
                greeting = "Hi there! Welcome back."
            else:
                greeting = "Hello! It's been a while!"
        log_structured('INFO', 'Generated personalized greeting', self.correlation_id, greeting=greeting, days_since_last_seen=days)
        return greeting

    def set_name(self, phone, name):
        profile = self.get_user_profile(phone)
        profile['name'] = name
        self.save_user_profile(phone, profile)
        log_structured('INFO', 'Set user name', self.correlation_id, name=name)

    def set_setting(self, phone, key, value):
        profile = self.get_user_profile(phone)
        if 'settings' not in profile:
            profile['settings'] = {}
        profile['settings'][key] = value
        self.save_user_profile(phone, profile)
        log_structured('INFO', 'Set user setting', self.correlation_id, key=key, value=value)

    def get_setting(self, phone, key, default=None):
        profile = self.get_user_profile(phone)
        return profile.get('settings', {}).get(key, default)

    def set_privacy_notice_ack(self, phone, acknowledged=True):
        self.set_setting(phone, 'privacy_notice_ack', acknowledged)

    def get_privacy_notice_ack(self, phone):
        return self.get_setting(phone, 'privacy_notice_ack', False)
