import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from utils.logging import log_structured
from services.redis_service import get_user_skylight_email  # Import this!

def send_to_skylight_sendgrid(event_data, phone_number, correlation_id, user_email=None):
    try:
        sg_api_key = os.getenv('SENDGRID_API_KEY', '').strip()
        if not sg_api_key:
            log_structured('ERROR', 'SendGrid API key not configured', correlation_id)
            return False
        
        # Get user email if not provided
        if not user_email:
            user_email = get_user_skylight_email(phone_number)
        
        # Fall back to default if still no email
        if not user_email:
            user_email = os.getenv('DEFAULT_SKYLIGHT_EMAIL', '').strip()
        
        if not user_email:
            log_structured('ERROR', 'No Skylight email configured', correlation_id)
            return False
        
        subject = f"Calendar Update: {event_data.get('activity', 'Event')}"
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
        
        plain_content = f"""New Event Added\n\nEvent: {event_data.get('activity', 'Family Event')}\nDate: {event_data.get('day', 'Today')}\nTime: {event_data.get('time', 'TBD')}"""
        if event_data.get('child'):
            plain_content += f"\nFor: {event_data.get('child')}"
        if event_data.get('location'):
            plain_content += f"\nLocation: {event_data.get('location')}"
        if event_data.get('recurring'):
            plain_content += f"\nRecurring: {event_data.get('recurring')}"
        plain_content += "\n\nAdded by S.V.E.N. Family Assistant"
        
        message = Mail(
            from_email=(os.getenv('SENDGRID_FROM_EMAIL', 'sven@family-assistant.com').strip(),
                        'S.V.E.N. Family Assistant'),
            to_emails=user_email,
            subject=subject,
            plain_text_content=plain_content,
            html_content=html_content
        )
        message.reply_to = 'noreply@family-assistant.com'
        
        sg = SendGridAPIClient(api_key=sg_api_key)
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