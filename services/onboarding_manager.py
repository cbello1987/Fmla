import re
from typing import Optional, List, Dict, Any
from services.enhanced_user_profile_manager import EnhancedUserProfileManager
from utils.logging import log_structured

class OnboardingManager:
    # Onboarding states
    WELCOME = 'WELCOME'
    NAME_COLLECTION = 'NAME_COLLECTION'
    FAMILY_INFO = 'FAMILY_INFO'
    EMAIL_SETUP = 'EMAIL_SETUP'
    COMPLETION = 'COMPLETION'
    
    STATE_SEQUENCE = [WELCOME, NAME_COLLECTION, FAMILY_INFO, EMAIL_SETUP, COMPLETION]

    def __init__(self, redis_client):
        self.profile_manager = EnhancedUserProfileManager(redis_client)

    def get_onboarding_state(self, phone: str) -> str:
        profile = self.profile_manager.get_profile(phone)
        return profile.get('onboarding_state', self.WELCOME)

    def advance_onboarding_state(self, phone: str, collected_data: Dict[str, Any]) -> str:
        profile = self.profile_manager.get_profile(phone)
        current_state = profile.get('onboarding_state', self.WELCOME)
        idx = self.STATE_SEQUENCE.index(current_state) if current_state in self.STATE_SEQUENCE else 0
        # Save collected data
        self.profile_manager.update_profile(phone, collected_data)
        # Advance state
        if idx < len(self.STATE_SEQUENCE) - 1:
            next_state = self.STATE_SEQUENCE[idx + 1]
            self.profile_manager.update_profile(phone, {'onboarding_state': next_state})
            return next_state
        else:
            self.profile_manager.update_profile(phone, {'onboarding_complete': True, 'onboarding_state': self.COMPLETION})
            return self.COMPLETION

    def is_onboarding_complete(self, phone: str) -> bool:
        profile = self.profile_manager.get_profile(phone)
        return bool(profile.get('onboarding_complete'))

    def extract_name_from_natural_language(self, message: str) -> Optional[str]:
        # Look for patterns like "I'm Carlos", "My name is Maria", "This is John", or just a name
        patterns = [
            r"i['’`]?m ([A-Z][a-z]+)",
            r"my name is ([A-Z][a-z]+)",
            r"this is ([A-Z][a-z]+)",
            r"^([A-Z][a-z]+)$"
        ]
        for pat in patterns:
            match = re.search(pat, message, re.IGNORECASE)
            if match:
                name = match.group(1).strip().title()
                if name:
                    return name
        return None

    def extract_family_members(self, message: str) -> List[Dict[str, Any]]:
        # Look for patterns like "I have Andy who's 8", "Two kids: Emma and Jack", "My children are Emma (10), Jack (8)"
        members = []
        # Pattern 1: Name and age
        for match in re.finditer(r"([A-Z][a-z]+)[^\d]*(\d{1,2})", message):
            name, age = match.group(1), match.group(2)
            members.append({'name': name, 'age': int(age)})
        # Pattern 2: List of names (no ages)
        if not members:
            name_list = re.findall(r"([A-Z][a-z]+)", message)
            if name_list and len(name_list) > 1:
                for n in name_list:
                    members.append({'name': n})
        return members

    def generate_onboarding_prompt(self, current_state: str, user_data: Dict[str, Any]) -> str:
        if current_state == self.WELCOME:
            return "👋 Hi! I'm S.V.E.N., your family assistant. What's your first name?"
        elif current_state == self.NAME_COLLECTION:
            name = user_data.get('name')
            if name:
                return f"Nice to meet you, {name}! Do you have any kids or family members you'd like me to remember? (You can say 'skip' if not)"
            else:
                return "What's your first name? (You can just reply with your name)"
        elif current_state == self.FAMILY_INFO:
            if user_data.get('family_members'):
                return "Got it! Would you like to connect your family calendar? If so, please share your email. (Or say 'skip')"
            else:
                return "Do you have any kids or family members you'd like me to remember? (Or say 'skip')"
        elif current_state == self.EMAIL_SETUP:
            if user_data.get('email'):
                return f"Thanks! I'll send a test event to {user_data['email']}. One moment..."
            else:
                return "What's the best email to use for your family calendar? (Or say 'skip')"
        elif current_state == self.COMPLETION:
            return "🎉 All set! You're ready to use S.V.E.N. for your family. Just text me anytime!"
        else:
            return "Let's continue setting up your family assistant."

    def validate_email(self, email: str) -> bool:
        # Simple regex for email validation
        return bool(re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email))

    def handle_skip(self, phone: str, current_state: str) -> str:
        # For non-essential info, allow skipping
        if current_state in [self.FAMILY_INFO, self.EMAIL_SETUP]:
            return self.advance_onboarding_state(phone, {})
        return current_state

    def send_test_event(self, email: str, phone: str, correlation_id: str) -> bool:
        # Import locally to avoid circular import
        try:
            from services.email_service import send_to_skylight_sendgrid
            event_data = {
                'activity': 'Welcome to S.V.E.N.!',
                'day': 'Today',
                'time': 'Now',
                'location': 'Your Family',
            }
            return send_to_skylight_sendgrid(event_data, phone, correlation_id, user_email=email)
        except Exception as e:
            log_structured('ERROR', 'Test event email failed', correlation_id, error=str(e))
            return False
