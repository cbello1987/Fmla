import re
from typing import Dict, Any
from services.enhanced_user_profile_manager import EnhancedUserProfileManager
from utils.logging import log_structured

class SettingsManager:
    def __init__(self, redis_client):
        self.profile_manager = EnhancedUserProfileManager(redis_client)

    def handle_email_change(self, phone: str, new_email: str) -> str:
        if not self.validate_and_test_email(new_email):
            return "That doesn't look like a valid email. Please try again."
        self.profile_manager.update_profile(phone, {'email': new_email})
        return f"Your email has been updated to {new_email}."

    def handle_family_update(self, phone: str, update_message: str) -> str:
        profile = self.profile_manager.get_profile(phone)
        family = profile.get('family_members', [])
        # Add: "add Emma who's 6"
        add_match = re.match(r"add ([A-Z][a-z]+)(?: who's (\d{1,2}))?", update_message, re.IGNORECASE)
        if add_match:
            name = add_match.group(1)
            age = add_match.group(2)
            member = {'name': name}
            if age:
                member['age'] = int(age)
            family.append(member)
            self.profile_manager.update_profile(phone, {'family_members': family})
            return f"Added {name}{' (age ' + age + ')' if age else ''} to your family."
        # Remove: "remove Jack"
        remove_match = re.match(r"remove ([A-Z][a-z]+)", update_message, re.IGNORECASE)
        if remove_match:
            name = remove_match.group(1)
            new_family = [m for m in family if m.get('name', '').lower() != name.lower()]
            self.profile_manager.update_profile(phone, {'family_members': new_family})
            return f"Removed {name} from your family."
        # Update: "Andy is now 9"
        update_age = re.match(r"([A-Z][a-z]+) is now (\d{1,2})", update_message, re.IGNORECASE)
        if update_age:
            name = update_age.group(1)
            age = int(update_age.group(2))
            updated = False
            for m in family:
                if m.get('name', '').lower() == name.lower():
                    m['age'] = age
                    updated = True
            if updated:
                self.profile_manager.update_profile(phone, {'family_members': family})
                return f"Updated {name}'s age to {age}."
            else:
                return f"Couldn't find {name} in your family."
        return "Sorry, I couldn't understand your family update. Try 'add Emma who's 6', 'remove Jack', or 'Andy is now 9'."

    def handle_name_change(self, phone: str, new_name: str) -> str:
        self.profile_manager.update_profile(phone, {'name': new_name})
        return f"Your name has been updated to {new_name}."

    def generate_current_settings_display(self, user_profile: Dict[str, Any]) -> str:
        name = user_profile.get('name', 'Not set')
        email = user_profile.get('email', 'Not set')
        family = user_profile.get('family_members', [])
        fam_str = ', '.join([f"{m.get('name')} ({m.get('age','?')})" if m.get('age') else m.get('name') for m in family]) or 'None'
        return (f"Here are your current settings:\n"
                f"Name: {name}\n"
                f"Email: {email}\n"
                f"Family: {fam_str}\n"
                f"(You can say things like 'change email to new@domain.com', 'add Emma who's 6', 'remove Jack', 'Andy is now 9', or 'delete my data')")

    def process_settings_command(self, phone: str, command: str, value: str) -> str:
        # Email change
        if re.match(r"change email to ", command, re.IGNORECASE):
            email = value.strip()
            return self.handle_email_change(phone, email)
        # Name change
        if re.match(r"my name is ", command, re.IGNORECASE):
            name = value.strip()
            return self.handle_name_change(phone, name)
        # Family updates
        if any(kw in command.lower() for kw in ['add ', 'remove ', 'is now ']):
            return self.handle_family_update(phone, command)
        # Data deletion
        if 'delete my data' in command.lower():
            if self.delete_all_user_data(phone):
                return "All your data has been deleted. We're sad to see you go!"
            else:
                return "There was a problem deleting your data. Please try again."
        # Show settings
        if 'show my settings' in command.lower():
            profile = self.profile_manager.get_profile(phone)
            return self.generate_current_settings_display(profile)
        return "Sorry, I didn't understand that settings command."

    def validate_and_test_email(self, email_address: str) -> bool:
        # Simple regex for email validation
        if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email_address):
            return False
        # Try sending a test event (simulate or call real function)
        try:
            from services.email_service import send_to_skylight_sendgrid
            # Use dummy phone and correlation_id for test
            event_data = {'activity': 'Test Email', 'day': 'Today', 'time': 'Now'}
            result = send_to_skylight_sendgrid(event_data, 'test', 'test-corr', user_email=email_address)
            return result
        except Exception as e:
            log_structured('ERROR', 'Test email failed', 'test-corr', error=str(e))
            return False

    def export_user_data(self, phone: str) -> Dict:
        return self.profile_manager.get_profile(phone)

    def delete_all_user_data(self, phone: str) -> bool:
        try:
            self.profile_manager.delete_profile(phone)
            return True
        except Exception as e:
            log_structured('ERROR', 'Delete user data failed', phone, error=str(e))
            return False
