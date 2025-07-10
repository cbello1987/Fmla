from flask import Blueprint, request, make_response
from utils.helpers import get_correlation_id, sanitize_input, verify_webhook_signature
from utils.logging import log_structured
from services.redis_service import (
    get_pending_event, clear_pending_event, store_pending_event, delete_user_data, store_user_email, get_user_skylight_email, get_user_profile, store_user_name
)
from services.email_service import send_to_skylight_sendgrid
from services.message_processor import MessageProcessor
from services.user_context_service import UserContextService
from services.user_manager import UserManager
from services.config import SVENConfig
from utils.security import validate_phone, sanitize_message, add_security_headers
from utils.rate_limiting import AntiAbuseLimiter
import os
import time
from datetime import datetime

sms_bp = Blueprint('sms', __name__)

@sms_bp.route('/sms', methods=['POST'])

def sms_webhook():
    from utils.command_matcher import CommandMatcher
    correlation_id = get_correlation_id()
    request_start_time = time.time()
    log_structured('INFO', 'SMS webhook triggered', correlation_id)
    message_processor = MessageProcessor()
    user_context_service = UserContextService()
    user_mgr = UserManager()

    try:
        # Security: Verify webhook signature (always enforce in prod)
        if not verify_webhook_signature(request):
            log_structured('WARN', 'Invalid webhook signature', correlation_id)
            resp = make_response('Forbidden', 403)
            return add_security_headers(resp)

        # Extract and validate input
        from_number = request.form.get('From', 'UNKNOWN')
        message_body = request.form.get('Body', '')
        num_media = int(request.form.get('NumMedia', 0))

        # Input validation and sanitization
        if not validate_phone(from_number):
            log_structured('WARN', 'Invalid phone format', correlation_id)
            resp = make_response('Forbidden', 400)
            return add_security_headers(resp)
        message_body = sanitize_message(message_body)

        # Anti-abuse rate limiting
        allowed, wait = AntiAbuseLimiter.allow(from_number, message_body)
        if not allowed:
            log_structured('WARN', 'Rate limit/abuse triggered', correlation_id, phone=from_number, wait_seconds=wait)
            resp = message_processor.create_error_response(f"Too many requests. Please wait {wait} seconds.", correlation_id)
            return add_security_headers(resp)

        # Get user context for personalized responses
        try:
            user_context = user_context_service.get_user_context(from_number, correlation_id)
            is_new_user = user_context['is_new']
            user_name = user_context.get('name', 'there')
            log_structured('INFO', 'User context loaded', correlation_id, 
                          is_new=is_new_user, user_name=user_name, 
                          greeting_type=user_context.get('greeting_type'))
        except Exception as e:
            log_structured('ERROR', 'Failed to load user context', correlation_id, error=str(e))
            # Fallback to treating as new user
            is_new_user = True
            user_context = {'is_new': True, 'profile': {}, 'greeting_type': 'new_user'}
            user_name = 'there'

        # Environment check
        required_vars = ['OPENAI_API_KEY', 'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN']
        env_ok = all(os.getenv(var) for var in required_vars)
        if not env_ok:
            log_structured('WARN', 'Environment not ready', correlation_id)
            resp = message_processor.create_error_response(
                SVENConfig.MSG_STARTUP,
                correlation_id
            )
            return add_security_headers(resp)


        # Handle new users with personalized onboarding
        if is_new_user or user_context_service.should_trigger_onboarding(user_context):
            try:
                onboarding_message = user_context_service.generate_contextual_greeting(from_number, user_context)
                user_context_service.update_user_interaction(from_number, 'onboarding', correlation_id)
                return message_processor.create_twiml_response(onboarding_message, correlation_id)
            except Exception as e:
                log_structured('ERROR', 'Onboarding flow failed', correlation_id, error=str(e))
                resp = message_processor.create_twiml_response(SVENConfig.MSG_ONBOARD, correlation_id)
                return add_security_headers(resp)

        # Check if this is a name response during onboarding  
        if is_new_user:
            extracted_name = user_mgr.extract_name(message_body)
            if extracted_name:
                user_mgr.set_name(from_number, extracted_name)
                user_context_service.update_user_interaction(from_number, 'name_setup', correlation_id)
                response_text = f"Nice to meet you, {extracted_name}! I help busy families manage schedules through voice messages.\n\nTo get started, set up your email with 'setup email your-calendar@skylight.frame'\n\nOr just tell me about a family event!"
                resp = message_processor.create_twiml_response(response_text, correlation_id)
                return add_security_headers(resp)

        # Returning user: update interaction tracking and provide context
        try:
            user_context_service.update_user_interaction(from_number, 'message', correlation_id)
            # Generate personalized greeting for returning users
            if message_body.lower().strip() in ['hi', 'hello', 'hey', 'menu']:
                contextual_greeting = user_context_service.generate_contextual_greeting(from_number, user_context)
                resp = message_processor.create_twiml_response(contextual_greeting, correlation_id)
                return add_security_headers(resp)
        except Exception as e:
            log_structured('ERROR', 'Failed to update user interaction', correlation_id, error=str(e))

        # Fallbacks for legacy code
        name = user_name
        children = user_context.get('profile', {}).get('children', [])
        email = user_context.get('profile', {}).get('email')

        # Fuzzy command matching
        matcher = CommandMatcher()
        try:
            match_result = matcher.match(message_body)
            matched_command = match_result.get('command')
            corrections = match_result.get('corrections')
        except Exception as e:
            log_structured('ERROR', 'Fuzzy command matching failed', correlation_id, error=str(e))
            matched_command = None
            corrections = None
        correction_msg = ''
        if corrections:
            correction_msg = f"I think you meant '{corrections[0].capitalize()}'!\n"

        # Email setup command
        import re
        try:
            email_setup_match = re.match(r"setup email (.+@.+\..+)", message_body.strip(), re.IGNORECASE)
        except Exception as e:
            log_structured('ERROR', 'Regex error for email setup', correlation_id, error=str(e))
            email_setup_match = None
        if email_setup_match:
            new_email = email_setup_match.group(1).strip()
            try:
                if user_context.get('profile', {}).get('email') != new_email:
                    # Only update if different
                    user_mgr = UserManager()
                    if user_mgr.validate_email(new_email):
                        user_mgr.set_email(from_number, new_email)
                        response_text = SVENConfig.MSG_EMAIL_SET.format(email=new_email)
                    else:
                        response_text = SVENConfig.MSG_EMAIL_INVALID
                else:
                    response_text = SVENConfig.MSG_EMAIL_SET.format(email=new_email)
            except Exception as e:
                log_structured('ERROR', 'Failed to set user email', correlation_id, error=str(e))
                response_text = SVENConfig.MSG_ERROR_GENERIC
            resp = message_processor.create_twiml_response(f"Hey {name}!\n{response_text}", correlation_id)
            return add_security_headers(resp)

        # Menu/help/settings/voice/expense/other command routing
        response_text = ""
        try:
            if matched_command in ['menu', 'help', 'settings']:
                if matched_command == 'menu':
                    children_str = ', '.join([f"{c['name']} ({c.get('age','?')})" for c in children]) if children else 'None'
                    response_text = (
                        f"Here's your menu:\n"
                        f"- Email: {email or 'Not set'}\n"
                        f"- Children: {children_str}\n"
                        "- Type 'help' for assistance or 'settings' to update your info."
                    )
                elif matched_command == 'help':
                    if email:
                        response_text = "You can add events, update your family, or type 'menu' for options."
                    else:
                        response_text = "Set up your email with 'setup email your@skylight.frame' to get started."
                elif matched_command == 'settings':
                    response_text = "Settings coming soon."
            elif message_body.strip() in ['1', '2', '3', '4', '5']:
                response_text = message_processor.handle_menu_choice(message_body.strip(), correlation_id)
            elif num_media > 0 and request.form.get('MediaContentType0', '').startswith('audio/'):
                try:
                    response_text = message_processor.process_voice_message(
                        request.form.get('MediaUrl0'),
                        from_number,
                        correlation_id
                    )
                except Exception as e:
                    log_structured('ERROR', 'Voice message processing failed', correlation_id, error=str(e))
                    response_text = SVENConfig.MSG_VOICE_ERROR.format(name=name)
            elif num_media > 0:
                response_text = SVENConfig.MSG_PHOTO_RECEIVED
            else:
                # Default: expense/trip or unknown command
                try:
                    result = message_processor.process_expense_message_with_trips(
                        message_body,
                        from_number,
                        correlation_id
                    )
                    response_text = f"{result}"
                except Exception as e:
                    log_structured('ERROR', 'Expense/trip processing failed', correlation_id, error=str(e))
                    response_text = SVENConfig.MSG_EXPENSE_ERROR.format(name=name)
        except Exception as e:
            log_structured('ERROR', 'Command routing failed', correlation_id, error=str(e))
            response_text = SVENConfig.MSG_ERROR_GENERIC

        # Add correction message if needed
        if correction_msg:
            response_text = correction_msg + response_text

        # Add personalized prefix to responses
        if user_name and user_name != 'there':
            if not response_text.startswith(f"Hey {user_name}"):
                response_text = f"Hey {user_name}! {response_text}"

        # Log performance and slow operations
        duration = time.time() - request_start_time
        if duration > 2.0:
            log_structured('WARN', 'Slow request', correlation_id, duration_ms=int(duration * 1000), user_name=name, email=email, children=children)
        else:
            log_structured('INFO', 'Request completed', correlation_id,
                          duration_ms=int(duration * 1000),
                          user_name=name, email=email, children=children)

        resp = message_processor.create_twiml_response(response_text, correlation_id)
        return add_security_headers(resp)
    except Exception as e:
        import traceback
        error_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        tb = traceback.format_exc(limit=3)
        log_structured('ERROR', 'Critical error', correlation_id,
                      error_id=error_id, error=str(e)[:200], traceback=tb)
        response_text = SVENConfig.MSG_SERVICE_UNAVAILABLE.format(error_id=error_id)
        resp = message_processor.create_error_response(response_text, correlation_id)
        return add_security_headers(resp)