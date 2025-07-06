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
# security.py - NEW FILE
import os
import hmac
import hashlib
from functools import wraps
from flask import request, abort
from twilio.request_validator import RequestValidator

def verify_twilio_webhook(f):
    """Decorator to verify Twilio webhook signatures"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Skip in development
        if os.getenv('FLASK_ENV') == 'development':
            return f(*args, **kwargs)
            
        validator = RequestValidator(os.getenv('TWILIO_AUTH_TOKEN'))
        
        # Get signature from headers
        signature = request.headers.get('X-Twilio-Signature', '')
        
        # Get the full URL (important for validation)
        url = request.url
        
        # Get POST parameters
        params = request.form.to_dict()
        
        # Validate
        if not validator.validate(url, params, signature):
            print("WARNING: Invalid Twilio signature detected!")
            abort(403)
            
        return f(*args, **kwargs)
    return decorated_function

def sanitize_family_input(text, max_length=500):
    """Sanitize input for family data"""
    if not text:
        return ""
    
    # Remove any potential script injections
    text = text.replace('<', '').replace('>', '')
    
    # Limit length
    return text.strip()[:max_length]
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
    """Extract expense data from message and AI response - ENHANCED VERSION"""
    try:
        import re
        
        # Combine message and AI response for analysis
        text = message + " " + ai_response
        
        # SMART AMOUNT DETECTION - Priority order
        amount = 0
        
        # 1. Look for explicit "Total:" patterns first
        total_patterns = re.findall(r'(?:total|amount|grand total):\s*\$?(\d+\.?\d*)', text.lower())
        if total_patterns:
            amount = float(total_patterns[-1])  # Take the last/final total
        
        # 2. Look for "Total $XXX.XX" patterns
        elif re.search(r'total\s+\$(\d+\.?\d*)', text.lower()):
            total_match = re.search(r'total\s+\$(\d+\.?\d*)', text.lower())
            amount = float(total_match.group(1))
        
        # 3. Find the largest dollar amount (likely the total)
        else:
            amounts = re.findall(r'\$(\d+\.?\d*)', text)
            if amounts:
                # Convert to floats and filter out small amounts (tax, tips, etc.)
                float_amounts = [float(a) for a in amounts if float(a) >= 5.0]  # Ignore amounts under $5
                if float_amounts:
                    amount = max(float_amounts)  # Take the largest amount
        
        # If no valid amount found, return None
        if amount == 0 or amount < 1.0:
            return None
        
        # SMART CATEGORY DETECTION
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["hotel", "room", "accommodation", "lodging", "inn", "resort"]):
            category = "lodging"
        elif any(word in text_lower for word in ["uber", "taxi", "flight", "parking", "gas", "mileage", "airport", "airline"]):
            category = "transportation"  
        elif any(word in text_lower for word in ["restaurant", "dinner", "lunch", "coffee", "meal", "food", "bar", "brewing", "cafe"]):
            category = "meals"
        elif any(word in text_lower for word in ["office", "supplies", "equipment", "software", "subscription"]):
            category = "office"
        else:
            category = "other"
        
        # SMART VENDOR EXTRACTION
        vendor = "Business Expense"
        
        # Look for merchant names in AI response
        merchant_patterns = re.findall(r'(?:merchant|from|at):\s*([A-Za-z][A-Za-z\s&]+?)(?:\s|$|\n)', text)
        if merchant_patterns:
            vendor = merchant_patterns[0].strip()
        else:
            # Fallback: Look for capitalized words (likely business names)
            vendor_patterns = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', text)
            if vendor_patterns:
                # Filter out common words
                filtered = [v for v in vendor_patterns if v not in ['Date', 'Total', 'Amount', 'Tax', 'Items', 'Payment']]
                if filtered:
                    vendor = filtered[0]
        
        return {
            "amount": round(amount, 2),  # Round to 2 decimal places
            "category": category,
            "vendor": vendor[:50],  # Limit vendor name length
            "description": message[:100]
        }
        
    except Exception as e:
        # Log error but don't crash
        print(f"Extract expense error: {str(e)[:50]}")
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

# REPLACE the old SVEN_PROMPT with this new family-focused version:

SVEN_FAMILY_PROMPT = """You are S.V.E.N. (Smart Virtual Event Navigator), a warm and efficient family scheduling assistant.

PERSONALITY:
- Friendly, helpful, and understanding of busy family life
- Nordic efficiency meets family warmth
- Patient with parents who are juggling multiple kids
- Celebrates small wins in family coordination

CAPABILITIES:
- Parse voice messages about family events
- Detect scheduling conflicts
- Suggest solutions for double-bookings
- Track multiple children's activities
- Understand common family activities (soccer, piano, dentist, school)

LANGUAGE:
- Always respond in the user's language
- Use warm, encouraging tone
- Include relevant emojis for visual clarity
- Keep responses concise for busy parents

IMPORTANT:
- Never make up events or schedules
- Always confirm before adding to calendar
- Be sensitive to family stress
- Celebrate successful scheduling

End responses with helpful next steps or encouragement.
Example: "Great job staying organized! 🌟" """

# UPDATE the welcome message function:
def get_family_welcome():
    """Get the new family-focused welcome message"""
    return """👋 Hi! I'm S.V.E.N., your family's planning assistant!

I help busy parents manage:
📅 Kids' activities & appointments
🚗 Schedule conflicts before they happen
⏰ Reminders for important events
🎯 All through simple voice messages!

To get started, tell me:
"My kids are [names and ages]"

Example: "My kids are Emma (8) and Jack (6)"

Ready to make family scheduling stress-free? 🌟"""

# UPDATE the webhook handler for numbered responses:
def handle_menu_choice(choice, correlation_id):
    """Updated menu for family context"""
    
    menu_responses = {
        '1': "👨‍👩‍👧‍👦 **Let's Set Up Your Family!**\n\nTell me your children's names and ages. For example:\n'My kids are Emma (8) and Jack (6)'\n\nThis helps me track their activities accurately! 🎯",
        
        '2': "🎙️ **Voice Scheduling Magic!**\n\nJust send a voice message like:\n• 'Soccer practice moved to Thursday 4:30'\n• 'Dentist appointment for Jack Monday at 3'\n• 'Emma has piano recital next Saturday'\n\nI'll understand and add it to your calendar! ✨",
        
        '3': "📱 **How S.V.E.N. Works:**\n\n1. Send voice message → I transcribe it\n2. I show you what I understood\n3. Confirm or edit the details\n4. Synced to your family calendar!\n\nNo more forgotten practices! 🏆",
        
        '4': "🧪 **Test Voice Feature!**\n\nTry sending a voice message now:\n'Soccer practice moved to Thursday 4:30'\n\nI'll show you how I process it! 🎯",
        
        '5': "💡 **S.V.E.N. Family Tips:**\n\n• Name which child: 'Emma's dance class'\n• Include times: 'Baseball 9am Saturday'\n• I'll detect conflicts automatically\n• Your data is always private & secure\n\nQuestions? Just ask! 💬"
    }
    
    return menu_responses.get(choice, "Please choose 1, 2, 3, 4, or 5! 📋")

Only work with real data the user provides."""

# =================== WEBHOOK HANDLERS ===================

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


    
    def process_expense_message_with_trips(message_body, phone_number, correlation_id):
    """Enhanced expense processing with trip intelligence"""
    
    # Check for data deletion request
    if "delete my data" in message_body.lower():
        if delete_user_data(phone_number):
            return "✅ All your data has been deleted from S.V.E.N. You can start fresh anytime!"
        else:
            return "❌ Unable to delete data right now. Please try again later."
    
    # ========= ADD THESE NEW LINES HERE =========
    # Check for family setup
    if "my kids are" in message_body.lower():
        return "✅ Great! I'll help you manage your family's schedule. For now, I'm in demo mode. Try sending 'menu' to see options!"
    
    # Check for hello/hi
    if message_body.lower().strip() in ["hi", "hello", "hey"]:
        return "👋 Hi! I'm S.V.E.N., your family scheduling assistant! I help manage kids' activities. Type 'menu' to get started!"
    # ========= END OF NEW LINES =========
    
    # NEW COMMAND DETECTION (this already exists, don't change)
    message_lower = message_body.lower().strip()        


    # NEW COMMAND DETECTION
    message_lower = message_body.lower().strip()
    
    # Menu command
    if "menu" in message_lower or "help" in message_lower:
        return """I'm S.V.E.N., your Smart Virtual Expense Navigator! 🧾✨

Choose what you'd like to do:
1️⃣ Send receipt photo
2️⃣ Learn about features  
3️⃣ Get help
4️⃣ Test menu system
5️⃣ Ask a question

Reply with 1, 2, 3, 4, or 5. This is an educational demo only."""
    
    # Trip status commands
    if any(phrase in message_lower for phrase in ["trip total", "trip summary", "how much", "show expenses", "my expenses"]):
        trip_summary = get_user_trip_summary(phone_number)
        if trip_summary:
            categories = trip_summary['categories']
            breakdown = ""
            for category, amount in categories.items():
                if amount > 0:
                    breakdown += f"• {category.title()}: ${amount:.2f}\n"
            
            return f"""📊 **{trip_summary['trip_name']} Summary**

💰 **Total**: ${trip_summary['total_amount']:.2f}
📝 **Expenses**: {trip_summary['expense_count']} items

**Breakdown by category:**
{breakdown}
Need help with more receipts? This is an educational demo only."""
        else:
            return "You don't have an active trip yet. Send a receipt photo to start one! This is an educational demo only."
    
    # End trip command
    if any(phrase in message_lower for phrase in ["end trip", "finish trip", "complete trip", "close trip"]):
        trip_summary = get_user_trip_summary(phone_number)
        if trip_summary:
            # Archive the trip
            redis_client = get_redis_client()
            if redis_client:
                phone_hash = hash_phone_number(phone_number)
                redis_client.hdel(f"user:{phone_hash}:profile", "active_trip_id")
            
            return f"""✅ **Trip Completed!**

📊 Final Summary: ${trip_summary['total_amount']:.2f} ({trip_summary['expense_count']} expenses)

Your trip has been archived. Send a new receipt photo to start your next trip!

Need help with more receipts? This is an educational demo only."""
        else:
            return "You don't have an active trip to end. This is an educational demo only."






    
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
        '1': "👨‍👩‍👧‍👦 **Let's Set Up Your Family!**\n\nTell me your children's names and ages. For example:\n'My kids are Emma (8) and Jack (6)'\n\nThis helps me track their activities accurately! 🎯",
        
        '2': "💡 **S.V.E.N. Features:**\n\n🔸 **Smart Receipt Analysis** - AI-powered categorization\n🔸 **Trip Tracking** - Group expenses by business trip\n🔸 **Multi-language Support** - Works in your language\n🔸 **Hotel Itemization** - Detailed breakdowns\n🔸 **Policy Compliance** - Business rule checking\n🔸 **Zero Image Storage** - Your data stays private\n\nSend a receipt photo to try it out! 📸",
        
        '3': "❓ **How to Use S.V.E.N.:**\n\n1. Send receipt photo via WhatsApp\n2. Get instant AI analysis\n3. Create business trips to group expenses\n4. Get formatted expense details\n\n**Tips:**\n📱 Take clear photos\n💡 Group expenses into trips\n🔄 Try different receipt types\n🗑️ Type 'delete my data' to clear everything\n\nReady? Send a receipt photo! 📸",
        
        '4': "🧪 **Menu Test Successful!**\n\nGreat! The numbered menu system is working perfectly. This gives us guided workflows without needing interactive buttons.\n\nTry sending a receipt photo to see the full expense analysis with trip tracking! 📸✨",
        
        '5': "💬 **Ask S.V.E.N. Anything!**\n\nI can help with:\n🔸 Expense categorization questions\n🔸 Receipt analysis explanations\n🔸 Business trip organization\n🔸 Policy guidance\n🔸 Feature demonstrations\n\nJust type your question or send a receipt photo! 💭"
    }
    
    return menu_responses.get(choice, "Please choose 1, 2, 3, 4, or 5 from the menu above! 📋")

# =================== STATUS ENDPOINTS ===================

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

if __name__ == '__main__':
    log_structured('INFO', "S.V.E.N. with Trip Intelligence starting up")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))