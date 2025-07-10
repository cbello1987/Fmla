import threading
import time
from collections import OrderedDict
from services.config import SVENConfig
from utils.logging import log_structured

class LRUCache:
    def __init__(self, max_size=1000, ttl=3600):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.cache:
                value, expires = self.cache.pop(key)
                if expires > time.time():
                    self.cache[key] = (value, expires)
                    return value
                else:
                    del self.cache[key]
            return None

    def set(self, key, value):
        with self.lock:
            expires = time.time() + self.ttl
            if key in self.cache:
                self.cache.pop(key)
            elif len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
            self.cache[key] = (value, expires)

    def clear(self):
        with self.lock:
            self.cache.clear()

class CacheOptimizer:
    """
    Memory and Redis cache for hot user profiles, response templates, and voice transcriptions.
    """
    user_profile_cache = LRUCache(max_size=SVENConfig.REDIS_CACHE_SIZE, ttl=SVENConfig.REDIS_PROFILE_TTL)
    response_template_cache = LRUCache(max_size=100, ttl=3600)
    voice_transcription_cache = LRUCache(max_size=100, ttl=86400)

    @classmethod
    def get_user_profile(cls, phone, fetch_func):
        cached = cls.user_profile_cache.get(phone)
        if cached:
            log_structured('INFO', 'Cache hit', cache='user_profile', phone=phone)
            return cached
        profile = fetch_func(phone)
        cls.user_profile_cache.set(phone, profile)
        log_structured('INFO', 'Cache miss', cache='user_profile', phone=phone)
        return profile

    @classmethod
    def invalidate_user_profile(cls, phone):
        cls.user_profile_cache.cache.pop(phone, None)

    @classmethod
    def get_response_template(cls, key, fetch_func):
        cached = cls.response_template_cache.get(key)
        if cached:
            return cached
        template = fetch_func(key)
        cls.response_template_cache.set(key, template)
        return template

    @classmethod
    def get_voice_transcription(cls, audio_url, fetch_func):
        cached = cls.voice_transcription_cache.get(audio_url)
        if cached:
            return cached
        transcription = fetch_func(audio_url)
        cls.voice_transcription_cache.set(audio_url, transcription)
        return transcription

    @classmethod
    def cleanup_temp_files(cls, filepaths):
        import os
        for f in filepaths:
            try:
                os.remove(f)
                log_structured('INFO', 'Temp file removed', file=f)
            except Exception as e:
                log_structured('ERROR', 'Temp file cleanup failed', file=f, error=str(e))
