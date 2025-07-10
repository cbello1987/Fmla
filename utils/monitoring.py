import psutil
import time
from services.performance_monitor import PerformanceMonitor
from services.rate_limiter import RateLimiter
from services.redis_service import get_redis_client
from utils.logging import log_structured

class Monitoring:
    @staticmethod
    def health_check():
        # Redis
        redis_ok = False
        redis_ping = None
        try:
            client = get_redis_client()
            if client:
                start = time.time()
                redis_ok = client.ping()
                redis_ping = (time.time() - start) * 1000
        except Exception as e:
            log_structured('ERROR', 'Redis health check failed', error=str(e))
        # Memory
        mem = psutil.virtual_memory()
        # Performance
        perf = PerformanceMonitor.get_all_stats()
        return {
            'redis_ok': redis_ok,
            'redis_ping_ms': redis_ping,
            'memory_used_mb': mem.used // 1024 // 1024,
            'memory_percent': mem.percent,
            'performance': perf,
        }

    @staticmethod
    def rate_limit_status(phone):
        return RateLimiter.get_status(phone)

    @staticmethod
    def log_periodic_health():
        health = Monitoring.health_check()
        log_structured('INFO', 'Periodic health', **health)
