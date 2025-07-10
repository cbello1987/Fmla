import time
import threading
from collections import defaultdict, deque
from utils.logging import log_structured

class PerformanceMonitor:
    """
    Tracks response times, error rates, and metrics for S.V.E.N. endpoints and services.
    Thread-safe, supports percentile queries and rolling windows.
    """
    _lock = threading.Lock()
    _metrics = defaultdict(lambda: deque(maxlen=1000))  # endpoint -> deque of (duration_ms, success)
    _errors = defaultdict(int)  # endpoint -> error count
    _calls = defaultdict(int)   # endpoint -> total call count

    @classmethod
    def record(cls, endpoint, duration_ms, success=True):
        with cls._lock:
            cls._metrics[endpoint].append((duration_ms, success))
            cls._calls[endpoint] += 1
            if not success:
                cls._errors[endpoint] += 1
        if duration_ms > 2000:
            log_structured('WARN', 'Slow operation', endpoint=endpoint, duration_ms=duration_ms)

    @classmethod
    def get_stats(cls, endpoint):
        with cls._lock:
            data = list(cls._metrics[endpoint])
        if not data:
            return {'count': 0, 'avg_ms': 0, 'p95_ms': 0, 'error_rate': 0}
        durations = [d[0] for d in data]
        errors = sum(1 for d in data if not d[1])
        avg = sum(durations) / len(durations)
        p95 = sorted(durations)[int(0.95 * len(durations))-1] if len(durations) >= 20 else max(durations)
        error_rate = errors / len(durations)
        return {'count': len(durations), 'avg_ms': avg, 'p95_ms': p95, 'error_rate': error_rate}

    @classmethod
    def get_all_stats(cls):
        return {ep: cls.get_stats(ep) for ep in cls._metrics}
