import enum
import json
from services.user_manager import UserManager
from services.redis_service import get_redis_client, hash_phone_number
from utils.logging import log_structured

class OnboardingState(enum.Enum):
    NEED_NAME = 'need_name'
    NEED_EMAIL = 'need_email'
    COMPLETE = 'complete'

class OnboardingStateManager:
    def __init__(self):
        self.user_manager = UserManager()
        self.redis = get_redis_client()

    def get_current_state(self, phone_number):
        """
        Returns the current onboarding state for the user.
        """
        phone_hash = hash_phone_number(phone_number)
        profile_key = f"sven:user:{phone_hash}:profile"
        profile_data = self.redis.get(profile_key)
        if not profile_data:
            return OnboardingState.NEED_NAME
        try:
            profile = json.loads(profile_data)
        except Exception as e:
            log_structured('ERROR', 'Failed to parse user profile JSON', None, error=str(e))
            return OnboardingState.NEED_NAME
        if not profile.get('name'):
            return OnboardingState.NEED_NAME
        if not profile.get('email'):
            return OnboardingState.NEED_EMAIL
        if profile.get('onboarding_complete'):
            return OnboardingState.COMPLETE
        return OnboardingState.NEED_EMAIL

    def advance_state(self, phone_number, collected_data):
        """
        Atomically update the user's onboarding state and profile with collected data.
        """
        phone_hash = hash_phone_number(phone_number)
        profile_key = f"sven:user:{phone_hash}:profile"
        pipe = self.redis.pipeline()
        # Fetch and update profile atomically
        while True:
            try:
                pipe.watch(profile_key)
                profile_data = pipe.get(profile_key)
                if profile_data:
                    profile = json.loads(profile_data)
                else:
                    profile = {}
                # Update profile with new data
                profile.update(collected_data)
                # Determine if onboarding is complete
                if profile.get('name') and profile.get('email'):
                    profile['onboarding_complete'] = True
                pipe.multi()
                pipe.set(profile_key, json.dumps(profile))
                pipe.execute()
                break
            except Exception as e:
                log_structured('ERROR', 'Onboarding state update failed', None, error=str(e))
                pipe.reset()
                continue
            finally:
                pipe.reset()

    def is_complete(self, phone_number):
        """
        Returns True if onboarding is complete for the user.
        """
        state = self.get_current_state(phone_number)
        return state == OnboardingState.COMPLETE
