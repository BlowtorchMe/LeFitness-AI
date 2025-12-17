"""
Conversation state management for guiding users through the booking flow
"""
from enum import Enum
from typing import Optional, Dict
from datetime import datetime


class ConversationState(Enum):
    """Conversation state enumeration"""
    WELCOME = "welcome"
    GATHERING_PROFILE = "gathering_profile"
    PROFILE_COMPLETE = "profile_complete"
    RECOMMENDING_BOOKING = "recommending_booking"
    COLLECTING_BOOKING_DETAILS = "collecting_booking_details"
    CONFIRMING_BOOKING = "confirming_booking"
    BOOKING_CONFIRMED = "booking_confirmed"
    ANSWERING_QUESTIONS = "answering_questions"
    FOLLOW_UP = "follow_up"


class ConversationFlowManager:
    """Manages conversation flow and guides users through booking process"""
    
    def __init__(self):
        self.state_transitions = {
            ConversationState.WELCOME: ConversationState.GATHERING_PROFILE,
            ConversationState.GATHERING_PROFILE: ConversationState.PROFILE_COMPLETE,
            ConversationState.PROFILE_COMPLETE: ConversationState.RECOMMENDING_BOOKING,
            ConversationState.RECOMMENDING_BOOKING: ConversationState.COLLECTING_BOOKING_DETAILS,
            ConversationState.COLLECTING_BOOKING_DETAILS: ConversationState.CONFIRMING_BOOKING,
            ConversationState.CONFIRMING_BOOKING: ConversationState.BOOKING_CONFIRMED,
        }
    
    def get_next_state(self, current_state: ConversationState) -> Optional[ConversationState]:
        """Get next state in the flow"""
        return self.state_transitions.get(current_state)
    
    def get_state_prompt(self, state: ConversationState, customer_info: Dict) -> str:
        """Get AI prompt based on current conversation state"""
        from app.config import settings
        
        prompts = {
            ConversationState.WELCOME: f"""You just welcomed the customer. Now guide them to share their profile information (name, email, phone) so you can help them book their free trial.""",
            
            ConversationState.GATHERING_PROFILE: """You are currently gathering the customer's profile information. Be friendly and explain why you need this information (to send booking confirmation, reminders, etc.). Ask for one piece of information at a time.""",
            
            ConversationState.PROFILE_COMPLETE: f"""Great! You have the customer's profile information. Now proactively recommend booking their free {settings.free_trial_days}-day trial period. Be enthusiastic and highlight the benefits. Guide them toward booking.""",
            
            ConversationState.RECOMMENDING_BOOKING: f"""You are recommending the free trial. Be persuasive but not pushy. Highlight benefits like: full gym access, equipment, group training, gym tour. The user has been provided with an appointment schedule link - remind them to use that link to book. DO NOT suggest specific time slots.""",
            
            ConversationState.COLLECTING_BOOKING_DETAILS: """The user has been provided with an appointment schedule link. DO NOT suggest specific time slots. Instead, remind them to use the appointment schedule link that was already sent to book at a time that works for them. Once they book via the calendar, the system will automatically detect it.""",
            
            ConversationState.CONFIRMING_BOOKING: """You are confirming the booking details with the customer. Repeat back the date and time they chose. Ask for final confirmation before creating the booking.""",
            
            ConversationState.BOOKING_CONFIRMED: """The booking has been confirmed! Congratulate them, remind them about the appointment, and let them know they'll receive a confirmation email and reminder. Be warm and welcoming.""",
            
            ConversationState.ANSWERING_QUESTIONS: """The customer is asking questions. Answer helpfully, but always try to guide the conversation back toward booking their free trial. Be solution-oriented.""",
        }
        
        return prompts.get(state, "Continue the conversation naturally while guiding toward booking.")
    
    def should_proactively_message(self, state: ConversationState) -> bool:
        """Determine if agent should send proactive message"""
        proactive_states = [
            ConversationState.PROFILE_COMPLETE,
            ConversationState.RECOMMENDING_BOOKING,
        ]
        return state in proactive_states
    
    def get_proactive_message(self, state: ConversationState, customer_name: str) -> Optional[str]:
        """Get proactive message to guide conversation forward"""
        from app.config import settings
        
        if state == ConversationState.PROFILE_COMPLETE:
            return f"Perfect, {customer_name}! Now let's get you booked for your free {settings.free_trial_days}-day trial. When would you like to visit us?"
        
        if state == ConversationState.RECOMMENDING_BOOKING:
            return f"Great! Our free {settings.free_trial_days}-day trial includes full access to all equipment, group training classes, and a personal gym tour. Would you like to book your appointment now?"
        
        return None

