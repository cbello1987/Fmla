
import os
import re
from utils.logging import log_structured

class SVENConfig:
    # Redis Configuration
    REDIS_PROFILE_TTL = int(os.getenv('REDIS_PROFILE_TTL', str(365 * 24 * 3600)))  # 1 year
    REDIS_EVENT_TTL = int(os.getenv('REDIS_EVENT_TTL', '300'))  # 5 minutes
    REDIS_CONN_TIMEOUT = int(os.getenv('REDIS_CONN_TIMEOUT', '5'))
    REDIS_KEY_PREFIX = os.getenv('REDIS_KEY_PREFIX', 'sven:user:')
    REDIS_CACHE_SIZE = int(os.getenv('REDIS_CACHE_SIZE', '1000'))

    # API Timeouts
    OPENAI_TIMEOUT = int(os.getenv('OPENAI_TIMEOUT', '30'))
    SENDGRID_TIMEOUT = int(os.getenv('SENDGRID_TIMEOUT', '10'))
    TWILIO_TIMEOUT = int(os.getenv('TWILIO_TIMEOUT', '10'))

    # Processing Limits
    MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', '1000'))
    MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', '10'))
    RATE_LIMIT_PER_MIN = int(os.getenv('RATE_LIMIT_PER_MIN', '20'))

    # Response Templates
    MSG_STARTUP = os.getenv('MSG_STARTUP', "S.V.E.N. is starting up. Please try again in 30 seconds! 🔄")
    MSG_ONBOARD = os.getenv('MSG_ONBOARD', (
        "� Welcome to S.V.E.N.! I'm your family's planning assistant.\n\n"
        "To get started, please set up your Skylight calendar email.\n"
        "Reply with: setup email your-calendar@skylight.frame\n\n"
        "Example: setup email smith-family@skylight.frame\n\n"
        "You can also tell me about your kids: 'My kids are Emma (8) and Jack (6)'\n\n"
        "Type 'menu' for more options!"
    ))
    MSG_EMAIL_INVALID = os.getenv('MSG_EMAIL_INVALID', "That doesn't look like a valid email. Please try again.")
    MSG_EMAIL_SET = os.getenv('MSG_EMAIL_SET', "Great! Your email {email} is now set up.")
    MSG_ERROR_GENERIC = os.getenv('MSG_ERROR_GENERIC', "Sorry, something went wrong. Please try again.")
    MSG_PHOTO_RECEIVED = os.getenv('MSG_PHOTO_RECEIVED', "📸 Photo received! For voice scheduling, please send a voice message instead! 🎤")
    MSG_VOICE_ERROR = os.getenv('MSG_VOICE_ERROR', "Sorry {name}, I couldn't process your voice message. Please try again.")
    MSG_EXPENSE_ERROR = os.getenv('MSG_EXPENSE_ERROR', "Sorry {name}, I couldn't process that right now. Please try again later.")
    MSG_SERVICE_UNAVAILABLE = os.getenv('MSG_SERVICE_UNAVAILABLE', "Service temporarily unavailable (ID: {error_id})")
    MSG_PRIVACY_NOTICE = os.getenv('MSG_PRIVACY_NOTICE', "Your privacy is important. We never share your info.")

    # Feature Flags
    ENABLE_FUZZY_MATCH = os.getenv('ENABLE_FUZZY_MATCH', 'true').lower() == 'true'
    ENABLE_VOICE = os.getenv('ENABLE_VOICE', 'true').lower() == 'true'
    DEBUG_MODE = os.getenv('DEBUG_MODE', 'false').lower() == 'true'

    # Email Settings
    SKYLIGHT_DOMAIN = os.getenv('SKYLIGHT_DOMAIN', 'ourskylight.com')
    DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', f'sven@{SKYLIGHT_DOMAIN}')
    EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$")

    @classmethod
    def validate_config(cls):
        errors = []
        # Check positive numbers
        for attr in ['REDIS_PROFILE_TTL', 'REDIS_EVENT_TTL', 'REDIS_CONN_TIMEOUT', 'REDIS_CACHE_SIZE',
                     'OPENAI_TIMEOUT', 'SENDGRID_TIMEOUT', 'TWILIO_TIMEOUT',
                     'MAX_MESSAGE_LENGTH', 'MAX_FILE_SIZE_MB', 'RATE_LIMIT_PER_MIN']:
            value = getattr(cls, attr)
            if not isinstance(value, int) or value <= 0:
                errors.append(f"{attr} must be a positive integer (got {value})")
        # Check email domain
        if not cls.SKYLIGHT_DOMAIN or '@' in cls.SKYLIGHT_DOMAIN:
            errors.append("SKYLIGHT_DOMAIN must be a domain name, not an email address")
        # Check default from email
        if not cls.EMAIL_REGEX.match(cls.DEFAULT_FROM_EMAIL):
            errors.append(f"DEFAULT_FROM_EMAIL is not a valid email: {cls.DEFAULT_FROM_EMAIL}")
        # Required envs
        required_envs = [
            'REDIS_URL',
            'SENDGRID_API_KEY',
            'PHONE_HASH_SALT',
        ]
        missing = [var for var in required_envs if not os.getenv(var)]
        if missing:
            errors.append(f"Missing required environment variables: {', '.join(missing)}")
        if errors:
            for err in errors:
                log_structured('ERROR', 'Config validation error', error=err)
            raise ValueError(f"SVENConfig validation failed: {errors}")
        log_structured('INFO', 'SVENConfig validated successfully')

    @classmethod
    def log_config(cls):
        # Log all config except secrets
        config_items = {k: v for k, v in cls.__dict__.items() if not k.startswith('__') and not callable(v) and 'SECRET' not in k and 'TOKEN' not in k}
        log_structured('INFO', 'SVENConfig loaded', **config_items)

    @classmethod
    def get_redis_ttl(cls, key_type='profile'):
        if key_type == 'profile':
            return cls.REDIS_PROFILE_TTL
        elif key_type == 'event':
            return cls.REDIS_EVENT_TTL
        return cls.REDIS_PROFILE_TTL

    @classmethod
    def get_api_timeout(cls, api='openai'):
        if api == 'openai':
            return cls.OPENAI_TIMEOUT
        elif api == 'sendgrid':
            return cls.SENDGRID_TIMEOUT
        elif api == 'twilio':
            return cls.TWILIO_TIMEOUT
        return 10

    @classmethod
    def get_response_template(cls, key):
        return getattr(cls, f"MSG_{key.upper()}", cls.MSG_ERROR_GENERIC)

# Validate and log config on import
try:
    SVENConfig.validate_config()
    SVENConfig.log_config()
except Exception as e:
    log_structured('CRITICAL', 'SVENConfig failed to load', error=str(e))
    raise
