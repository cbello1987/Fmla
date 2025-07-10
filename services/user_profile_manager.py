"""
This file is deprecated. Please use services/user_manager.py for all user management.
"""

    def set_onboarding_complete(self, phone, complete=True):
        profile = self.get_user_profile(phone) or self.create_user_profile(phone)
        profile['onboarding_complete'] = complete
        self.save_user_profile(phone, profile)
