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

4. CONVERSATION PATTERNS:
   - Photo → "Business dinner detected! 🍽 Total: $X, Y people. Who joined you?"
   - Follow-up → Context building and proper categorization
   - Guidance → Real-time policy checking and suggestions

SAMPLE RESPONSES:
- Receipt photo: "Hotel receipt analyzed! 📊 REIMBURSABLE: Room $189 ✅ NON-REIMBURSABLE: Minibar $12.50 ❌"
- Greeting: "Hello! I'm S.V.E.N., your Smart Virtual Expense Navigator. Send me receipt photos and I'll help categorize them instantly! 🧾✨"

Always end by asking if they need help with more receipts or have expense questions. This is an educational demo only."""

@app.route('/sms', methods=['POST'])
def sms_webhook():
    try:
        # Get message data
        from_number = request.form.get('From')
        message_body = request.form.get('Body', '')
        num_media = int(request.form.get('NumMedia', 0))
        
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

def process_text_message(message_body):
    """Process text-only messages"""
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SVEN_PROMPT},
                {"role": "user", "content": message_body}
            ],
            max_tokens=1000,
            temperature=0.7
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
    """Process receipt images with comprehensive error handling"""
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
        
        # Create the prompt for receipt analysis
        user_prompt = f"User's question: {message_body}" if message_body else "Please analyze this receipt for expense categorization"
        
        log_debug("📡 Calling OpenAI Vision API")
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SVEN_PROMPT},
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": media_url}}
                    ]
                }
            ],
            max_tokens=1200,
            temperature=0.7
        )
        
        result = response.choices[0].message.content
        log_debug("✅ Vision API response received", {
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
        log_debug("💥 Unexpected error in image processing", {
            'error': str(e),
            'traceback': traceback.format_exc()
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

if __name__ == '__main__':
    log_debug("🚀 S.V.E.N. starting up")
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    