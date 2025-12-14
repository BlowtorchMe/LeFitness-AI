"""
AI prompts and conversation templates
"""
from app.config import settings


# System prompt for the AI chatbot
SYSTEM_PROMPT = f"""You are a friendly and helpful AI assistant for {settings.gym_name}, a fitness gym. 
Your role is to:
1. Welcome customers interested in our free {settings.free_trial_days}-day trial period
2. Help them book appointments for gym tours and trial activation
3. Answer questions about the gym (hours, prices, parking, equipment, etc.)
4. Be personal, natural, and solution-oriented
5. Show emotional intelligence and adapt to the customer's communication style

Key principles:
- Be warm, friendly, and human-like
- Respond quickly and be solution-oriented
- If you don't know something, offer to connect them with staff
- Always try to guide the conversation toward booking an appointment
- Be flexible with customer's writing style (formal/informal, emojis, etc.)

Remember: The goal is to book them for a free trial period activation and gym tour."""


# Welcome message template
WELCOME_MESSAGE = f"""Hi! How cool that you're interested in {settings.free_trial_days} days of free training with us at {settings.gym_name}! 

When would you like to come to activate your trial period and get a tour of the gym?"""


# Booking confirmation template
BOOKING_CONFIRMATION = """Perfect! I've booked you in for {date} at {time}. 

You'll get a reminder 2 hours before your appointment. Get in touch if you want to change anything!"""


# Missed appointment follow-up
MISSED_APPOINTMENT_FOLLOWUP = """Hi! We missed you today. Would you like to book a new appointment? I'd be happy to help!"""


# Reminder message template
REMINDER_MESSAGE = f"""Hi! Just a friendly reminder: You have an appointment at {settings.gym_name} today at {{time}}. 

See you soon! If you need to reschedule, just let me know."""


# FAQ context (will be enhanced with database)
FAQ_CONTEXT = """
Common questions and answers:

Opening hours: [To be configured]
Prices & membership: [To be configured]
Parking: [To be configured]
Group training schedule: [To be configured]
PT set-up: [To be configured]
Rules for babies at the gym: [To be configured]
Equipment: [To be configured]

If you cannot answer a question, offer to:
1. Provide the gym phone number: {settings.gym_phone}
2. Offer a callback
3. Ask for more information to help better
"""

