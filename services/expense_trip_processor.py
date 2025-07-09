from typing import Dict, Any
from utils.command_matcher import CommandMatcher
from utils.personalized_response import PersonalizedResponseGenerator
from services.enhanced_user_profile_manager import EnhancedUserProfileManager
from utils.logging import log_structured

class ExpenseTripProcessor:
    def __init__(self, redis_client):
        self.profile_manager = EnhancedUserProfileManager(redis_client)
        self.command_matcher = CommandMatcher()
        self.response_generator = PersonalizedResponseGenerator()

    def process_with_user_context(self, message: str, user_profile: Dict[str, Any], phone: str, correlation_id: str) -> Dict[str, Any]:
        # 1. Check onboarding status
        if not user_profile.get('onboarding_complete'):
            return {'response': self.response_generator.generate_onboarding_prompt(user_profile), 'onboarding': True}
        
        # 2. Fuzzy command matching
        match_result = self.command_matcher.match(message)
        command = match_result.get('command')
        corrections = match_result.get('corrections')
        
        # 3. Route based on user state
        if not command:
            response = self.response_generator.generate_unknown_command(user_profile, message, corrections)
            self.log_interaction(phone, correlation_id, message, response, user_profile)
            return {'response': response, 'success': False}
        
        # 4. Generate contextual response
        command_result = self.handle_command(command, message, user_profile)
        response = self.generate_contextual_response(message, user_profile, command_result)
        
        # 5. Update user profile
        self.update_user_from_interaction(phone, message, command_result)
        
        # 6. Log interaction
        self.log_interaction(phone, correlation_id, message, response, user_profile, command_result)
        
        return {'response': response, 'success': True, 'command': command}

    def generate_contextual_response(self, message: str, user_profile: Dict[str, Any], command_result: Dict[str, Any]) -> str:
        name = user_profile.get('name', 'there')
        family = user_profile.get('family_members', [])
        preferences = user_profile.get('preferences', {})
        language = self.get_user_appropriate_language(user_profile)
        
        if command_result.get('type') == 'expense':
            fam_str = self._family_string(family)
            return f"Great job, {name}! I've logged your expense. {fam_str} Let me know if you want to add more details."
        elif command_result.get('type') == 'trip':
            fam_str = self._family_string(family)
            return f"Trip added, {name}! {fam_str} Want to set reminders or share with your family?"
        elif command_result.get('type') == 'confirmation':
            return f"All set, {name}! If you need anything else, just ask."
        elif command_result.get('type') == 'error':
            return f"Oops, {name}, something went wrong: {command_result.get('error_message', 'Please try again.')}."
        else:
            return f"{language} {name}, how can I help your family today?"

    def update_user_from_interaction(self, phone: str, message: str, response_data: Dict[str, Any]):
        # Learn new preferences, update family, etc.
        updates = {}
        if response_data.get('new_preference'):
            updates.setdefault('preferences', {}).update(response_data['new_preference'])
        if response_data.get('family_update'):
            updates['family_members'] = response_data['family_update']
        if updates:
            self.profile_manager.update_profile(phone, updates)

    def get_user_appropriate_language(self, user_profile: Dict[str, Any]) -> str:
        # Return a greeting or phrase based on user preferences or family context
        if user_profile.get('preferences', {}).get('tone') == 'formal':
            return "Hello"
        elif user_profile.get('name'):
            return "Hey"
        else:
            return "Hi"

    def handle_command(self, command: str, message: str, user_profile: Dict[str, Any]) -> Dict[str, Any]:
        # Dummy implementation for command handling
        # In real use, this would process the command and return results
        if command == 'add_expense':
            return {'type': 'expense'}
        elif command == 'add_trip':
            return {'type': 'trip'}
        elif command == 'confirm':
            return {'type': 'confirmation'}
        else:
            return {'type': 'error', 'error_message': 'Unknown command'}

    def _family_string(self, family: list) -> str:
        if not family:
            return ""
        names = ', '.join([m.get('name') for m in family if m.get('name')])
        if names:
            return f"(Family: {names})"
        return ""

    def log_interaction(self, phone, correlation_id, message, response, user_profile, command_result=None):
        log_structured('INFO', 'User interaction', correlation_id,
            phone=phone,
            user_name=user_profile.get('name'),
            family=user_profile.get('family_members'),
            message=message,
            response=response,
            command_result=command_result)
