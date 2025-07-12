import time
from collections import defaultdict, deque
from utils.logging import log_structured

class AntiAbuseLimiter:
    _msg_minute = defaultdict(lambda: deque(maxlen=10))
    _fail_minute = defaultdict(lambda: deque(maxlen=5))
    _banned = defaultdict(float)  # phone -> ban expiry
    _identical_msgs = defaultdict(lambda: deque(maxlen=5))
    # Development/test whitelist (bypass all rate limiting)
    _whitelist = {
        '+16178171635',  # Add more numbers as needed
    }

    @classmethod
    def allow(cls, phone, message, success=True):
        if phone in cls._whitelist:
            log_structured('INFO', 'Rate limit bypass for whitelisted number', phone=phone)
            return True, 0
        now = time.time()
        if now < cls._banned[phone]:
            return False, int(cls._banned[phone] - now)
        cls._msg_minute[phone].append(now)
        if not success:
            cls._fail_minute[phone].append(now)
        # Block repeated identical messages
        if cls._identical_msgs[phone] and cls._identical_msgs[phone][-1] == message:
            cls._identical_msgs[phone].append(message)
            if len(cls._identical_msgs[phone]) >= 5:
                cls._banned[phone] = now + 600  # 10 min ban
                log_structured('WARN', 'User banned for repeated identical messages', phone=phone)
                return False, 600
        else:
            cls._identical_msgs[phone].append(message)
        # Rate limit
        cls._msg_minute[phone] = deque([t for t in cls._msg_minute[phone] if now-t < 60], maxlen=10)
        cls._fail_minute[phone] = deque([t for t in cls._fail_minute[phone] if now-t < 60], maxlen=5)
        if len(cls._msg_minute[phone]) > 10 or len(cls._fail_minute[phone]) > 5:
            cls._banned[phone] = now + 300  # 5 min ban
            log_structured('WARN', 'User temporarily banned for abuse', phone=phone)
            return False, 300
        return True, 0

    @classmethod
    def is_banned(cls, phone):
        return time.time() < cls._banned[phone]
