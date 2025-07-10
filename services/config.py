import os

class SVENConfig:
    # Redis Configuration
    REDIS_PROFILE_TTL = int(os.getenv('REDIS_PROFILE_TTL', '31536000'))  # 1 year
    REDIS_EVENT_TTL = int(os.getenv('REDIS_EVENT_TTL', '300'))  # 5 minutes
    REDIS_TIMEOUT = int(os.getenv('REDIS_TIMEOUT', '5'))

    # API Timeouts
    OPENAI_TIMEOUT = int(os.getenv('OPENAI_TIMEOUT', '12'))
    SENDGRID_TIMEOUT = int(os.getenv('SENDGRID_TIMEOUT', '10'))
    TWILIO_TIMEOUT = int(os.getenv('TWILIO_TIMEOUT', '10'))

    # Processing Limits
    MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', '5000'))
    MAX_VOICE_FILE_SIZE = int(os.getenv('MAX_VOICE_FILE_SIZE', '16777216'))  # 16MB

    # Response Templates
    PRIVACY_NOTICE = os.getenv('SVEN_PRIVACY_NOTICE', "🔒 Your data is private. Type 'delete my data' anytime.")
    ERROR_GENERIC = os.getenv('SVEN_ERROR_GENERIC', "Sorry, I had trouble with that. Please try again!")

    # Feature Flags
    FUZZY_MATCHING_ENABLED = os.getenv('FUZZY_MATCHING_ENABLED', 'true').lower() == 'true'
    VOICE_PROCESSING_ENABLED = os.getenv('VOICE_PROCESSING_ENABLED', 'true').lower() == 'true'

    @classmethod
    def validate_config(cls):
        """Validate all configuration values on startup"""
        required_envs = [
            'REDIS_URL',
            'SENDGRID_API_KEY',
            'PHONE_HASH_SALT',
        ]
        missing = [var for var in required_envs if not os.getenv(var)]
        if missing:
            raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")
        # Additional validation can be added here
