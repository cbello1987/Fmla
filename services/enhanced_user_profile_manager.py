"""
This file is deprecated. Please use services/user_manager.py for all user management.
"""
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
