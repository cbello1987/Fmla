from datetime import datetime

def log_structured(level, message, correlation_id=None, **kwargs):
    timestamp = datetime.now().isoformat()
    log_data = {
        'timestamp': timestamp,
        'level': level,
        'message': message,
        'correlation_id': correlation_id,
        **kwargs
    }
    if 'error' in log_data and len(str(log_data['error'])) > 200:
        log_data['error'] = str(log_data['error'])[:200] + '...'
    print(f"{level} [{correlation_id}] {message} {log_data}")
