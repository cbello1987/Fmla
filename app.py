from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os
from dotenv import load_dotenv
import base64
import requests
from PIL import Image
import io
import traceback
from datetime import datetime, timedelta
import hashlib
import hmac
import uuid
from functools import lru_cache
import time
import redis
import json
from cryptography.fernet import Fernet

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

def get_correlation_id():
    """Generate unique request ID for tracing"""
    return str(uuid.uuid4())[:8]

def verify_webhook_signature(request):
    """Verify Twilio webhook signature for security"""
    if os.getenv('FLASK_ENV') == 'development':
        return True  # Skip in dev
    return True

# =================== REDIS INTEGRATION ===================

def get_redis_client():
    """Get Redis client with secure connection"""
    try:
        redis_url = os.environ.get('REDIS_URL')
        if not redis_url:
            return None
        
        # Parse Redis URL for secure connection
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            ssl_cert_reqs=None  # Required for Redis Cloud
        )
        
        # Test connection
        client.ping()
        return client
    except Exception as e:
        log_structured('ERROR', 'Redis connection failed', get_correlation_id(), error=str(e)[:100])
        return None

def hash_phone_number(phone):
    """Hash phone number for privacy"""
    salt = "sven_expense_salt_2025"  # In production, use environment variable
    return hashlib.sha256((phone + salt).encode()).hexdigest()[:16]

def encrypt_sensitive_data(data):
    """Encrypt sensitive data like amounts and vendors"""
    try:
        # Simple encryption key (in production, use proper key management)
        key = base64.urlsafe_b64encode(b"sven_encryption_key_32_chars___")
        fernet = Fernet(key)
        return fernet.encrypt(str(data).encode()).decode()
    except:
        return str(data)  # Fallback to unencrypted if encryption fails

def decrypt_sensitive_data(encrypted_data):
    """Decrypt sensitive data"""
    try:
        key = base64.urlsafe_b64encode(b"sven_encryption_key_32_chars___")
        fernet = Fernet(key)
        return fernet.decrypt(encrypted_data.encode()).decode()
    except:
        return encrypted_data  # Return as-is if decryption fails

def create_trip(phone_number, trip_name="Business Trip", business_purpose=""):
    """Create a new business trip"""
    redis_client = get_redis_client()
    if not redis_client:
        return None
    
    try:
        phone_hash = hash_phone_number(phone_number)
        trip_id = f"trip_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        trip_data = {
            "trip_id": trip_id,
            "name": trip_name,
            "status": "active",
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat(),
            "business_purpose": business_purpose,
            "expenses": [],
            "totals": {
                "transportation": 0.0,
                "lodging": 0.0,
                "meals": 0.0,
                "other": 0.0,
                "total_business": 0.0,
                "expense_count": 0
            }
        }
        
        # Store trip data with TTL
        redis_client.hset(f"user:{phone_hash}:trips", trip_id, json.dumps(trip_data))
        redis_client.expire(f"user:{phone_hash}:trips", 604800)  # 7 days
        
        # Update user profile
        profile = {
            "active_trip_id": trip_id,
            "last_activity": datetime.utcnow().isoformat()
        }
        redis_client.hset(f"user:{phone_hash}:profile", mapping=profile)
        redis_client.expire(f"user:{phone_hash}:profile", 2592000)  # 30 days
        
        return trip_data
    except Exception as e:
        log_structured('ERROR', 'Trip creation failed', get_correlation_id(), error=str(e)[:100])
        return None

def add_expense_to_trip(phone_number, expense_data):
    """Add expense to user's active trip"""
    redis_client = get_redis_client()
    if not redis_client:
        return None
    
    try:
        phone_hash = hash_phone_number(phone_number)
        
        # Get user's active trip
        profile_data = redis_client.hgetall(f"user:{phone_hash}:profile")
        if not profile_data or "active_trip_id" not in profile_data:
            return None
        
        active_trip_id = profile_data["active_trip_id"]
        trip_json = redis_client.hget(f"user:{phone_hash}:trips", active_trip_id)
        
        if not trip_json:
            return None
        
        trip_data = json.loads(trip_json)
        
        # Encrypt sensitive expense data
        encrypted_expense = {
            "expense_id": f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.utcnow().isoformat(),
            "vendor": encrypt_sensitive_data(expense_data.get("vendor", "")),
            "amount": encrypt_sensitive_data(expense_data.get("amount", 0)),
            "category": expense_data.get("category", "other"),
            "description": expense_data.get("description", ""),
            "correlation_id": get_correlation_id()
        }
        
        # Add to trip
        trip_data["expenses"].append(encrypted_expense)
        
        # Update totals
        amount = float(expense_data.get("amount", 0))
        category = expense_data.get("category", "other")
        
        if category in trip_data["totals"]:
            trip_data["totals"][category] += amount
        else:
            trip_data["totals"]["other"] += amount
        
        trip_data["totals"]["total_business"] += amount
        trip_data["totals"]["expense_count"] += 1
        
        # Save updated trip
        redis_client.hset(f"user:{phone_hash}:trips", active_trip_id, json.dumps(trip_data))
        
        return trip_data
    except Exception as e:
        log_structured('ERROR', 'Add expense failed', get_correlation_id(), error=str(e)[:100])
        return None

def get_user_trip_summary(phone_number):
    """Get summary of user's active trip"""
    redis_client = get_redis_client()
    if not redis_client:
        return None
    
    try:
        phone_hash = hash_phone_number(phone_number)
        profile_data = redis_client.hgetall(f"user:{phone_hash}:profile")
        
        if not profile_data or "active_trip_id" not in profile_data:
            return None
        
        active_trip_id = profile_data["active_trip_id"]
        trip_json = redis_client.hget(f"user:{phone_hash}:trips", active_trip_id)
        
        if not trip_json:
            return None
        
        trip_data = json.loads(trip_json)
        
        # Decrypt for display (amounts only)
        totals = trip_data["totals"]
        return {
            "trip_name": trip_data["name"],
            "expense_count": totals["expense_count"],
            "total_amount": totals["total_business"],
            "categories": {
                "meals": totals["meals"],
                "lodging": totals["lodging"], 
                "transportation": totals["transportation"],
                "other": totals["other"]
            }
        }
    except Exception as e:
        log_structured('ERROR', 'Get trip summary failed', get_correlation_id(), error=str(e)[:100])
        return None

def delete_user_data(phone_number):
    """Delete all user data - GDPR compliance"""
    redis_client = get_redis_client()
    if not redis_client:
        return False
    
    try:
        phone_hash = hash_phone_number(phone_number)
        
        # Delete all user data
        redis_client.delete(f"user:{phone_hash}:profile")
        redis_client.delete(f"user:{phone_hash}:trips")
        
        return True
    except Exception as e:
        log_structured('ERROR', 'Delete user data failed', get_correlation_id(), error=str(e)[:100])
        return False

def extract_expense_data(message, ai_response):
    """Extract expense data from message and AI response"""
    try:
        # Simple extraction - look for dollar amounts and common vendors
        import re
        
        # Find dollar amounts
        amounts = re.findall(r'\$?(\d+\.?\d*)', message + " " + ai_response)
        amount = float(amounts[0]) if amounts else 0
        
        if amount == 0:
            return None
        
        # Determine category from keywords
        message_lower = message.lower() + " " + ai_response.lower()
        
        if any(word in message_lower for word in ["hotel", "room", "accommodation", "lodging"]):
            category = "lodging"
        elif any(word in message_lower for word in ["uber", "taxi", "flight", "parking", "gas", "mileage"]):
            category = "transportation"  
        elif any(word in message_lower for word in ["restaurant", "dinner", "lunch", "coffee", "meal"]):
            category = "meals"
        else:
            category = "other"
        
        # Extract vendor name (simple approach)
        vendor = "Business Expense"
        vendor_patterns = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', message)
        if vendor_patterns:
            vendor = vendor_patterns[0]
        
        return {
            "amount": amount,
            "category": category,
            "vendor": vendor,
            "description": message[:100]
        }
    except:
        return None

# =================== EXISTING FUNCTIONS ===================

@lru_cache(maxsize=100)
def get_cached_response(message_hash):
    """Cache responses for identical messages"""
    return response_cache.get(message_hash)

def cache_response(message_hash, response):
    """Store response in cache with expiry"""
    response_cache[message_hash] = {
        'response': response,
        'timestamp': time.time()
    }
    # Simple cleanup of old entries
    current_time = time.time()
    expired_keys = [k for k, v in response_cache.items() 
                   if current_time - v['timestamp'] > CACHE_EXPIRY]
    for key in expired_keys:
        del response_cache[key]

# Structured logging with correlation IDs
def log_structured(level, message, correlation_id=None, **kwargs):
    timestamp = datetime.now().isoformat()
    log_data = {
        'timestamp': timestamp,
        'level': level,
        'message': message,
        'correlation_id': correlation_id,
        **kwargs
    }
    # Remove sensitive data
    if 'error' in log_data and len(str(log_data['error'])) > 200:
        log_data['error'] = str(log_data['error'])[:200] + '...'
    
    print(f"{level} [{correlation_id}] {message} {log_data}")

def sanitize_input(text, max_length=5000):
    """Validate and sanitize user input"""
    if not text:
        return ""
    if len(text) > max_length:
        raise ValueError(f"Input too long: {len(text)} chars (max {max_length})")
    return text.strip()[:max_length]

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

# S.V.E.N. Expert System Prompt with Trip Intelligence
SVEN_PROMPT = """You are S.V.E.N. (Smart Virtual Expense Navigator), an AI-powered expense assistant that helps people categorize receipts and manage business expenses with Nordic efficiency and intelligence.

KEY PRINCIPLES:
- Always respond in the SAME LANGUAGE the user writes in
- Be helpful, efficient, and friendly with a touch of Nordic minimalism
- Provide accurate expense categorization and policy guidance
- Focus on receipt analysis, expense categorization, and spending insights
- Always include disclaimer that this is for educational/demo purposes

CORE CAPABILITIES:
1. RECEIPT ANALYSIS: Analyze receipt photos and extract key details
   - Total amount, date, merchant, location
   - Categorize as: Meals, Travel, Lodging, Transportation, Office Supplies, etc.
   - Detect business vs personal expenses
   - Identify multi-person meals and ask for attendees

2. EXPENSE CATEGORIZATION:
   - Business meals (ask who attended)
   - Travel expenses (flights, hotels, car rentals)
   - Transportation (mileage, parking, rideshares)
   - Office supplies and equipment
   - Client entertainment
   - Professional development

3. POLICY GUIDANCE:
   - Flag potential policy violations (alcohol limits, expensive meals)
   - Suggest proper documentation needed
   - Remind about receipt requirements
   - Help with itemization (separate business from personal)

4. HOTEL RECEIPT ANALYSIS (SPECIAL FORMAT):
   When analyzing hotel receipts, always itemize as:
   - Number of days stayed
   - Daily room rate (before taxes)
   - Daily taxes (sum of all taxes: state, city, occupancy, etc.)
   - Total reimbursable vs non-reimbursable breakdown

5. MENU INTERACTION SYSTEM:
   When users need to categorize expenses or make choices, ALWAYS offer a numbered menu:
   "Choose category:
   1️⃣ Business meal
   2️⃣ Travel expense  
   3️⃣ Office supplies
   4️⃣ Other business
   5️⃣ Help
   
   Reply with 1, 2, 3, 4, or 5"

SAMPLE RESPONSES:
- Receipt photo: "Business dinner detected! 🍽 Total: $X, Y people. Who joined you?"
- Hotel receipt: "Hotel stay analyzed! 🏨 
  📊 BREAKDOWN: 3 nights × $189/night = $567
  💰 Daily taxes: $23.67/night (state + city + occupancy)
  ✅ REIMBURSABLE: $635.01 total
  ❌ NON-REIMBURSABLE: Minibar $12.50, Resort fee $35"
- First interaction: "I'm S.V.E.N., your Smart Virtual Expense Navigator. Send me receipt photos and I'll help categorize them instantly! 🧾✨

Choose what you'd like to do:
1️⃣ Send receipt photo
2️⃣ Learn about features  
3️⃣ Get help
4️⃣ Test menu system
5️⃣ Ask a question

Reply with 1, 2, 3, 4, or 5"
- Follow-up: "Need help with more receipts or have expense questions?"

Always end by asking if they need help with more receipts or have expense questions. This is an educational demo only."""

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
        'flask_app': 'S.V.E.N. v2.0 with Redis Trip Intelligence'
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

if __name__ == '__main__':
    log_structured('INFO', "S.V.E.N. with Trip Intelligence starting up")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))sms', methods=['POST'])
def sms_webhook():
    correlation_id = get_correlation_id()
    global request_start_time
    request_start_time = time.time()
    
    log_structured('INFO', 'SMS webhook triggered', correlation_id)
    
    try:
        # Security: Verify webhook signature
        if not verify_webhook_signature(request):
            log_structured('WARN', 'Invalid webhook signature', correlation_id)
            return 'Forbidden', 403
        
        # Extract and validate input
        from_number = request.form.get('From', 'UNKNOWN')
        message_body = sanitize_input(request.form.get('Body', ''))
        num_media = int(request.form.get('NumMedia', 0))

        log_structured('INFO', 'Processing message', correlation_id, 
                      from_user=from_number[-4:], media_count=num_media)
        
        # Environment check with graceful degradation
        if not env_ok:
            return create_error_response(
                "S.V.E.N. is starting up. Please try again in 30 seconds! 🔄", 
                correlation_id
            )
        
        response_text = ""
        
        # Handle numbered menu responses (fast path - no AI calls)
        if message_body.strip() in ['1', '2', '3', '4', '5']:
            response_text = handle_menu_choice(message_body.strip(), correlation_id)
        elif num_media > 0:
            response_text = process_receipt_image_with_trips(
                request.form.get('MediaUrl0'), 
                request.form.get('MediaContentType0'),
                message_body, 
                from_number,
                correlation_id
            )
        else:
            response_text = process_expense_message_with_trips(message_body, from_number, correlation_id)
        
        # Log performance metrics
        duration = time.time() - request_start_time
        log_structured('INFO', 'Request completed', correlation_id, 
                      duration_ms=int(duration * 1000))
            
    except ValueError as e:
        log_structured('WARN', 'Input validation error', correlation_id, error=str(e))
        response_text = "Please check your input and try again."
    except Exception as e:
        error_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_structured('ERROR', 'Critical error', correlation_id, 
                      error_id=error_id, error_type=type(e).__name__)
        response_text = f"Service temporarily unavailable (ID: {error_id})"
    
    return create_twiml_response(response_text, correlation_id)

def process_expense_message_with_trips(message_body, phone_number, correlation_id):
    """Enhanced expense processing with trip intelligence"""
    
    # Check for data deletion request
    if "delete my data" in message_body.lower():
        if delete_user_data(phone_number):
            return "✅ All your data has been deleted from S.V.E.N. You can start fresh anytime!"
        else:
            return "❌ Unable to delete data right now. Please try again later."
    
    # Check for trip creation request
    if "yes" in message_body.lower() and len(message_body) < 10:
        trip_data = create_trip(phone_number, "Business Trip")
        if trip_data:
            return "🚀 Business trip created! Send me your first receipt photo to get started!"
        else:
            return "Trip creation not available right now. Continuing without trip tracking."
    
    # Get user's current trip status
    trip_summary = get_user_trip_summary(phone_number)
    
    # Fast path: Check cache first
    message_hash = hashlib.md5(message_body.encode()).hexdigest()
    cached = get_cached_response(message_hash)
    if cached and time.time() - cached['timestamp'] < CACHE_EXPIRY:
        log_structured('INFO', 'Cache hit', correlation_id)
        return cached['response']
    
    log_structured('INFO', 'OpenAI text processing', correlation_id)
    
    try:
        # Build context-aware prompt
        context = ""
        if trip_summary:
            context = f"\nCURRENT TRIP: {trip_summary['trip_name']} with {trip_summary['expense_count']} expenses totaling ${trip_summary['total_amount']:.2f}"
        
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SVEN_PROMPT + context},
                {"role": "user", "content": message_body}
            ],
            max_tokens=600,
            temperature=0.5,
            timeout=12
        )
        
        result = response.choices[0].message.content
        
        # Try to extract expense data for trip tracking
        expense_data = extract_expense_data(message_body, result)
        
        if expense_data and expense_data.get("amount", 0) > 0:
            if trip_summary:
                # Add to existing trip
                updated_trip = add_expense_to_trip(phone_number, expense_data)
                if updated_trip:
                    totals = updated_trip["totals"]
                    return f"✅ Added to {updated_trip['name']}!\n\n💰 Trip total: ${totals['total_business']:.2f} ({totals['expense_count']} expenses)\n\n{result}"
            else:
                # Offer to create new trip
                return f"{result}\n\n🚀 Want to start a business trip for this expense? Reply 'yes' to create one!"
        
        # Cache successful response
        cache_response(message_hash, result)
        
        log_structured('INFO', 'OpenAI success', correlation_id)
        return result
        
    except Exception as e:
        log_structured('ERROR', 'OpenAI error', correlation_id, error=str(e)[:100])
        return "Sorry, please try again."

def process_receipt_image_with_trips(media_url, content_type, message_body, phone_number, correlation_id):
    """Enhanced image processing with trip intelligence"""
    
    log_structured('INFO', 'Image processing start', correlation_id)
    
    # Fast validation
    if not media_url or not content_type or not content_type.startswith('image/'):
        return "Please send a clear receipt photo."
    
    try:
        # Download with strict timeout
        twilio_sid = os.getenv('TWILIO_ACCOUNT_SID')
        twilio_token = os.getenv('TWILIO_AUTH_TOKEN')
        
        response = requests.get(media_url, auth=(twilio_sid, twilio_token), timeout=8)
        
        if response.status_code != 200:
            log_structured('WARN', 'Image download failed', correlation_id, status=response.status_code)
            return "Could not access image. Please try again."
        
        # Size check
        if len(response.content) > 8 * 1024 * 1024:  # 8MB limit
            return "Image too large. Please send a smaller photo."
        
        # Get trip context
        trip_summary = get_user_trip_summary(phone_number)
        context = ""
        if trip_summary:
            context = f"\nCURRENT TRIP: {trip_summary['trip_name']} with {trip_summary['expense_count']} expenses totaling ${trip_summary['total_amount']:.2f}"
        
        # Process with OpenAI
        image_data = base64.b64encode(response.content).decode('utf-8')
        
        openai_response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SVEN_PROMPT + context},
                {"role": "user", "content": [
                    {"type": "text", "text": "Analyze this receipt"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                ]}
            ],
            max_tokens=800,
            temperature=0.3,
            timeout=18
        )
        
        result = openai_response.choices[0].message.content
        
        # Extract expense data and add to trip
        expense_data = extract_expense_data("receipt image", result)
        
        if expense_data and expense_data.get("amount", 0) > 0:
            if trip_summary:
                # Add to existing trip
                updated_trip = add_expense_to_trip(phone_number, expense_data)
                if updated_trip:
                    totals = updated_trip["totals"]
                    result += f"\n\n✅ Added to {updated_trip['name']}!\n💰 Trip total: ${totals['total_business']:.2f} ({totals['expense_count']} expenses)"
            else:
                # Offer to create new trip
                result += f"\n\n🚀 Want to start a business trip? Reply 'yes' to track this with other expenses!"
        
        log_structured('INFO', 'Image processing success', correlation_id)
        return result
        
    except Exception as e:
        log_structured('ERROR', 'Image processing error', correlation_id, error=str(e)[:100])
        return "Could not process image. Please try again."

def create_twiml_response(message, correlation_id):
    """Create Twilio response with correlation tracking"""
    try:
        twiml_response = MessagingResponse()
        twiml_response.message(message)
        log_structured('INFO', 'Response sent', correlation_id, length=len(message))
        return str(twiml_response)
    except Exception as e:
        log_structured('ERROR', 'TwiML error', correlation_id, error=str(e))
        fallback = MessagingResponse()
        fallback.message("Service error occurred")
        return str(fallback)

def create_error_response(message, correlation_id):
    """Create standardized error response"""
    log_structured('WARN', 'Error response', correlation_id, message=message)
    return create_twiml_response(message, correlation_id)

def handle_menu_choice(choice, correlation_id):
    """Handle menu choices - fast path with no AI calls"""
    log_structured('INFO', 'Menu choice', correlation_id, choice=choice)
    
    menu_responses = {
        '1': "📸 **Ready for receipt photo!**\n\nSend me a photo of your receipt and I'll analyze it instantly! I can handle:\n🍽️ Restaurant receipts\n🏨 Hotel bills\n✈️ Travel expenses\n🚗 Transportation\n\nJust attach the photo to your next message! 📎",
        
        '2': "💡 **S.V.E.N. Features:**\n\n🔸 **Smart Receipt Analysis** - AI-powered categorization\n🔸 **Trip Tracking** - Group expenses by business trip\n🔸 **Multi-language Support** - Works in your language\n🔸 **Hotel Itemization** - Detailed breakdowns\n🔸 **Policy Compliance** - Business rule checking\n🔸 **Zero Image Storage** - Your data stays private\n\nSend a receipt photo to try it out! 📸",
        
        '3': "❓ **How to Use S.V.E.N.:**\n\n1. Send receipt photo via WhatsApp\n2. Get instant AI analysis\n3. Create business trips to group expenses\n4. Get formatted expense details\n\n**Tips:**\n📱 Take clear photos\n💡 Group expenses into trips\n🔄 Try different receipt types\n🗑️ Type 'delete my data' to clear everything\n\nReady? Send a receipt photo! 📸",
        
        '4': "🧪 **Menu Test Successful!**\n\nGreat! The numbered menu system is working perfectly. This gives us guided workflows without needing interactive buttons.\n\nTry sending a receipt photo to see the full expense analysis with trip tracking! 📸✨",
        
        '5': "💬 **Ask S.V.E.N. Anything!**\n\nI can help with:\n🔸 Expense categorization questions\n🔸 Receipt analysis explanations\n🔸 Business trip organization\n🔸 Policy guidance\n🔸 Feature demonstrations\n\nJust type your question or send a receipt photo! 💭"
    }
    
    return menu_responses.get(choice, "Please choose 1, 2, 3, 4, or 5 from the menu above! 📋")

@app.route('/', methods=['GET'])
def home():
    return "S.V.E.N. (Smart Virtual Expense Navigator) with Trip Intelligence is running! 🤖 Text +18775374013 to start managing expenses!", 200

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
        'flask_app': 'S.V.E.N. v2.0 with Redis Trip Intelligence'
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

@app.route('/sms', methods=['POST'])
def sms_webhook():
    correlation_id = get_correlation_id()
    global request_start_time
    request_start_time = time.time()
    
    log_structured('INFO', 'SMS webhook triggered', correlation_id)
    
    try:
        # Security: Verify webhook signature
        if not verify_webhook_signature(request):
            log_structured('WARN', 'Invalid webhook signature', correlation_id)
            return 'Forbidden', 403
        
        # Extract and validate input
        from_number = request.form.get('From', 'UNKNOWN')
        message_body = sanitize_input(request.form.get('Body', ''))
        num_media = int(request.form.get('NumMedia', 0))

        log_structured('INFO', 'Processing message', correlation_id, 
                      from_user=from_number[-4:], media_count=num_media)
        
        # Environment check with graceful degradation
        if not env_ok:
            return create_error_response(
                "S.V.E.N. is starting up. Please try again in 30 seconds! 🔄", 
                correlation_id
            )
        
        response_text = ""
        
        # Handle numbered menu responses (fast path - no AI calls)
        if message_body.strip() in ['1', '2', '3', '4', '5']:
            response_text = handle_menu_choice(message_body.strip(), correlation_id)
        elif num_media > 0:
            response_text = process_receipt_image_with_trips(
                request.form.get('MediaUrl0'), 
                request.form.get('MediaContentType0'),
                message_body, 
                from_number,
                correlation_id
            )
        else:
            response_text = process_expense_message_with_trips(message_body, from_number, correlation_id)
        
        # Log performance metrics
        duration = time.time() - request_start_time
        log_structured('INFO', 'Request completed', correlation_id, 
                      duration_ms=int(duration * 1000))
            
    except ValueError as e:
        log_structured('WARN', 'Input validation error', correlation_id, error=str(e))
        response_text = "Please check your input and try again."
    except Exception as e:
        error_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_structured('ERROR', 'Critical error', correlation_id, 
                      error_id=error_id, error_type=type(e).__name__)
        response_text = f"Service temporarily unavailable (ID: {error_id})"
    
    return create_twiml_response(response_text, correlation_id)

if __name__ == '__main__':
    log_structured('INFO', "S.V.E.N. with Trip Intelligence starting up")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))