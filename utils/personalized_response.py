class PersonalizedResponseGenerator:
    def __init__(self):
        pass

    def _get_name(self, user_profile):
        return user_profile.get('name')

    def _get_children(self, user_profile):
        children = user_profile.get('children', [])
        if not children:
            return None
        names = [c['name'] for c in children if 'name' in c]
        return names if names else None

    def generate_welcome_message(self, user_profile, is_new_user):
        name = self._get_name(user_profile)
        children = self._get_children(user_profile)
        if is_new_user:
            msg = "👋 Welcome to S.V.E.N.! I'm your family's planning assistant.\n"
            if name:
                msg += f"Great to meet you, {name}! "
            msg += "I help busy parents manage kids' activities, appointments, and reminders.\n"
            if children:
                msg += f"I see your family includes: {', '.join(children)}.\n"
            msg += "To get started, set up your Skylight calendar email (e.g. 'setup email your@email.com').\n"
            msg += "Type 'menu' for options or 'help' for more info!"
        else:
            msg = f"👋 Welcome back{name and f', {name}' or ''}! "
            if children:
                msg += f"How are {', '.join(children)} doing today? "
            msg += "What can I help your family with? Type 'menu' for options."
        return msg

    def generate_menu_response(self, user_profile):
        name = self._get_name(user_profile)
        children = self._get_children(user_profile)
        msg = "\n📋 Main Menu:\n"
        if name:
            msg = f"Hi {name}! " + msg
        if children:
            msg += f"Managing for: {', '.join(children)}\n"
        msg += (
            "1️⃣ Set up your Skylight email\n"
            "2️⃣ Add a new event (voice or text)\n"
            "3️⃣ See how S.V.E.N. works\n"
            "4️⃣ Test voice feature\n"
            "5️⃣ Settings & help\n"
            "\nReply with 1, 2, 3, 4, or 5.\n"
        )
        if self.should_show_privacy_notice(user_profile):
            msg += "\n🔒 Your data is private. Type 'delete my data' anytime."
        return msg

    def generate_help_message(self, user_profile):
        name = self._get_name(user_profile)
        onboarding = user_profile.get('onboarding_complete', False)
        msg = "💡 S.V.E.N. Help:\n"
        if name:
            msg = f"Hi {name}, " + msg
        if not onboarding:
            msg += "It looks like you haven't finished setup. Please reply with 'setup email your@email.com'.\n"
        msg += (
            "- To add an event, just send a voice or text message!\n"
            "- To see the menu, type 'menu'.\n"
            "- For privacy info, type 'privacy'.\n"
            "- To delete your data, type 'delete my data'.\n"
        )
        return msg

    def generate_confirmation_response(self, user_profile, event_data):
        name = self._get_name(user_profile)
        children = self._get_children(user_profile)
        msg = "✅ Event added! "
        if name:
            msg += f"Great job, {name}! "
        if event_data:
            msg += f"Added: {event_data.get('activity', 'an event')}"
            if event_data.get('child'):
                msg += f" for {event_data.get('child')}"
            msg += f" on {event_data.get('day', 'TBD')} at {event_data.get('time', 'TBD')}"
            if event_data.get('location'):
                msg += f" at {event_data.get('location')}"
            msg += ". "
        if children:
            msg += f"Your family calendar is up to date for {', '.join(children)}! "
        msg += "\nKeep it up! 🌟"
        return msg

    def generate_settings_menu(self, user_profile):
        name = self._get_name(user_profile)
        msg = "⚙️ Settings Menu:\n"
        if name:
            msg = f"Hi {name}, " + msg
        msg += (
            "- To update your email, reply with 'setup email your@email.com'.\n"
            "- To add children, reply with 'My kids are Emma (8), Jack (6)'.\n"
            "- To delete your data, type 'delete my data'.\n"
            "- For privacy info, type 'privacy'.\n"
        )
        return msg

    def should_show_privacy_notice(self, user_profile):
        # Show privacy notice if user is new or hasn't acknowledged
        return not user_profile.get('privacy_notice_ack', False)
