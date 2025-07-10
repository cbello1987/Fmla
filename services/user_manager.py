
import re
from datetime import datetime
from services.redis_service import (
    store_user_email, get_user_skylight_email, get_user_profile, store_user_name
)
from utils.logging import log_structured
from services.config import SVENConfig

class UserManager:
    """
    Unified user management for S.V.E.N. Handles profile, onboarding, family, and email.
    Uses redis_service.py for all storage.
    """
    def __init__(self):
        pass

    def get_profile(self, phone):
        return get_user_profile(phone)

    def update_profile(self, phone, updates):
        profile = get_user_profile(phone)
        profile.update(updates)
        # Save name/email using redis_service helpers for compatibility
        if 'name' in updates:
            store_user_name(phone, updates['name'])
        if 'skylight_email' in updates or 'email' in updates:
            email = updates.get('skylight_email') or updates.get('email')
            store_user_email(phone, email)
        # Save other fields
        import json
        from services.redis_service import get_redis_client, hash_phone_number
        redis_client = get_redis_client()
        if redis_client:
            phone_hash = hash_phone_number(phone)
            redis_client.setex(f"user:{phone_hash}:profile", SVENConfig.get_redis_ttl('profile'), json.dumps(profile))
        return profile

    def get_email(self, phone):
        return get_user_skylight_email(phone)

    def set_email(self, phone, email):
        return store_user_email(phone, email)

    def get_name(self, phone):
        profile = get_user_profile(phone)
        return profile.get('name')

    def set_name(self, phone, name):
        return store_user_name(phone, name)

    def get_family(self, phone):
        profile = get_user_profile(phone)
        return profile.get('family_members', [])

    def set_family(self, phone, family_list):
        profile = get_user_profile(phone)
        profile['family_members'] = family_list
        self.update_profile(phone, profile)

    def onboarding_state(self, phone):
        profile = get_user_profile(phone)
        return profile.get('onboarding_state', 'WELCOME')

    def set_onboarding_state(self, phone, state):
        profile = get_user_profile(phone)
        profile['onboarding_state'] = state
        self.update_profile(phone, profile)

    def is_onboarding_complete(self, phone):
        profile = get_user_profile(phone)
        return bool(profile.get('onboarding_complete'))

    def mark_onboarding_complete(self, phone):
        profile = get_user_profile(phone)
        profile['onboarding_complete'] = True
        self.update_profile(phone, profile)

    def extract_name(self, message):
        patterns = [
            r"i['’`]?m ([A-Z][a-z]+)",
            r"my name is ([A-Z][a-z]+)",
            r"this is ([A-Z][a-z]+)",
            r"^([A-Z][a-z]+)$"
        ]
        for pat in patterns:
            match = re.search(pat, message, re.IGNORECASE)
            if match:
                return match.group(1).strip().title()
        return None

    def extract_family(self, message):
        members = []
        for match in re.finditer(r"([A-Z][a-z]+)[^\d]*(\d{1,2})", message):
            name, age = match.group(1), match.group(2)
            members.append({'name': name, 'age': int(age)})
        if not members:
            name_list = re.findall(r"([A-Z][a-z]+)", message)
            if name_list and len(name_list) > 1:
                for n in name_list:
                    members.append({'name': n})
        return members

    def validate_email(self, email):
        return bool(SVENConfig.EMAIL_REGEX.match(email))
