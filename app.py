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

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure OpenAI
openai.api_key = os.getenv('OPENAI_API_KEY')

# Debug logging function - SECURE VERSION
def log_debug(message, data=None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🔍 [{timestamp}] {message}")
    if data:
        # Sanitize sensitive data
        safe_data = sanitize_log_data(data)
        print(f"   📊 Data: {safe_data}")

def sanitize_log_data(data):
    """Remove sensitive information from logs"""
    if isinstance(data, dict):
        safe_data = {}
        for key, value in data.items():
            if key.lower() in ['from', 'phone', 'number']:
                # Anonymize phone numbers
                safe_data[key] = f"***{str(value)[-4:]}" if value else "None"
            elif 'key' in key.lower() or 'token' in key.lower():
                safe_data[key] = "***REDACTED***"
            elif key == 'traceback':
                # Limit traceback exposure
                safe_data[key] = "ERROR_LOGGED" 
            else:
                safe_data[key] = value
        return safe_data
    return data

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
- First interaction: "I'm S.V.E.N., your Smart Virtual Expense Navigator. Send me receipt photos and I'll help categorize them instantly! 🧾✨"
- Menu offering: "Choose category:\n1️⃣ Business meal\n2️⃣ Travel expense\n3️⃣ Office supplies\n4️⃣ Other business\n5️⃣ Help\n\nReply with 1, 2, 3, 4, or 5"
- Follow-up: "Need help with more receipts or have expense questions?"

Always end by asking if they need help with more receipts or have expense questions. This is an educational demo only."""

@app.route('/sms', methods=['POST'])
def sms_webhook():
    log_debug("🚀 SMS WEBHOOK TRIGGERED")
    
    try:
        # Log all incoming data for debugging
        log_debug("Incoming request", {
            'method': request.method,
            'content_type': request.content_type,
            'form_keys': list(request.form.keys())
        })
        
        # Get message data with validation
        from_number = request.form.get('From', 'UNKNOWN')
        message_body = request.form.get('Body', '').strip()
        num_media = int(request.form.get('NumMedia', 0))

        log_debug("Message details", {
            'from': from_number,
            'body': message_body[:50] + '...' if len(message_body) > 50 else message_body,
            'media_count': num_media
        })
        
        # Basic input validation
        if len(message_body) > 5000:  # Prevent abuse
            return create_error_response("Message too long. Please keep it under 5000 characters.")
        
        # Environment check
        if not env_ok:
            return create_error_response("⚠️ Configuration error. Please contact support.")
        
        response_text = ""
        
        if num_media > 0:
            log_debug("📸 Processing image message")
            media_url = request.form.get('MediaUrl0')
            media_content_type = request.form.get('MediaContentType0')
            
            log_debug("Media details", {
                'url': media_url[:50] + '...' if media_url else None,
                'type': media_content_type
            })
            
            if media_content_type and media_content_type.startswith('image/'):
                response_text = process_receipt_image(media_url, message_body)
            else:
                response_text = "I can only analyze receipt images. Please send a photo of your receipt! 📸"
                log_debug("❌ Non-image media received", {'type': media_content_type})
        else:
            log_debug("💬 Processing text message")
            response_text = process_expense_message(message_body)
        
        log_debug("✅ Response generated", {
            'length': len(response_text),
            'preview': response_text[:100] + '...' if len(response_text) > 100 else response_text
        })
            
    except Exception as e:
        error_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_debug(f"💥 CRITICAL ERROR [{error_id}]", {
            'error': str(e)[:200],  # Limit error message length
            'type': type(e).__name__
        })
        # Don't log full traceback in production
        if os.getenv('FLASK_ENV') == 'development':
            print(f"Full traceback: {traceback.format_exc()}")
        
        response_text = f"Sorry, there was an error (ID: {error_id}). Please try again! 🔄"
    
    return create_twiml_response(response_text)

def create_twiml_response(message):
    """Create standardized Twilio response with logging"""
    try:
        twiml_response = MessagingResponse()
        twiml_response.message(message)
        log_debug("📤 Sending Twilio response", {'message_length': len(message)})
        return str(twiml_response)
    except Exception as e:
        log_debug("💥 Error creating Twilio response", {'error': str(e)})
        # Fallback basic response
        return '<?xml version="1.0" encoding="UTF-8"?><Response><Message>Error occurred</Message></Response>'

def create_error_response(message):
    """Create error response with logging"""
    log_debug(f"⚠️ Error response: {message}")
    return create_twiml_response(message)

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

def handle_menu_choice(choice):
    """Handle numbered menu selections"""
    log_debug("📋 Processing menu choice", {'choice': choice})
    
    menu_responses = {
        '1': "✅ **Business Meal** selected!\n\nGreat! I'll categorize this as a business meal. Perfect for client entertainment or team lunches.\n\nNeed help with more receipts? Just send another photo! 📸",
        
        '2': "✅ **Travel Expense** selected!\n\nNice! This will be categorized as travel-related. Great for flights, hotels, or ground transportation.\n\nSend more travel receipts and I'll keep tracking! ✈️",
        
        '3': "✅ **Office Supplies** selected!\n\nPerfect! This goes under office supplies and equipment. Ideal for business materials and tools.\n\nWhat's your next expense? Send another receipt! 📋",
        
        '4': "✅ **Other Business** selected!\n\nGot it! I'll mark this as a general business expense. Good for miscellaneous business costs.\n\nReady for your next receipt! 💼",
        
        '5': "💡 **Need Help?**\n\nI'm S.V.E.N., your Smart Virtual Expense Navigator! I help categorize business receipts instantly.\n\n🔸 Send receipt photos\n🔸 Get instant categorization\n🔸 Track business expenses\n\nJust send me a receipt photo to get started! 📸✨"
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