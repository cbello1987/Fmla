from flask import Blueprint, request
from utils.helpers import get_correlation_id, sanitize_input, verify_webhook_signature
from utils.logging import log_structured
from services.redis_service import (
    get_pending_event, clear_pending_event, store_pending_event, delete_user_data, store_user_email, get_user_skylight_email, get_user_profile, store_user_name
)
from services.email_service import send_to_skylight_sendgrid
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
    from services.user_profile_manager import UserProfileManager

    correlation_id = get_correlation_id()
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

        # User profile management
        profile_mgr = UserProfileManager()
        user_profile = profile_mgr.get_user_profile(from_number)
        is_new_user = user_profile is None

        # Log user status
        log_structured('INFO', 'User status', correlation_id, user_status='new' if is_new_user else 'returning', phone=from_number)

        # Environment check
        if not env_ok:
            return create_error_response(
                "S.V.E.N. is starting up. Please try again in 30 seconds! 🔄",
                correlation_id
            )

        # Onboarding flow for new users
        if is_new_user:
            # Create profile and send onboarding message
            profile_mgr.create_user_profile(from_number)
            onboarding_msg = (
                "👋 Welcome to S.V.E.N.! I'm your family's planning assistant.\n\n"
                "To get started, please set up your Skylight calendar email.\n"
                "Reply with: setup email your-calendar@skylight.frame\n\n"
                "Example: setup email smith-family@skylight.frame\n\n"
                "You can also tell me about your kids: 'My kids are Emma (8) and Jack (6)'\n\n"
                "Type 'menu' for more options!"
            )
            # Save last_seen and increment message count
            profile_mgr.update_last_seen(from_number)
            profile_mgr.increment_message_count(from_number)
            return create_twiml_response(onboarding_msg, correlation_id)

        # Returning user: personalized greeting or normal flow
        profile_mgr.update_last_seen(from_number)
        profile_mgr.increment_message_count(from_number)
        message_count = user_profile.get('message_count', 0) + 1 if user_profile else 1
        onboarding_complete = user_profile.get('onboarding_complete', False) if user_profile else False

        # Personalized greeting for returning users who haven't completed onboarding
        if not onboarding_complete:
            greet_msg = (
                f"👋 Welcome back! You have sent {message_count} messages.\n"
                "Don't forget to set up your Skylight email if you haven't: setup email your-calendar@skylight.frame\n"
                "Type 'menu' for more options."
            )
            return create_twiml_response(greet_msg, correlation_id)

        # Otherwise, proceed with normal message handling
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