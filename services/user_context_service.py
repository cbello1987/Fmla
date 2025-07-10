from datetime import datetime, timedelta
from services.user_manager import UserManager
from utils.logging import log_structured

class UserContextService:
    def __init__(self):
        self.user_manager = UserManager()

    def get_user_context(self, phone_number, correlation_id=None):
        """
        Get user profile and determine interaction context
        Returns: {
            'is_new': bool,
            'profile': dict,
            'greeting_type': str,  # 'new_user', 'same_day', 'recent', 'long_absence'
            'days_since_last_seen': int,
            'name': str or None,
            'last_event_summary': str or None
        }
        """
        try:
            profile = self.user_manager.get_profile(phone_number)
        except Exception as e:
            log_structured('ERROR', 'Failed to load user profile', correlation_id, error=str(e))
            profile = None
        is_new = not profile or not profile.get('name')
        name = profile.get('name') if profile else None
        last_seen_str = None
        days_since_last_seen = None
        greeting_type = 'new_user'
        last_event_summary = None
        if not is_new and profile:
            last_seen_str = profile.get('metadata', {}).get('last_seen')
            if last_seen_str:
                try:
                    last_seen = datetime.fromisoformat(last_seen_str)
                    now = datetime.now()
                    days_since_last_seen = (now.date() - last_seen.date()).days
                    if days_since_last_seen == 0:
                        greeting_type = 'same_day'
                    elif 1 <= days_since_last_seen <= 7:
                        greeting_type = 'recent'
                    else:
                        greeting_type = 'long_absence'
                except Exception as e:
                    log_structured('ERROR', 'Corrupted last_seen in user profile', correlation_id, error=str(e))
                    greeting_type = 'recent'
                    days_since_last_seen = None
            else:
                greeting_type = 'recent'
            # Try to get last event summary
            last_event_summary = profile.get('last_event_summary')
        return {
            'is_new': is_new,
            'profile': profile,
            'greeting_type': greeting_type,
            'days_since_last_seen': days_since_last_seen,
            'name': name,
            'last_event_summary': last_event_summary
        }

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
