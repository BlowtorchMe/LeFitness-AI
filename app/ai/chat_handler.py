"""
Main AI conversation handler
"""
import openai
from typing import Optional, Dict, List
from app.config import settings
from app.ai.prompts import SYSTEM_PROMPT, FAQ_CONTEXT
from app.ai.translations import get as t
from app.ai.faq_handler import FAQHandler
from app.ai.intent_recognizer import IntentRecognizer
from app.ai.conversation_state import ConversationState, ConversationFlowManager


class ChatHandler:
    """Handles AI conversations with customers"""
    
    def __init__(self):
        # Initialize OpenAI client only if API key is available
        self.client = None
        if settings.openai_api_key:
            try:
                self.client = openai.OpenAI(api_key=settings.openai_api_key)
            except Exception:
                pass  # Will fail gracefully on first API call
        self.faq_handler = FAQHandler()
        self.intent_recognizer = IntentRecognizer()
        self.flow_manager = ConversationFlowManager()
    
    async def process_message(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        customer_info: Optional[Dict] = None,
        conversation_state: Optional[str] = None,
        language: str = "en",
    ) -> Dict[str, any]:
        """
        Process a user message and generate an AI response
        The agent proactively guides the conversation through the booking flow
        
        Args:
            user_message: The message from the customer
            conversation_history: Previous messages in the conversation
            customer_info: Customer information (name, phone, etc.)
            conversation_state: Current state in conversation flow
        
        Returns:
            Dict with response text, intent, next_state, and any actions needed
        """
        # Recognize intent
        intent = await self.intent_recognizer.recognize(user_message)
        
        # Determine current state
        current_state = ConversationState(conversation_state) if conversation_state else ConversationState.WELCOME
        
        # Check FAQ first
        faq_answer = await self.faq_handler.get_answer(user_message)
        
        # Get state-specific prompt
        state_prompt = self.flow_manager.get_state_prompt(current_state, customer_info or {})
        
        # Build conversation context
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        messages.append({
            "role": "system",
            "content": f"""You must reply with BOTH English and Swedish. Output exactly:
---EN---
[full reply in English]
---SV---
[full reply in Swedish]

No other format. Both blocks are required every time.

Current conversation state: {current_state.value}
            
{state_prompt}

IMPORTANT: You are actively leading this conversation. Your goal is to guide the customer through:
1. Welcome (done)
2. Gather profile info (if not complete)
3. Recommend booking free trial
4. Collect booking details (date/time)
5. Confirm booking
6. Send confirmation

Be proactive! Don't just answer questions - guide them toward booking. If they ask questions, answer briefly then guide back to booking."""
        })
        
        # Add FAQ context
        if faq_answer:
            messages.append({
                "role": "system",
                "content": f"FAQ Context: {FAQ_CONTEXT}\n\nRelevant FAQ: {faq_answer}"
            })
        
        # Add customer info if available
        if customer_info:
            customer_context = f"Customer info: {customer_info}"
            messages.append({"role": "system", "content": customer_context})
        
        # Add conversation history
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        if not self.client:
            err = "I'm sorry, the AI service is not configured. Please contact support."
            return {"response": err, "response_en": err, "response_sv": None, "intent": "error", "next_state": conversation_state}
        
        try:
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                temperature=0.7,
                max_tokens=900
            )
            raw = response.choices[0].message.content
            response_en, response_sv = self._parse_bilingual_response(raw)
            if response_en and not response_sv:
                response_sv = self._get_swedish_from_ai(response_en)
            single = response_en or response_sv or raw
            next_state = self._determine_next_state(current_state, intent, user_message, customer_info)
            return {
                "response": single,
                "response_en": response_en,
                "response_sv": response_sv,
                "intent": intent,
                "current_state": current_state.value,
                "next_state": next_state.value if next_state else current_state.value,
                "faq_used": faq_answer is not None,
                "needs_human": self._should_escalate(user_message, single),
                "should_proceed": self._should_proceed_to_next_state(current_state, intent)
            }
        
        except Exception as e:
            fallback = f"I apologize, but I'm having trouble right now. Please call us at {settings.gym_phone} and we'll be happy to help!"
            return {
                "response": fallback,
                "response_en": fallback,
                "response_sv": None,
                "intent": "error",
                "current_state": current_state.value,
                "next_state": current_state.value,
                "faq_used": False,
                "needs_human": True,
                "error": str(e)
            }
    
    def _determine_next_state(
        self,
        current_state: ConversationState,
        intent: str,
        user_message: str,
        customer_info: Optional[Dict]
    ) -> Optional[ConversationState]:
        """Determine next state based on current state and user intent"""
        
        # If booking intent detected, move to collecting details
        if intent == "book" and current_state in [ConversationState.PROFILE_COMPLETE, ConversationState.RECOMMENDING_BOOKING]:
            return ConversationState.COLLECTING_BOOKING_DETAILS
        
        # If user provides date/time, move to confirmation
        if current_state == ConversationState.COLLECTING_BOOKING_DETAILS:
            # Check if message contains date/time indicators
            time_indicators = ["tomorrow", "today", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "am", "pm", ":", "at"]
            if any(indicator in user_message.lower() for indicator in time_indicators):
                return ConversationState.CONFIRMING_BOOKING
        
        # If user confirms, move to booking confirmed
        if current_state == ConversationState.CONFIRMING_BOOKING and intent in ["book", "greeting"]:
            return ConversationState.BOOKING_CONFIRMED
        
        # If profile complete and user asks questions, still recommend booking
        if current_state == ConversationState.PROFILE_COMPLETE and intent == "question":
            return ConversationState.RECOMMENDING_BOOKING
        
        # Default: get next state from flow manager
        return self.flow_manager.get_next_state(current_state)
    
    def _should_proceed_to_next_state(self, current_state: ConversationState, intent: str) -> bool:
        """Determine if we should proactively move to next state"""
        if current_state == ConversationState.PROFILE_COMPLETE:
            return True  # Always recommend booking after profile complete
        if current_state == ConversationState.RECOMMENDING_BOOKING and intent == "book":
            return True  # User wants to book
        return False
    
    def _get_swedish_from_ai(self, text_en: str) -> Optional[str]:
        if not text_en or not self.client:
            return None
        try:
            r = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": "Reply with only the Swedish translation. No other text, no explanation."},
                    {"role": "user", "content": f"Translate to Swedish:\n\n{text_en}"}
                ],
                temperature=0.3,
                max_tokens=500
            )
            out = (r.choices[0].message.content or "").strip()
            return out if out else None
        except Exception:
            return None

    @staticmethod
    def _parse_bilingual_response(raw: str) -> tuple:
        """Parse ---EN--- / ---SV--- blocks. Returns (response_en, response_sv)."""
        if not raw or not isinstance(raw, str):
            return (None, None)
        raw = raw.strip()
        en, sv = None, None
        if "---EN---" in raw and "---SV---" in raw:
            parts = raw.split("---EN---", 1)
            if len(parts) == 2:
                rest = parts[1].split("---SV---", 1)
                en = (rest[0].strip() or None) if rest else None
                sv = (rest[1].strip() or None) if len(rest) > 1 else None
        if not en and not sv and raw:
            en = raw
        return (en, sv)

    def _should_escalate(self, user_message: str, ai_response: str) -> bool:
        """Determine if conversation should be escalated to human"""
        # Simple heuristics - can be enhanced
        uncertainty_phrases = [
            "I'm not sure",
            "I don't know",
            "I'm uncertain",
            "I cannot",
            "I'm unable"
        ]
        
        return any(phrase.lower() in ai_response.lower() for phrase in uncertainty_phrases)
    
    def get_welcome_message(self, language: str = "en", customer_name: Optional[str] = None) -> str:
        """Generate welcome message in the given language."""
        if customer_name:
            return t(language, "welcome_hi", name=customer_name)
        return t(language, "welcome")

