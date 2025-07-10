
from flask import Flask, request
from dotenv import load_dotenv
import openai
import os
import time
from datetime import datetime
import requests
import json
from twilio.twiml.messaging_response import MessagingResponse
from services.message_processor import MessageProcessor

# Import helpers and services
from utils.helpers import get_correlation_id, sanitize_input, sanitize_family_input, verify_webhook_signature
from utils.logging import log_structured
from services.redis_service import (
    get_redis_client, hash_phone_number, delete_user_data, store_pending_event, get_pending_event, clear_pending_event, store_user_email, get_user_skylight_email, get_user_profile, store_user_name
)
from services.email_service import send_to_skylight_sendgrid

# Load environment variables
load_dotenv()


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

# Configure OpenAI
openai.api_key = os.getenv('OPENAI_API_KEY')

# Performance monitoring
request_start_time = None

# Simple in-memory cache for responses (production: use Redis)
response_cache = {}
CACHE_EXPIRY = 3600  # 1 hour


# =================== LOGGING ===================


# Environment check on startup
def check_environment():
    required_vars = ['OPENAI_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN']
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        log_structured('ERROR', f"Missing env vars: {missing}")
        return False
    else:
        log_structured('INFO', "All environment variables loaded")
        return True

# Check environment on startup
env_ok = check_environment()


# =================== STATUS ENDPOINTS ===================

@app.route('/', methods=['GET'])
def home():
   return "S.V.E.N. (Smart Virtual Event Navigator) is running! 🤖 Text +18775374013 to start!", 200

@app.route('/ping', methods=['GET'])
def ping():
   """Simple keep-alive endpoint"""
   return {'status': 'alive', 'timestamp': datetime.now().isoformat()}, 200

@app.route('/health', methods=['GET'])
def health_check():
   """Comprehensive health check"""
   health_data = {
       'status': 'healthy',
       'timestamp': datetime.now().isoformat(),
       'environment_ok': env_ok,
       'cache_size': len(response_cache),
       'memory_usage': f"{len(str(response_cache)) / 1024:.1f}KB"
   }
   
   # Test Redis connectivity
   try:
       redis_client = get_redis_client()
       if redis_client:
           health_data['redis_status'] = 'connected'
       else:
           health_data['redis_status'] = 'disconnected'
   except:
       health_data['redis_status'] = 'error'
   
   # Test OpenAI connectivity
   try:
       if not openai.api_key:
           health_data['openai_status'] = 'no_key'
       else:
           health_data['openai_status'] = 'ready'
   except:
       health_data['openai_status'] = 'error'
   
   # Test SendGrid connectivity
   try:
       if os.getenv('SENDGRID_API_KEY'):
           health_data['sendgrid_status'] = 'configured'
       else:
           health_data['sendgrid_status'] = 'not_configured'
   except:
       health_data['sendgrid_status'] = 'error'
   
   status_code = 200 if env_ok else 503
   return health_data, status_code

@app.route('/debug', methods=['GET'])
def debug_info():
   """Debug endpoint - RESTRICT IN PRODUCTION"""
   if os.getenv('FLASK_ENV') != 'development':
       return "Debug endpoint disabled in production", 404
   
   debug_data = {
       'timestamp': datetime.now().isoformat(),
       'environment_ok': env_ok,
       'openai_key_present': bool(os.getenv('OPENAI_API_KEY')),
       'twilio_sid_present': bool(os.getenv('TWILIO_ACCOUNT_SID')),
       'redis_url_present': bool(os.getenv('REDIS_URL')),
       'sendgrid_key_present': bool(os.getenv('SENDGRID_API_KEY')),
       'flask_app': 'S.V.E.N. v2.0 Family Assistant with SendGrid'
   }
   
   # Test Redis connection in debug
   try:
       redis_client = get_redis_client()
       if redis_client:
           debug_data['redis_test'] = 'success'
           debug_data['redis_info'] = redis_client.info('server')['redis_version']
       else:
           debug_data['redis_test'] = 'failed'
   except Exception as e:
       debug_data['redis_test'] = f'error: {str(e)[:50]}'
   
   return debug_data, 200

@app.route('/test-email', methods=['GET'])
def test_email():
   """Test email configuration - useful for debugging SendGrid"""
   if os.getenv('FLASK_ENV') != 'development':
       return "Test endpoint disabled in production", 404
   
   try:
       test_event = {
           'activity': 'Test Event from S.V.E.N.',
           'child': 'Test Child',
           'day': 'Today',
           'time': datetime.now().strftime('%I:%M %p'),
           'location': 'Test Location'
       }
       
       test_email_address = os.getenv('DEFAULT_SKYLIGHT_EMAIL', 'test@example.com')
       success = send_to_skylight_sendgrid(test_event, 'test-phone', 'test-correlation', test_email_address)
       
       if success:
           return f"Email test successful! Check {test_email_address} for the test event.", 200
       else:
           return "Email test failed. Check logs for details.", 500
           
   except Exception as e:
       return f"Email test error: {str(e)}", 500


# Register blueprints (routes)
from routes.sms import sms_bp
app.register_blueprint(sms_bp)

if __name__ == '__main__':
    log_structured('INFO', "S.V.E.N. Family Assistant starting up with SendGrid")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))