from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os
from dotenv import load_dotenv
import base64
import requests
from PIL import Image
import io

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure OpenAI
openai.api_key = os.getenv('OPENAI_API_KEY')

# FMLA Expert System Prompt
FMLA_PROMPT = """You are an expert FMLA (Family and Medical Leave Act) assistant that helps workers understand their rights. You can communicate in any language the user writes in.

KEY PRINCIPLES:
- Always respond in the SAME LANGUAGE the user writes in
- Be warm, helpful, and supportive
- Provide accurate FMLA information
- Always include the disclaimer that this is educational, not legal advice
- Help with eligibility, rights, forms, and next steps

FMLA ELIGIBILITY REQUIREMENTS:
- Employee must work for employer 12+ months
- Employee must have worked 1,250+ hours in past 12 months  
- Employer must have 50+ employees within 75 miles
- Valid reasons: serious health condition, family care, childbirth, military family leave

FMLA RIGHTS:
- Up to 12 weeks unpaid leave per year
- Job protection (same or equivalent position)
- Health benefits continue during leave
- Cannot be retaliated against

If user sends a photo, analyze any FMLA-related documents and explain them clearly in the user's language.

Always end with asking if they have more questions and remind them this is educational information."""

@app.route('/sms', methods=['POST'])
def sms_webhook():
    print("=== SMS WEBHOOK RECEIVED ===")
    print(f"Request form data: {request.form}")
    
    try:
        # Get message data
        from_number = request.form.get('From')
        message_body = request.form.get('Body', '')
        num_media = int(request.form.get('NumMedia', 0))

        print(f"Message: {message_body}")
        print(f"From: {from_number}")
        print(f"NumMedia: {num_media}")
        
        response_text = ""
        
        if num_media > 0:
            # Handle image message
            media_url = request.form.get('MediaUrl0')
            media_content_type = request.form.get('MediaContentType0')
            
            if media_content_type and media_content_type.startswith('image/'):
                response_text = process_image_message(media_url, message_body)
            else:
                response_text = "Lo siento, solo puedo procesar imágenes. / Sorry, I can only process images."
        else:
            # Handle text message
            response_text = process_text_message(message_body)
            
    except Exception as e:
        response_text = "Disculpe, hubo un error. Intente de nuevo. / Sorry, there was an error. Please try again."
        print(f"Error: {e}")
    
    # Create Twilio response
    twiml_response = MessagingResponse()
    twiml_response.message(response_text)
    
    return str(twiml_response)

def process_text_message(message_body):
    """Process text-only messages"""
    print(f"=== CALLING OPENAI WITH MESSAGE: {message_body} ===")
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": FMLA_PROMPT},
                {"role": "user", "content": message_body}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"OpenAI Error: {e}")
        return "Disculpe, no pude procesar su mensaje. Intente de nuevo. / Sorry, I couldn't process your message. Please try again."

def process_image_message(media_url, message_body):
    """Process messages with images"""
    try:
        # Create the prompt for image analysis
        user_prompt = f"User's question: {message_body}" if message_body else "Please explain this FMLA document"
        
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": FMLA_PROMPT},
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
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"Vision API Error: {e}")
        return "No pude analizar la imagen. Intente de nuevo. / I couldn't analyze the image. Please try again."

@app.route('/', methods=['GET'])
def home():
    return "FMLA Amigo Bot is running! 🤖 Text +18775374013 to get started.", 200

@app.route('/health', methods=['GET'])
def health_check():
    return "FMLA Amigo Bot is running!", 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
