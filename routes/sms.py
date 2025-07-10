

from flask import Blueprint, request
from utils.helpers import get_correlation_id, sanitize_input, verify_webhook_signature
from utils.logging import log_structured
from services.redis_service import (
    get_pending_event, clear_pending_event, store_pending_event, delete_user_data, store_user_email, get_user_skylight_email, get_user_profile, store_user_name
)
from services.email_service import send_to_skylight_sendgrid
from services.user_manager import UserManager
from services.config import SVENConfig
from utils.security import validate_phone, sanitize_message, add_security_headers
from utils.rate_limiting import AntiAbuseLimiter
import os
import time
from datetime import datetime
import openai

sms_bp = Blueprint('sms', __name__)

@sms_bp.route('/sms', methods=['POST'])
def sms_webhook():
    # Import the functions from app at runtime to avoid circular imports
    from app import (
        env_ok, handle_menu_choice, process_expense_message_with_trips, 
        process_voice_message, create_twiml_response, create_error_response
    )
    from utils.command_matcher import CommandMatcher
    correlation_id = get_correlation_id()
    request_start_time = time.time()
    log_structured('INFO', 'SMS webhook triggered', correlation_id)

    try:
        # Security: Verify webhook signature (always enforce in prod)
        if not verify_webhook_signature(request):
            log_structured('WARN', 'Invalid webhook signature', correlation_id)
            return 'Forbidden', 403

        # Extract and validate input
        from_number = request.form.get('From', 'UNKNOWN')
        message_body = request.form.get('Body', '')
        num_media = int(request.form.get('NumMedia', 0))

        # Input validation and sanitization
        if not validate_phone(from_number):
            log_structured('WARN', 'Invalid phone format', correlation_id)
            return 'Forbidden', 400
        message_body = sanitize_message(message_body)

        # Anti-abuse rate limiting
        allowed, wait = AntiAbuseLimiter.allow(from_number, message_body)
        if not allowed:
            log_structured('WARN', 'Rate limit/abuse triggered', correlation_id, phone=from_number, wait_seconds=wait)
            resp = create_error_response(f"Too many requests. Please wait {wait} seconds.", correlation_id)
            return add_security_headers(resp)

        # User profile management
        user_mgr = UserManager()
        try:
            user_profile = user_mgr.get_profile(from_number)
        except Exception as e:
            log_structured('ERROR', 'Failed to load user profile', correlation_id, error=str(e))
            user_profile = None
        is_new_user = not user_profile or not user_profile.get('name')

        # Log user status
        log_structured('INFO', 'User status', correlation_id, user_status='new' if is_new_user else 'returning', phone=from_number)

        # Environment check
        if not env_ok:
            log_structured('WARN', 'Environment not ready', correlation_id)
            return create_error_response(
                SVENConfig.MSG_STARTUP,
                correlation_id
            )

        # Onboarding flow for new users
        if is_new_user:
            try:
                user_mgr.update_profile(from_number, {'name': None, 'onboarding_complete': False, 'message_count': 1, 'last_seen': datetime.now().isoformat()})
            except Exception as e:
                log_structured('ERROR', 'Failed to update new user profile', correlation_id, error=str(e))
            return create_twiml_response(SVENConfig.MSG_ONBOARD, correlation_id)

        # Returning user: update last seen and message count
        try:
            user_mgr.update_profile(from_number, {'last_seen': datetime.now().isoformat(), 'message_count': user_profile.get('metadata', {}).get('message_count', 0) + 1})
        except Exception as e:
            log_structured('ERROR', 'Failed to update returning user profile', correlation_id, error=str(e))
        name = user_profile.get('name', 'there')
        onboarding_complete = user_profile.get('metadata', {}).get('onboarding_complete', False)
        children = user_profile.get('children', [])
        email = user_profile.get('email')

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
                if user_mgr.validate_email(new_email):
                    user_mgr.set_email(from_number, new_email)
                    response_text = SVENConfig.MSG_EMAIL_SET.format(email=new_email)
                else:
                    response_text = SVENConfig.MSG_EMAIL_INVALID
            except Exception as e:
                log_structured('ERROR', 'Failed to set user email', correlation_id, error=str(e))
                response_text = SVENConfig.MSG_ERROR_GENERIC
            return create_twiml_response(f"Hey {name}!\n{response_text}", correlation_id)

        # Menu/help/settings/voice/expense/other command routing

        response_text = ""
        try:
            if matched_command in ['menu', 'help', 'settings']:
                if matched_command == 'menu':
                    children_str = ', '.join([f"{c['name']} ({c.get('age','?')})" for c in children]) if children else 'None'
                    response_text = (
                        f"Hey {name}! Here's your menu:\n"
                        f"- Email: {email or 'Not set'}\n"
                        f"- Children: {children_str}\n"
                        "- Type 'help' for assistance or 'settings' to update your info."
                    )
                elif matched_command == 'help':
                    if email:
                        response_text = f"Hey {name}! You can add events, update your family, or type 'menu' for options."
                    else:
                        response_text = f"Hey {name}! Set up your email with 'setup email your@skylight.frame' to get started."
                elif matched_command == 'settings':
                    response_text = f"Hey {name}! Settings coming soon."
            elif message_body.strip() in ['1', '2', '3', '4', '5']:
                response_text = handle_menu_choice(message_body.strip(), correlation_id)
            elif num_media > 0 and request.form.get('MediaContentType0', '').startswith('audio/'):
                try:
                    response_text = process_voice_message(
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
                    result = process_expense_message_with_trips(
                        message_body,
                        from_number,
                        correlation_id
                    )
                    response_text = f"Hey {name}! {result}"
                except Exception as e:
                    log_structured('ERROR', 'Expense/trip processing failed', correlation_id, error=str(e))
                    response_text = SVENConfig.MSG_EXPENSE_ERROR.format(name=name)
        except Exception as e:
            log_structured('ERROR', 'Command routing failed', correlation_id, error=str(e))
            response_text = SVENConfig.MSG_ERROR_GENERIC

        # Add correction message if needed
        if correction_msg:
            response_text = correction_msg + response_text

        # Log performance and slow operations
        duration = time.time() - request_start_time
        if duration > 2.0:
            log_structured('WARN', 'Slow request', correlation_id, duration_ms=int(duration * 1000), user_name=name, email=email, children=children)
        else:
            log_structured('INFO', 'Request completed', correlation_id,
                          duration_ms=int(duration * 1000),
                          user_name=name, email=email, children=children)

        resp = create_twiml_response(response_text, correlation_id)
        return add_security_headers(resp)
    except Exception as e:
        import traceback
        error_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        tb = traceback.format_exc(limit=3)
        log_structured('ERROR', 'Critical error', correlation_id,
                      error_id=error_id, error=str(e)[:200], traceback=tb)
        response_text = SVENConfig.MSG_SERVICE_UNAVAILABLE.format(error_id=error_id)
        resp = create_error_response(response_text, correlation_id)
        return add_security_headers(resp)