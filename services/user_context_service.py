import json
import os
import hashlib
from datetime import datetime
from utils.logging import log_structured
from datetime import datetime, timedelta
from services.user_manager import UserManager
from utils.logging import log_structured
from services.redis_service import get_redis_client, hash_phone_number

class UserContextService:
    def __init__(self):
        self.user_manager = UserManager()

    def get_user_context(self, phone_number, correlation_id=None):
        try:
            redis_client = get_redis_client()
            phone_hash = hash_phone_number(phone_number)
            profile_key = f"sven:user:{phone_hash}:profile"
            profile_data = redis_client.get(profile_key)
            if profile_data:
                profile = json.loads(profile_data)
                user_name = profile.get('name')
                if user_name:
                    return {
                        'is_new': False,
                        'name': user_name,
                        'profile': profile,
                        'greeting_type': self._determine_greeting_type(profile)
                    }
            return {
                'is_new': True,
                'name': None,
                'profile': {},
                'greeting_type': 'new_user'
            }
        except Exception as e:
            log_structured('ERROR', 'get_user_context failed', correlation_id, error=str(e))
            return {
                'is_new': True,
                'name': None,
                'profile': {},
                'greeting_type': 'new_user'
            }

    def _determine_greeting_type(self, profile):
        last_seen = profile.get('last_seen') or profile.get('metadata', {}).get('last_seen')
        if not last_seen:
            return 'returning_user'
        try:
            last_dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
            now = datetime.now().astimezone()
            hours_since = (now - last_dt).total_seconds() / 3600
            if hours_since < 24:
                return 'same_day'
            elif hours_since < 168:
                return 'recent'
            else:
                return 'long_absence'
        except Exception:
            return 'returning_user'

    def generate_contextual_greeting(self, phone_number, user_context):
        """
        Generate personalized greeting based on user history
        Returns appropriate greeting string based on greeting_type
        """
        name = user_context.get('name') or 'there'
        greeting_type = user_context.get('greeting_type')
        last_event = user_context.get('last_event_summary') or 'something fun'
        if greeting_type == 'new_user':
            return "👋 Hi! I'm S.V.E.N., your family's planning assistant! What's your first name?"
        elif greeting_type == 'same_day':
            return f"👋 Hey {name}! Back again? Ready to add more events?"
        elif greeting_type == 'recent':
            return f"👋 Welcome back, {name}! Last time you added {last_event}. What's next?"
        elif greeting_type == 'long_absence':
            return f"👋 Hey {name}! Good to see you again. I still have your setup. Ready to add events?"
        else:
            return f"👋 Hi {name}! How can I help your family today?"

    def should_trigger_onboarding(self, user_context):
        """
        Determine if user needs onboarding flow
        Returns: bool
        """
        return user_context.get('is_new', True)

    def update_user_interaction(self, phone_number, message_type='sms', correlation_id=None):
        """
        Update last_seen timestamp and interaction patterns
        """
        try:
            self.user_manager.update_profile(phone_number, {
                'metadata': {
                    'last_seen': datetime.now().isoformat(),
                    'last_message_type': message_type
                }
            })
        except Exception as e:
            log_structured('ERROR', 'Failed to update user interaction', correlation_id, error=str(e))
