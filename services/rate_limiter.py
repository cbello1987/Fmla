import time
from collections import defaultdict, deque
from services.config import SVENConfig
from utils.logging import log_structured

class RateLimiter:
    """
    Per-phone rate limiting: 10/min, 100/hour. Exponential backoff for abusers.
    Whitelist for admin/test numbers.
    """
    _minute = defaultdict(lambda: deque(maxlen=10))
    _hour = defaultdict(lambda: deque(maxlen=100))
    _backoff = defaultdict(int)
    _whitelist = set(SVENConfig.__dict__.get('RATE_LIMIT_WHITELIST', []))

    @classmethod
    def allow(cls, phone):
        if phone in cls._whitelist:
            return True, 0
        now = time.time()
        cls._minute[phone].append(now)
        cls._hour[phone].append(now)
        # Clean up old
        cls._minute[phone] = deque([t for t in cls._minute[phone] if now-t < 60], maxlen=10)
        cls._hour[phone] = deque([t for t in cls._hour[phone] if now-t < 3600], maxlen=100)
        if len(cls._minute[phone]) > 10 or len(cls._hour[phone]) > 100:
            cls._backoff[phone] += 1
            wait = min(2 ** cls._backoff[phone], 300)
            log_structured('WARN', 'Rate limit exceeded', phone=phone, wait_seconds=wait)
            return False, wait
        cls._backoff[phone] = 0
        return True, 0

    @classmethod
    def get_status(cls, phone):
        return {
            'minute': len(cls._minute[phone]),
            'hour': len(cls._hour[phone]),
            'backoff': cls._backoff[phone]
        }
