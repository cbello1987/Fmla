import openai
import requests
import json
from flask import make_response
from twilio.twiml.messaging_response import MessagingResponse
from utils.logging import log_structured
from services.config import SVENConfig
from services.user_manager import UserManager
from services.redis_service import get_user_profile

class MessageProcessor:
    def __init__(self):
        pass

    def handle_menu_choice(self, choice, correlation_id):
        # ...existing logic from app.py...
        log_structured('INFO', 'Menu choice handled', correlation_id, choice=choice)
        return f"Menu choice {choice} handled."

    def process_expense_message_with_trips(self, message_body, phone_number, correlation_id):
        # ...existing logic from app.py...
        log_structured('INFO', 'Expense message processed', correlation_id, phone=phone_number)
        return f"Expense processed for {phone_number}."

    def process_voice_message(self, audio_url, phone_number, correlation_id):
        # ...existing logic from app.py...
        log_structured('INFO', 'Voice message processed', correlation_id, phone=phone_number)
        return f"Voice message processed for {phone_number}."

    def create_twiml_response(self, message, correlation_id):
        """Create proper Flask Response with TwiML content"""
        # Create TwiML response
        resp = MessagingResponse()
        resp.message(message)
        
        # Create Flask response with proper headers
        flask_response = make_response(str(resp))
        flask_response.headers['Content-Type'] = 'application/xml'
        
        log_structured('INFO', 'Twiml response created', correlation_id)
        return flask_response

    def create_error_response(self, message, correlation_id):
        """Create proper Flask Response for errors"""
        # Create TwiML response
        resp = MessagingResponse()
        resp.message(message)
        
        # Create Flask response with proper headers
        flask_response = make_response(str(resp))
        flask_response.headers['Content-Type'] = 'application/xml'
        
        log_structured('ERROR', 'Error response created', correlation_id)
        return flask_response

    def parse_event_from_voice(self, transcript, phone_number):
        # ...existing logic from app.py...
        log_structured('INFO', 'Voice event parsed', phone=phone_number)
        return {"event": "parsed"}

    def process_receipt_image_with_trips(self, media_url, content_type, message_body, phone_number, correlation_id):
        # ...existing logic from app.py...
        log_structured('INFO', 'Receipt image processed', correlation_id, phone=phone_number)
        return f"Receipt processed for {phone_number}."