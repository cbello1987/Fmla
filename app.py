from flask import Flask, request
from dotenv import load_dotenv
import openai
import os
import time
from datetime import datetime
import requests
import json
from twilio.twiml.messaging_response import MessagingResponse

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


# =================== MESSAGE PROCESSING ===================

def process_expense_message_with_trips(message_body, phone_number, correlation_id):
    """Enhanced expense processing with trip intelligence and improved UX"""
    message_lower = message_body.lower().strip()
    # Accept more confirmations
    confirm_responses = ["yes", "ok", "👍", "confirm", "y"]
    cancel_responses = ["no", "cancel", "edit", "n", "❌"]

    # Check for email setup command
    if message_lower.startswith("setup email"):
        parts = message_body.split()
        if len(parts) >= 3:
            email = ' '.join(parts[2:]).strip()
            if "@" in email and "." in email:
                if store_user_email(phone_number, email):
                    test_event = {
                        'activity': 'S.V.E.N. Setup Test',
                        'day': 'Today',
                        'time': datetime.now().strftime('%I:%M %p'),
                        'child': 'Setup verification'
                    }
                    if send_to_skylight_sendgrid(test_event, phone_number, correlation_id, email):
                        return (f"✅ Perfect! I've sent a test email to: {email}\n\nCheck your Skylight - you should see a test event!\n\nNow you can send voice messages about real events! 🎤\n\n🔒 Your data is private. Type 'delete my data' anytime.")
                    else:
                        return (f"✅ Email saved: {email}\n\n⚠️ I couldn't send a test email. I'll try again with your first real event!\n\n🔒 Your data is private. Type 'delete my data' anytime.")
                else:
                    return f"✅ Email noted: {email}\n\nNow send a voice message about an event! 🎤"
            else:
                return "❌ That doesn't look like a valid email. Please try again:\nsetup email your-calendar@skylight.frame"
        else:
            return "❌ Please include your Skylight email:\nsetup email your-calendar@skylight.frame"

    # Accept more confirmation/cancellation responses
    if message_lower in confirm_responses:
        pending_event = get_pending_event(phone_number)
        if pending_event:
            success = send_to_skylight_sendgrid(pending_event, phone_number, correlation_id)
            if success:
                clear_pending_event(phone_number)
                user_email = get_user_skylight_email(phone_number) or "your Skylight"
                return (f"✅ Event sent to {user_email}! You'll see it in ~30 seconds. 📺\n\n🎉 Your family scheduling just got easier!\n\nWhat next?\n• Add another\n• Show my week\n• Help\n\n🔒 Your data is private. Type 'delete my data' anytime.")
            else:
                return ("❌ I couldn't send the email to Skylight.\n\n"
                        "Please check:\n"
                        "1. Your Skylight email is correct\n"
                        "2. Check spam/junk folder\n\n"
                        "Your event details:\n"
                        f"📅 {pending_event.get('activity')} for {pending_event.get('child', 'your child')}\n"
                        f"🕐 {pending_event.get('day')} at {pending_event.get('time')}\n\n"
                        "🔒 Your data is private. Type 'delete my data' anytime.")
        else:
            return "🤔 I don't have any pending events to confirm. Try sending a voice message!"
    if message_lower in cancel_responses:
        clear_pending_event(phone_number)
        return "❌ Event cancelled. No changes made.\n\nYou can send a new voice message or type 'menu' for options."

    # Data deletion
    if "delete my data" in message_lower:
        if delete_user_data(phone_number):
            return "✅ All your data has been deleted from S.V.E.N. You can start fresh anytime!"
        else:
            return "❌ Unable to delete data right now. Please try again later."

    # Family setup
    if "my kids are" in message_lower:
        return ("✅ Great! I'll help you manage your family's schedule. First, set up your email with 'setup email your-calendar@skylight.frame', then send voice messages! 🎤\n\n🔒 Your data is private. Type 'delete my data' anytime.")

    # Greetings
    if message_lower in ["hi", "hello", "hey"]:
        return ("👋 Hi! I'm S.V.E.N., your family scheduling assistant! I help manage kids' activities. Type 'menu' to get started!\n\n🔒 Your data is private. Type 'delete my data' anytime.")

    # Menu/help
    if message_lower in ["menu", "help"]:
        return ("I'm S.V.E.N., your Smart Virtual Event Navigator! 📅✨\n\nChoose what you'd like to do:\n1️⃣ Set up your email for calendar\n2️⃣ Learn about voice features  \n3️⃣ How S.V.E.N. works\n4️⃣ Test voice message\n5️⃣ Ask a question\n\nReply with 1, 2, 3, 4, or 5.\n\n🔒 Your data is private. Type 'delete my data' anytime.")

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
        return response.choices[0].message.content + "\n\n🔒 Your data is private. Type 'delete my data' anytime."
    except Exception as e:
        log_structured('ERROR', 'OpenAI error', correlation_id, error=str(e)[:100])
        return "Sorry, I couldn't process that. Please try again!\n\n🔒 Your data is private. Type 'delete my data' anytime."

def process_voice_message(audio_url, phone_number, correlation_id):
    """Process voice messages and convert to text for event extraction (improved UX)"""
    try:
        # Download the audio file with auth
        auth = (os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        audio_response = requests.get(audio_url, auth=auth, timeout=10)
        
        if audio_response.status_code != 200:
            log_structured('ERROR', 'Audio download failed', correlation_id, status=audio_response.status_code)
            return "Sorry, I couldn't access the voice message. Please try again! 🎤\n\n🔒 Your data is private. Type 'delete my data' anytime."

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
            
            confirmation += ("\n✅ Reply 'yes', 'ok', or 👍 to add to calendar, "
                             "or reply 'no', 'cancel', or 'edit' to discard or change.\n"
                             "You can also type changes directly!\n\n"
                             "🔒 Your data is private. Type 'delete my data' anytime.")
            
            # Store event data temporarily in Redis for confirmation
            store_pending_event(phone_number, event_data, correlation_id)
            
            return confirmation
        else:
            return (f"🎤 I heard: \"{transcript.text}\"\n\n"
                    "🤔 I couldn't understand the event details. Please try saying:\n"
                    "• 'Soccer practice Thursday at 4:30'\n"
                    "• 'Emma has piano Monday 3pm'\n"
                    "• 'Dentist for Jack tomorrow at 2'\n\n"
                    "Or type your event details.\n\n"
                    "🔒 Your data is private. Type 'delete my data' anytime.")
    except Exception as e:
        log_structured('ERROR', 'Voice processing failed', correlation_id, error=str(e)[:200])
        return "Sorry, I had trouble with that voice message. Please try again! 🎤\n\n🔒 Your data is private. Type 'delete my data' anytime."
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