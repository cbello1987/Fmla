from flask import Flask, request, abort
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
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
from functools import lru_cache, wraps
import time
import redis
import json
from cryptography.fernet import Fernet
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

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
    
    validator = RequestValidator(os.getenv('TWILIO_AUTH_TOKEN'))
    signature = request.headers.get('X-Twilio-Signature', '')
    url = request.url
    params = request.form.to_dict()
    
    if not validator.validate(url, params, signature):
        print("WARNING: Invalid Twilio signature detected!")
        return False
    
    return True

def sanitize_family_input(text, max_length=500):
    """Sanitize input for family data"""
    if not text:
        return ""
    text = text.replace('<', '').replace('>', '')
    return text.strip()[:max_length]

# =================== REDIS INTEGRATION ===================

def get_redis_client():
    """Get Redis client with secure connection"""
    try:
        redis_url = os.environ.get('REDIS_URL')
        if not redis_url:
            return None
        
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        
        client.ping()
        return client
    except Exception as e:
        log_structured('ERROR', 'Redis connection failed', get_correlation_id(), error=str(e)[:100])
        return None

def hash_phone_number(phone):
    """Hash phone number for privacy"""
    salt = os.getenv('PHONE_HASH_SALT', 'sven_family_salt_2025')
    return hashlib.sha256((phone + salt).encode()).hexdigest()[:16]

def encrypt_sensitive_data(data):
    """Encrypt sensitive data like amounts and vendors"""
    try:
        key_string = os.getenv('ENCRYPTION_KEY', 'sven_encryption_key_32_chars___').encode()
        key = base64.urlsafe_b64encode(key_string[:32].ljust(32, b'0'))
        fernet = Fernet(key)
        return fernet.encrypt(str(data).encode()).decode()
    except:
        return str(data)

def decrypt_sensitive_data(encrypted_data):
    """Decrypt sensitive data"""
    try:
        key_string = os.getenv('ENCRYPTION_KEY', 'sven_encryption_key_32_chars___').encode()
        key = base64.urlsafe_b64encode(key_string[:32].ljust(32, b'0'))
        fernet = Fernet(key)
        return fernet.decrypt(encrypted_data.encode()).decode()
    except:
        return encrypted_data

def delete_user_data(phone_number):
    """Delete all user data - GDPR compliance"""
    redis_client = get_redis_client()
    if not redis_client:
        return False
    
    try:
        phone_hash = hash_phone_number(phone_number)
        redis_client.delete(f"user:{phone_hash}:profile")
        redis_client.delete(f"user:{phone_hash}:trips")
        redis_client.delete(f"family:{phone_hash}:profile")
        redis_client.delete(f"family:{phone_hash}:events")
        redis_client.delete(f"pending:{phone_hash}")
        return True
    except Exception as e:
        log_structured('ERROR', 'Delete user data failed', get_correlation_id(), error=str(e)[:100])
        return False

def store_pending_event(phone_number, event_data, correlation_id):
    """Store event data temporarily for confirmation"""
    redis_client = get_redis_client()
    if not redis_client:
        return
    
    try:
        phone_hash = hash_phone_number(phone_number)
        key = f"pending:{phone_hash}"
        redis_client.setex(key, 300, json.dumps(event_data))  # 5 minute expiry
        log_structured('INFO', 'Stored pending event', correlation_id)
    except Exception as e:
        log_structured('ERROR', 'Failed to store pending event', correlation_id, error=str(e))

def get_pending_event(phone_number):
    """Get pending event awaiting confirmation"""
    redis_client = get_redis_client()
    if not redis_client:
        return None
    
    try:
        phone_hash = hash_phone_number(phone_number)
        key = f"pending:{phone_hash}"
        data = redis_client.get(key)
        return json.loads(data) if data else None
    except Exception as e:
        log_structured('ERROR', 'Failed to get pending event', get_correlation_id(), error=str(e))
        return None

def clear_pending_event(phone_number):
    """Clear pending event after confirmation"""
    redis_client = get_redis_client()
    if not redis_client:
        return
    
    try:
        phone_hash = hash_phone_number(phone_number)
        key = f"pending:{phone_hash}"
        redis_client.delete(key)
    except:
        pass

def store_user_email(phone_number, email_address):
    """Store user's Skylight email"""
    redis_client = get_redis_client()
    if not redis_client:
        # Fallback to in-memory storage for MVP
        return False
    
    try:
        phone_hash = hash_phone_number(phone_number)
        user_data = {
            'skylight_email': email_address,
            'setup_date': datetime.now().isoformat()
        }
        redis_client.setex(f"user:{phone_hash}:profile", 
                          30 * 24 * 3600,  # 30 days
                          json.dumps(user_data))
        return True
    except Exception as e:
        log_structured('ERROR', 'Failed to store email', get_correlation_id(), error=str(e))
        return False

def get_user_skylight_email(phone_number):
    """Get user's Skylight email"""
    redis_client = get_redis_client()
    if not redis_client:
        # For MVP without Redis, use environment variable
        return os.getenv('DEFAULT_SKYLIGHT_EMAIL')
    
    try:
        phone_hash = hash_phone_number(phone_number)
        user_data = redis_client.get(f"user:{phone_hash}:profile")
        if user_data:
            return json.loads(user_data).get('skylight_email')
        return None
    except:
        return None

# =================== LOGGING ===================

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

# =================== AI PROMPTS ===================

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

def handle_menu_choice(choice, correlation_id):
    """Updated menu for family context"""
    
    menu_responses = {
        '1': "👨‍👩‍👧‍👦 **Let's Set Up Your Family!**\n\nFirst, I need your Skylight calendar email address.\n\nReply with: setup email your-calendar@skylight.frame\n\nExample: setup email smith-family@skylight.frame",
        
        '2': "🎙️ **Voice Scheduling Magic!**\n\nJust send a voice message like:\n• 'Soccer practice moved to Thursday 4:30'\n• 'Dentist appointment for Jack Monday at 3'\n• 'Emma has piano recital next Saturday'\n\nI'll transcribe it and add to your calendar! ✨",
        
        '3': "📱 **How S.V.E.N. Works:**\n\n1. Set up your Skylight email (option 1)\n2. Send voice message → I transcribe it\n3. Confirm the details\n4. Auto-synced to your Skylight!\n\nNo more forgotten practices! 🏆",
        
        '4': "🧪 **Test Voice Feature!**\n\nFirst, make sure you've set up your email (option 1)!\n\nThen send a voice message:\n'Soccer practice Thursday 4:30'\n\nI'll show you how I process it! 🎯",
        
        '5': "💡 **S.V.E.N. Family Tips:**\n\n• Set up your email first (option 1)\n• Name which child in voice messages\n• Include times and days\n• I'll detect conflicts automatically\n\nQuestions? Just ask! 💬"
    }
    
    return menu_responses.get(choice, "Please choose 1, 2, 3, 4, or 5! 📋")

# =================== SENDGRID EMAIL INTEGRATION ===================

def send_to_skylight_sendgrid(event_data, phone_number, correlation_id, user_email=None):
    """Send event to Skylight via SendGrid"""
    try:
        # Get SendGrid API key and ALWAYS strip whitespace
        sg_api_key = os.getenv('SENDGRID_API_KEY', '').strip()
        
        if not sg_api_key:
            log_structured('ERROR', 'SendGrid API key not configured', correlation_id)
            return False
        
        # Get user's email or use default
        if not user_email:
            user_email = get_user_skylight_email(phone_number)
        
        if not user_email:
            user_email = os.getenv('DEFAULT_SKYLIGHT_EMAIL', '').strip()  # Strip this too!
            
        if not user_email:
            log_structured('ERROR', 'No Skylight email configured', correlation_id)
            return False
        
        # Rest of the function stays the same...
        
        # Format the event for Skylight
        subject = f"Calendar Update: {event_data.get('activity', 'Event')}"
        
        # Build email body - Skylight compatible format
        html_content = f"""
        <html>
        <body>
            <h2>New Event Added</h2>
            <p><strong>Event:</strong> {event_data.get('activity', 'Family Event')}</p>
            <p><strong>Date:</strong> {event_data.get('day', 'Today')}</p>
            <p><strong>Time:</strong> {event_data.get('time', 'TBD')}</p>
        """
        
        if event_data.get('child'):
            html_content += f"<p><strong>For:</strong> {event_data.get('child')}</p>"
        
        if event_data.get('location'):
            html_content += f"<p><strong>Location:</strong> {event_data.get('location')}</p>"
        
        if event_data.get('recurring'):
            html_content += f"<p><strong>Recurring:</strong> {event_data.get('recurring')}</p>"
        
        html_content += """
            <hr>
            <p><small>Added by S.V.E.N. Family Assistant via WhatsApp</small></p>
        </body>
        </html>
        """
        
        # Plain text version
        plain_content = f"""New Event Added

Event: {event_data.get('activity', 'Family Event')}
Date: {event_data.get('day', 'Today')}
Time: {event_data.get('time', 'TBD')}"""
        
        if event_data.get('child'):
            plain_content += f"\nFor: {event_data.get('child')}"
        
        if event_data.get('location'):
            plain_content += f"\nLocation: {event_data.get('location')}"
        
        if event_data.get('recurring'):
            plain_content += f"\nRecurring: {event_data.get('recurring')}"
        
        plain_content += "\n\nAdded by S.V.E.N. Family Assistant"
        
        # Create SendGrid message
        message = Mail(
            from_email=(os.getenv('SENDGRID_FROM_EMAIL', 'sven@family-assistant.com').strip(), 
                       'S.V.E.N. Family Assistant'),
            to_emails=user_email,
            subject=subject,
            plain_text_content=plain_content,
            html_content=html_content
        )
        
        # Add custom headers for better deliverability
        message.reply_to = 'noreply@family-assistant.com'
        
        # Send via SendGrid
        sg_api_key = os.getenv('SENDGRID_API_KEY', '').strip()
        response = sg.send(message)
        
        log_structured('INFO', 'SendGrid email sent', correlation_id, 
                      status_code=response.status_code,
                      to_email=user_email,
                      event=event_data.get('activity'))
        
        return response.status_code in [200, 201, 202]
        
    except Exception as e:
        log_structured('ERROR', 'SendGrid send failed', correlation_id, 
                      error=str(e)[:200], 
                      error_type=type(e).__name__)
        return False

# =================== MESSAGE PROCESSING ===================

def process_expense_message_with_trips(message_body, phone_number, correlation_id):
    """Enhanced expense processing with trip intelligence"""
    
    # Check for email setup command
    if message_body.lower().startswith("setup email"):
        parts = message_body.split()
        if len(parts) >= 3:
            email = ' '.join(parts[2:]).strip()  # Handle emails with spaces and strip whitespace
            if "@" in email and "." in email:
                if store_user_email(phone_number, email):
                    # Send test email to verify
                    test_event = {
                        'activity': 'S.V.E.N. Setup Test',
                        'day': 'Today',
                        'time': datetime.now().strftime('%I:%M %p'),
                        'child': 'Setup verification'
                    }
                    if send_to_skylight_sendgrid(test_event, phone_number, correlation_id, email):
                        return f"✅ Perfect! I've sent a test email to: {email}\n\nCheck your Skylight - you should see a test event!\n\nNow you can send voice messages about real events! 🎤"
                    else:
                        return f"✅ Email saved: {email}\n\n⚠️ I couldn't send a test email. I'll try again with your first real event!"
                else:
                    return f"✅ Email noted: {email}\n\nNow send a voice message about an event! 🎤"
            else:
                return "❌ That doesn't look like a valid email. Please try again:\nsetup email your-calendar@skylight.frame"
        else:
            return "❌ Please include your Skylight email:\nsetup email your-calendar@skylight.frame"
    
    # Check for confirmation
    if message_body.lower().strip() == "yes":
        pending_event = get_pending_event(phone_number)
        if pending_event:
            # Use SendGrid to send!
            success = send_to_skylight_sendgrid(pending_event, phone_number, correlation_id)
            if success:
                clear_pending_event(phone_number)
                user_email = get_user_skylight_email(phone_number) or "your Skylight"
                return f"✅ Event sent to {user_email}! You'll see it in ~30 seconds. 📺\n\n🎉 Your family scheduling just got easier!"
            else:
                return ("❌ I couldn't send the email to Skylight.\n\n"
                       "Please check:\n"
                       "1. Your Skylight email is correct\n"
                       "2. Check spam/junk folder\n\n"
                       "Your event details:\n"
                       f"📅 {pending_event.get('activity')} for {pending_event.get('child', 'your child')}\n"
                       f"🕐 {pending_event.get('day')} at {pending_event.get('time')}")
        else:
            return "🤔 I don't have any pending events to confirm. Try sending a voice message!"
    
    # Check for data deletion request
    if "delete my data" in message_body.lower():
        if delete_user_data(phone_number):
            return "✅ All your data has been deleted from S.V.E.N. You can start fresh anytime!"
        else:
            return "❌ Unable to delete data right now. Please try again later."
    
    # Check for family setup
    if "my kids are" in message_body.lower():
        return "✅ Great! I'll help you manage your family's schedule. First, set up your email with 'setup email your-calendar@skylight.frame', then send voice messages! 🎤"
    
    # Check for hello/hi
    if message_body.lower().strip() in ["hi", "hello", "hey"]:
        return "👋 Hi! I'm S.V.E.N., your family scheduling assistant! I help manage kids' activities. Type 'menu' to get started!"
    
    # Menu command - exact match to avoid confusion
    message_lower = message_body.lower().strip()
    if message_lower == "menu" or message_lower == "help":
        return """I'm S.V.E.N., your Smart Virtual Event Navigator! 📅✨

Choose what you'd like to do:
1️⃣ Set up your email for calendar
2️⃣ Learn about voice features  
3️⃣ How S.V.E.N. works
4️⃣ Test voice message
5️⃣ Ask a question

Reply with 1, 2, 3, 4, or 5."""
    
    # For any other message, pass to the AI
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SVEN_FAMILY_PROMPT},
                {"role": "user", "content": message_body}
            ],
            max_tokens=600,
            temperature=0.5,
            timeout=12
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        log_structured('ERROR', 'OpenAI error', correlation_id, error=str(e)[:100])
        return "Sorry, I couldn't process that. Please try again!"

def process_voice_message(audio_url, phone_number, correlation_id):
    """Process voice messages and convert to text for event extraction"""
    try:
        # Download the audio file with auth
        auth = (os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        audio_response = requests.get(audio_url, auth=auth, timeout=10)
        
        if audio_response.status_code != 200:
            log_structured('ERROR', 'Audio download failed', correlation_id, status=audio_response.status_code)
            return "Sorry, I couldn't access the voice message. Please try again! 🎤"

        # Save audio temporarily
        temp_path = f"/tmp/audio_{correlation_id}.ogg"
        with open(temp_path, "wb") as f:
            f.write(audio_response.content)
        
        # Transcribe with Whisper
        with open(temp_path, "rb") as audio_file:
            transcript = openai.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        
        log_structured('INFO', 'Voice transcribed', correlation_id, text=transcript.text[:100])
        
        # Parse the event from transcript
        event_data = parse_event_from_voice(transcript.text, phone_number)
        
        if event_data:
            # Format confirmation message
            confirmation = f"🎤 I heard: \"{transcript.text}\"\n\n"
            confirmation += "📅 Event details:\n"
            confirmation += f"• Activity: {event_data.get('activity', 'Unknown')}\n"
            
            if event_data.get('child'):
                confirmation += f"• Child: {event_data.get('child')}\n"
            
            confirmation += f"• Day: {event_data.get('day', 'Not specified')}\n"
            confirmation += f"• Time: {event_data.get('time', 'Not specified')}\n"
            
            if event_data.get('location'):
                confirmation += f"• Location: {event_data.get('location')}\n"
            
            if event_data.get('recurring'):
                confirmation += f"• Recurring: {event_data.get('recurring')}\n"
            
            confirmation += "\n✅ Reply 'yes' to add to calendar or tell me what to change!"
            
            # Store event data temporarily in Redis for confirmation
            store_pending_event(phone_number, event_data, correlation_id)
            
            return confirmation
        else:
            return (f"🎤 I heard: \"{transcript.text}\"\n\n"
                   "🤔 I couldn't understand the event details. Please try saying:\n"
                   "• 'Soccer practice Thursday at 4:30'\n"
                   "• 'Emma has piano Monday 3pm'\n"
                   "• 'Dentist for Jack tomorrow at 2'")
            
    except Exception as e:
        log_structured('ERROR', 'Voice processing failed', correlation_id, error=str(e)[:200])
        return "Sorry, I had trouble with that voice message. Please try again! 🎤"
    finally:
        # Clean up temp file
        try:
            if 'temp_path' in locals():
                os.remove(temp_path)
        except:
            pass

def parse_event_from_voice(transcript, phone_number):
    """Use GPT-4 to parse event details from voice transcript"""
    try:
        # Add debug log
        log_structured('INFO', 'Starting event parse', get_correlation_id(), transcript=transcript)
        
        prompt = f"""Extract event details from this voice message about family scheduling.
        
        Voice message: "{transcript}"
        
        Extract these details:
        - activity: What is the event/activity?
        - child: Which child is this for? (if mentioned)
        - day: What day? (e.g., Thursday, tomorrow, Monday, every Monday)
        - time: What time? (e.g., 4:30 PM, 3 o'clock, 7 a.m.)
        - location: Where? (if mentioned)
        - recurring: Is this recurring? (e.g., every Monday)
        
        Return ONLY valid JSON, nothing else.
        
        Example: "piano lessons for Andy at 7 a.m. every Monday" should return:
        {{"activity": "piano lessons", "child": "Andy", "day": "Monday", "time": "7:00 AM", "location": null, "recurring": "every Monday"}}"""
        
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a JSON-only responder. Return ONLY valid JSON, no other text."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.1
        )
        
        # Get the response text
        response_text = response.choices[0].message.content.strip()
        
        # Try to parse the response
        try:
            event_data = json.loads(response_text)
            log_structured('INFO', 'Event parsed successfully', get_correlation_id(), event=event_data)
            return event_data
        except json.JSONDecodeError as je:
            log_structured('ERROR', 'JSON parse failed', get_correlation_id(), 
                          response=response_text[:200], json_error=str(je))
            return None
        
    except Exception as e:
        log_structured('ERROR', 'Event parsing failed', get_correlation_id(), error=str(e)[:100])
        return None

def process_receipt_image_with_trips(media_url, content_type, message_body, phone_number, correlation_id):
    """Process receipt images"""
    return "📸 Photo received! For voice scheduling, please send a voice message instead! 🎤"

# =================== RESPONSE HELPERS ===================

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
        
        # Environment check
        if not env_ok:
            return create_error_response(
                "S.V.E.N. is starting up. Please try again in 30 seconds! 🔄",
                correlation_id
            )
        
        response_text = ""
        
        # Handle numbered menu responses
        if message_body.strip() in ['1', '2', '3', '4', '5']:
            response_text = handle_menu_choice(message_body.strip(), correlation_id)
        
        # Handle voice messages
        elif num_media > 0 and request.form.get('MediaContentType0', '').startswith('audio/'):
            response_text = process_voice_message(
                request.form.get('MediaUrl0'),
                from_number,
                correlation_id
            )
        
        # Handle images
        elif num_media > 0:
            response_text = "📸 Photo received! For voice scheduling, please send a voice message instead! 🎤"
        
        # Handle text messages
        else:
            response_text = process_expense_message_with_trips(
                message_body, 
                from_number,
                correlation_id
            )
        
        # Log performance
        duration = time.time() - request_start_time
        log_structured('INFO', 'Request completed', correlation_id, 
                      duration_ms=int(duration * 1000))
        
        return create_twiml_response(response_text, correlation_id)
            
    except Exception as e:
        error_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_structured('ERROR', 'Critical error', correlation_id, 
                      error_id=error_id, error=str(e)[:200])
        response_text = f"Service temporarily unavailable (ID: {error_id})"
        return create_error_response(response_text, correlation_id)

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

if __name__ == '__main__':
   log_structured('INFO', "S.V.E.N. Family Assistant starting up with SendGrid")
   app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))