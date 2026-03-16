"""
Main AI conversation handler
"""
import openai, time
from typing import Optional, Dict, List

from app.config import settings
from app.ai.prompts import SYSTEM_PROMPT
from app.ai.translations import get as t
from app.ai.intent_recognizer import IntentRecognizer
from app.ai.conversation_state import ConversationState, ConversationFlowManager


class ChatHandler:
    """Handles AI conversations with customers"""

    def __init__(self):
        self.client = None
        if settings.openai_api_key:
            try:
                self.client = openai.OpenAI(api_key=settings.openai_api_key)
            except Exception:
                pass
        print("Using OpenAI model:", settings.openai_model)

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
        total_start = time.perf_counter()
        print("ChatHandler.process_message was called")

        intent_start = time.perf_counter()
        intent = await self.intent_recognizer.recognize(user_message)
        print("intent_recognizer took", (time.perf_counter() - intent_start) * 1000, "ms")

        current_state = (
            ConversationState(conversation_state)
            if conversation_state
            else ConversationState.WELCOME
        )

        state_prompt = self.flow_manager.get_state_prompt(current_state, customer_info or {})

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

        if customer_info:
            messages.append({"role": "system", "content": f"Customer info: {customer_info}"})

        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": user_message})

        if not self.client:
            err = "I'm sorry, the AI service is not configured. Please contact support."
            print("ChatHandler.process_message total took", (time.perf_counter() - total_start) * 1000, "ms")
            return {
                "response": err,
                "response_en": err,
                "response_sv": None,
                "intent": "error",
                "next_state": conversation_state,
            }

        try:
            openai_start = time.perf_counter()
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                temperature=0.7,
                max_tokens=600,
            )
            print("OpenAI chat.completions.create took", (time.perf_counter() - openai_start) * 1000, "ms")

            raw = response.choices[0].message.content
            response_en, response_sv = self._parse_bilingual_response(raw)
            single = response_en or response_sv or raw

            next_state = self._determine_next_state(current_state, intent, user_message, customer_info)

            print("ChatHandler.process_message total took", (time.perf_counter() - total_start) * 1000, "ms")
            return {
                "response": single,
                "response_en": response_en,
                "response_sv": response_sv,
                "intent": intent,
                "current_state": current_state.value,
                "next_state": next_state.value if next_state else current_state.value,
                "faq_used": False,
                "needs_human": self._should_escalate(user_message, single),
                "should_proceed": self._should_proceed_to_next_state(current_state, intent),
                "faq_video_url": None,
            }

        except Exception as e:
            print("ChatHandler.process_message failed:", str(e))
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
                "error": str(e),
            }

    def _determine_next_state(
        self,
        current_state: ConversationState,
        intent: str,
        user_message: str,
        customer_info: Optional[Dict],
    ) -> Optional[ConversationState]:
        if intent == "book" and current_state in [
            ConversationState.PROFILE_COMPLETE,
            ConversationState.RECOMMENDING_BOOKING,
        ]:
            return ConversationState.COLLECTING_BOOKING_DETAILS

        if current_state == ConversationState.COLLECTING_BOOKING_DETAILS:
            time_indicators = [
                "tomorrow", "today", "monday", "tuesday", "wednesday",
                "thursday", "friday", "saturday", "sunday", "am", "pm", ":", "at",
            ]
            if any(indicator in user_message.lower() for indicator in time_indicators):
                return ConversationState.CONFIRMING_BOOKING

        if current_state == ConversationState.CONFIRMING_BOOKING and intent in ["book", "greeting"]:
            return ConversationState.BOOKING_CONFIRMED

        if current_state == ConversationState.PROFILE_COMPLETE and intent == "question":
            return ConversationState.RECOMMENDING_BOOKING

        return self.flow_manager.get_next_state(current_state)

    def _should_proceed_to_next_state(self, current_state: ConversationState, intent: str) -> bool:
        if current_state == ConversationState.PROFILE_COMPLETE:
            return True
        if current_state == ConversationState.RECOMMENDING_BOOKING and intent == "book":
            return True
        return False

    def _get_swedish_from_ai(self, text_en: str) -> Optional[str]:
        if not text_en or not self.client:
            return None
        try:
            translate_start = time.perf_counter()
            r = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": "Reply with only the Swedish translation. No other text, no explanation."},
                    {"role": "user", "content": f"Translate to Swedish:\n\n{text_en}"},
                ],
                temperature=0.3,
                max_tokens=500,
            )
            print("_get_swedish_from_ai OpenAI call took", (time.perf_counter() - translate_start) * 1000, "ms")

            out = (r.choices[0].message.content or "").strip()
            return out if out else None
        except Exception:
            return None

    @staticmethod
    def _parse_bilingual_response(raw: str) -> tuple:
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
        uncertainty_phrases = [
            "I'm not sure",
            "I don't know",
            "I'm uncertain",
            "I cannot",
            "I'm unable",
        ]
        return any(phrase.lower() in ai_response.lower() for phrase in uncertainty_phrases)

    def get_welcome_message(self, language: str = "en", customer_name: Optional[str] = None) -> str:
        if customer_name:
            return t(language, "welcome_hi", name=customer_name)
        return t(language, "welcome")