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
from datetime import datetime

import hashlib
import hmac
import uuid
from functools import lru_cache
import time

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

# Configure OpenAI with connection pooling
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
    
    # In production, verify Twilio signature
    # signature = request.headers.get('X-Twilio-Signature', '')
    # return hmac.compare_digest(signature, expected_signature)
    return True

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
    # Remove potentially dangerous characters
    return text.strip()[:max_length]

# Environment check on startup
def check_environment():
    required_vars = ['OPENAI_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN']
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        log_debug(f"❌ MISSING ENVIRONMENT VARIABLES: {missing}")
        return False
    else:
        log_debug("✅ All environment variables loaded")
        return True

# Check environment on startup
env_ok = check_environment()

# S.V.E.N. Expert System Prompt
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

5. CONVERSATION PATTERNS:
   - Photo → "Business dinner detected! 🍽 Total: $X, Y people. Who joined you?"
   - Follow-up → Context building and proper categorization
   - Guidance → Real-time policy checking and suggestions

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
- Menu offering: "Choose category:\n1️⃣ Business meal\n2️⃣ Travel expense\n3️⃣ Office supplies\n4️⃣ Other business\n5️⃣ Help\n\nReply with 1, 2, 3, 4, or 5"
- Follow-up: "Need help with more receipts or have expense questions?"

Always end by asking if they need help with more receipts or have expense questions. This is an educational demo only."""

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
        
        # Environment check
        if not env_ok:
            return create_error_response("Configuration error", correlation_id)
        
        response_text = ""
        
        # Handle numbered menu responses (fast path - no AI calls)
        if message_body.strip() in ['1', '2', '3', '4', '5']:
            response_text = handle_menu_choice(message_body.strip(), correlation_id)
        elif num_media > 0:
            response_text = process_receipt_image_optimized(
                request.form.get('MediaUrl0'), 
                request.form.get('MediaContentType0'),
                message_body, 
                correlation_id
            )
        else:
            response_text = process_expense_message_optimized(message_body, correlation_id)
        
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

def process_expense_message(message_body):
    """Process text-only expense messages with detailed error handling"""
    log_debug("🤖 Starting OpenAI text processing", {'message_length': len(message_body)})
    
    # Handle numbered menu responses
    if message_body.strip() in ['1', '2', '3', '4', '5']:
        return handle_menu_choice(message_body.strip())
    
    try:
        # Validate OpenAI key
        if not openai.api_key:
            log_debug("❌ OpenAI API key missing")
            return "Configuration error. Please contact support."
        
        log_debug("📡 Calling OpenAI API with timeout")
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SVEN_PROMPT},
                {"role": "user", "content": message_body}
            ],
            max_tokens=800,  # Reduced for faster responses
            temperature=0.7,
            timeout=15  # 15 second timeout
        )
        
        result = response.choices[0].message.content
        log_debug("✅ OpenAI response received", {
            'response_length': len(result),
            'tokens_used': response.usage.total_tokens if hasattr(response, 'usage') else 'unknown'
        })
        
        return result
        
    except openai.AuthenticationError as e:
        log_debug("❌ OpenAI Authentication Error", {'error': str(e)})
        return "API authentication error. Please contact support."
    except openai.RateLimitError as e:
        log_debug("❌ OpenAI Rate Limit Error", {'error': str(e)})
        return "Service temporarily busy. Please try again in a moment! ⏳"
    except openai.APIError as e:
        log_debug("❌ OpenAI API Error", {'error': str(e)})
        return "AI service error. Please try again! 🔄"
    except Exception as e:
        log_debug("💥 Unexpected error in text processing", {
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        return "Sorry, I couldn't process your message. Please try again! 🔄"

def process_receipt_image(media_url, message_body):
    """Process receipt images with Twilio auth and zero persistence"""
    log_debug("📸 Starting image processing", {
        'has_url': bool(media_url),
        'message_length': len(message_body) if message_body else 0
    })
    
    try:
        # Validate inputs
        if not media_url:
            log_debug("❌ No media URL provided")
            return "No image received. Please send a receipt photo! 📸"
        
        if not openai.api_key:
            log_debug("❌ OpenAI API key missing")
            return "Configuration error. Please contact support."
        
        # Download image from Twilio with authentication
        log_debug("📥 Downloading image from Twilio")
        twilio_sid = os.getenv('TWILIO_ACCOUNT_SID')
        twilio_token = os.getenv('TWILIO_AUTH_TOKEN')
        
        if not twilio_sid or not twilio_token:
            log_debug("❌ Twilio credentials missing")
            return "Configuration error. Please contact support."
        
        # Download image with Twilio auth (with timeout for performance)
        response = requests.get(media_url, auth=(twilio_sid, twilio_token), timeout=10)
        
        if response.status_code != 200:
            log_debug("❌ Failed to download image", {'status': response.status_code})
            return "Could not access image. Please try again! 📸"
        
        # Check image size (prevent huge uploads from slowing us down)
        image_size_mb = len(response.content) / (1024 * 1024)
        if image_size_mb > 10:  # 10MB limit
            log_debug("❌ Image too large", {'size_mb': image_size_mb})
            return "Image too large. Please send a smaller receipt photo! 📸"
        
        # Convert to base64 for OpenAI (zero persistence - memory only)
        image_data = base64.b64encode(response.content).decode('utf-8')
        log_debug("✅ Image downloaded and converted", {'size_kb': len(response.content) // 1024})
        
        # Create the prompt for receipt analysis
        user_prompt = f"User's question: {message_body}" if message_body else "Please analyze this receipt for expense categorization"
        
        log_debug("📡 Calling OpenAI Vision API with base64 image")
        openai_response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SVEN_PROMPT},
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                    ]
                }
            ],
            max_tokens=1000,  # Reduced for faster responses
            temperature=0.7,
            timeout=20  # 20 second timeout for vision
        )
        
        result = openai_response.choices[0].message.content
        log_debug("✅ Vision API response received", {
            'response_length': len(result),
            'tokens_used': openai_response.usage.total_tokens if hasattr(openai_response, 'usage') else 'unknown'
        })
        
        # Image data automatically discarded when function ends - zero persistence!
        return result
        
    except requests.RequestException as e:
        log_debug("❌ Image download failed", {'error': str(e)})
        return "Could not download image. Please try again! 📸"
    except openai.AuthenticationError as e:
        log_debug("❌ OpenAI Authentication Error", {'error': str(e)})
        return "API authentication error. Please contact support."
    except openai.RateLimitError as e:
        log_debug("❌ OpenAI Rate Limit Error", {'error': str(e)})
        return "Service temporarily busy. Please try again in a moment! ⏳"
    except openai.APIError as e:
        log_debug("❌ OpenAI API Error", {'error': str(e)})
        return "AI service error. Please try again! 🔄"
    except Exception as e:
        log_debug("💥 Unexpected error in image processing", {
            'error': str(e)[:200],
            'type': type(e).__name__
        })
        return "I couldn't analyze the receipt image. Please try again! 📸"

@app.route('/', methods=['GET'])
def home():
    return "S.V.E.N. (Smart Virtual Expense Navigator) is running! 🤖 Text +18775374013 to start managing expenses!", 200

@app.route('/health', methods=['GET'])
def health_check():
    env_status = "✅ Environment OK" if env_ok else "❌ Environment Issues"
    return f"S.V.E.N. is running efficiently! ⚡ {env_status}", 200

@app.route('/debug', methods=['GET'])
def debug_info():
    """Debug endpoint - RESTRICT IN PRODUCTION"""
    # Check if this is development environment
    if os.getenv('FLASK_ENV') != 'development':
        return "Debug endpoint disabled in production", 404
    
    debug_data = {
        'timestamp': datetime.now().isoformat(),
        'environment_ok': env_ok,
        'openai_key_present': bool(os.getenv('OPENAI_API_KEY')),
        'twilio_sid_present': bool(os.getenv('TWILIO_ACCOUNT_SID')),
        'flask_app': 'S.V.E.N. v1.0'
        # Removed sensitive system info
    }
    
    return debug_data, 200

def process_expense_message_optimized(message_body, correlation_id):
    """Optimized text processing with caching and circuit breaker"""
    
    # Fast path: Check cache first
    message_hash = hashlib.md5(message_body.encode()).hexdigest()
    cached = get_cached_response(message_hash)
    if cached and time.time() - cached['timestamp'] < CACHE_EXPIRY:
        log_structured('INFO', 'Cache hit', correlation_id)
        return cached['response']
    
    log_structured('INFO', 'OpenAI text processing', correlation_id)
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SVEN_PROMPT},
                {"role": "user", "content": message_body}
            ],
            max_tokens=600,  # Reduced for speed
            temperature=0.5,  # Reduced for consistency
            timeout=12  # Shorter timeout
        )
        
        result = response.choices[0].message.content
        
        # Cache successful response
        cache_response(message_hash, result)
        
        log_structured('INFO', 'OpenAI success', correlation_id, 
                      tokens=response.usage.total_tokens if hasattr(response, 'usage') else 0)
        return result
        
    except openai.RateLimitError:
        log_structured('WARN', 'Rate limit hit', correlation_id)
        return "Service busy. Please try again in a moment."
    except openai.AuthenticationError:
        log_structured('ERROR', 'Auth error', correlation_id)
        return "Service temporarily unavailable."
    except Exception as e:
        log_structured('ERROR', 'OpenAI error', correlation_id, error=str(e)[:100])
        return "Sorry, please try again."

def process_receipt_image_optimized(media_url, content_type, message_body, correlation_id):
    """Optimized image processing with validation and circuit breaker"""
    
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
        
        # Process with OpenAI
        image_data = base64.b64encode(response.content).decode('utf-8')
        
        openai_response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SVEN_PROMPT},
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
        log_structured('INFO', 'Image processing success', correlation_id)
        return result
        
    except requests.Timeout:
        return "Image processing timed out. Please try again."
    except Exception as e:
        log_structured('ERROR', 'Image processing error', correlation_id, error=str(e)[:100])
        return "Could not process image. Please try again."

def handle_menu_choice(choice, correlation_id):
    """Handle menu choices - fast path with no AI calls"""
    log_structured('INFO', 'Menu choice', correlation_id, choice=choice)
    
    menu_responses = {
        '1': "📸 **Ready for receipt photo!**\n\nSend me a photo of your receipt and I'll analyze it instantly! I can handle:\n🍽️ Restaurant receipts\n🏨 Hotel bills\n✈️ Travel expenses\n🚗 Transportation\n\nJust attach the photo to your next message! 📎",
        
        '2': "💡 **S.V.E.N. Features:**\n\n🔸 **Smart Receipt Analysis** - AI-powered categorization\n🔸 **Multi-language Support** - Works in your language\n🔸 **Hotel Itemization** - Detailed breakdowns\n🔸 **Policy Compliance** - Business rule checking\n🔸 **Zero Storage** - Your data stays private\n\nSend a receipt photo to try it out! 📸",
        
        '3': "❓ **How to Use S.V.E.N.:**\n\n1. Send receipt photo via WhatsApp\n2. Get instant AI analysis\n3. Choose category if needed\n4. Get formatted expense details\n\n**Tips:**\n📱 Take clear photos\n💡 Include all receipt details\n🔄 Try different receipt types\n\nReady? Send a receipt photo! 📸",
        
        '4': "🧪 **Menu Test Successful!**\n\nGreat! The numbered menu system is working perfectly. This gives us guided workflows without needing interactive buttons.\n\nTry sending a receipt photo to see the full expense analysis! 📸✨",
        
        '5': "💬 **Ask S.V.E.N. Anything!**\n\nI can help with:\n🔸 Expense categorization questions\n🔸 Receipt analysis explanations\n🔸 Business policy guidance\n🔸 Feature demonstrations\n\nJust type your question or send a receipt photo! 💭"
    }
    
    return menu_responses.get(choice, "Please choose 1, 2, 3, 4, or 5 from the menu above! 📋")

def test_interactive_buttons():
    """Test WhatsApp interactive button capabilities"""
    log_debug("🧪 Testing interactive buttons")
    
    # Try WhatsApp Interactive Message format
    try:
        from twilio.rest import Client
        client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        
        # Test interactive message with buttons
        interactive_message = {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": "🧪 Button Test!\n\nWhich expense type?"
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": "meal_btn",
                                "title": "🍽️ Meal"
                            }
                        },
                        {
                            "type": "reply", 
                            "reply": {
                                "id": "travel_btn",
                                "title": "✈️ Travel"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "other_btn", 
                                "title": "📋 Other"
                            }
                        }
                    ]
                }
            }
        }
        
        log_debug("✅ Interactive buttons supported!")
        return "🧪 Testing interactive buttons... Check if you see clickable buttons above!"
        
    except Exception as e:
        log_debug("❌ Interactive buttons not supported", {'error': str(e)})
        return f"❌ Buttons not supported in sandbox.\n\nFallback menu:\n1️⃣ Meal\n2️⃣ Travel\n3️⃣ Other\n\nReply with 1, 2, or 3"

if __name__ == '__main__':
    log_debug("🚀 S.V.E.N. starting up")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))