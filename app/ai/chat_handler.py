"""
Main AI conversation handler
"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from typing import Optional, Dict, List, Tuple

import openai

from app.config import settings
from app.ai.faq_handler import FAQHandler, FAQMatch, FAQ_DIRECT_RESPONSE_THRESHOLD
from app.ai.prompts import FAQ_CONTEXT, build_compact_system_prompt
from app.ai.translations import get as t
from app.ai.intent_recognizer import IntentRecognizer
from app.ai.conversation_state import ConversationState, ConversationFlowManager


@lru_cache(maxsize=1)
def _get_openai_client():
    if not settings.openai_api_key:
        return None
    try:
        return openai.OpenAI(api_key=settings.openai_api_key)
    except Exception:
        return None


@dataclass(frozen=True)
class MessageAnalysis:
    intent: str
    current_state: ConversationState
    faq_match: Optional[FAQMatch]
    fast_path_response: Optional[Dict[str, any]]
    t0: float
    t1: float
    t2: float


class ChatHandler:
    """Handles AI conversations with customers"""
    
    def __init__(self):
        # Initialize OpenAI client only if API key is available
        self.client = _get_openai_client()
        self.faq_handler = FAQHandler()
        self.intent_recognizer = IntentRecognizer()
        self.flow_manager = ConversationFlowManager()
        self.logger = logging.getLogger(__name__)
        self._translation_cache: Dict[Tuple[str, str], str] = {}

    
    async def analyze_message(
        self,
        user_message: str,
        conversation_state: Optional[str] = None,
        language: str = "en",
    ) -> MessageAnalysis:
        print("ChatHandler.analyze_message was called")
        t0 = perf_counter()
        intent = await self.intent_recognizer.recognize(user_message)
        t1 = perf_counter()
        print(f"intent_recognizer took {(t1-t0)*1000:.1f}ms  intent={intent}")
        current_state = ConversationState(conversation_state) if conversation_state else ConversationState.WELCOME
        print(f"current_state: {current_state.value}")

        fast_path_response = None
        faq_match = None
        if intent == "overview":
            fast_path_response = self._build_overview_prompt_response(
                current_state=current_state,
                language=language,
            )
            t2 = perf_counter()
            print(f"fast_path overview (no FAQ/LLM call) took {(t2-t0)*1000:.1f}ms")
        else:
            faq_match = await self.faq_handler.get_match(user_message)
            t2 = perf_counter()
            print(f"faq_handler.get_match took {(t2-t1)*1000:.1f}ms")
            if self._should_direct_answer_with_faq(intent, faq_match):
                fast_path_response = self._build_direct_faq_response(
                    faq_match=faq_match,
                    current_state=current_state,
                    language=language,
                    intent=intent,
                )
                print(f"fast_path FAQ answer (no LLM call)  score={faq_match.score:.4f}")
        return MessageAnalysis(
            intent=intent,
            current_state=current_state,
            faq_match=faq_match,
            fast_path_response=fast_path_response,
            t0=t0,
            t1=t1,
            t2=t2,
        )

    async def process_message(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        customer_info: Optional[Dict] = None,
        conversation_state: Optional[str] = None,
        language: str = "en",
        analysis: Optional[MessageAnalysis] = None,
    ) -> Dict[str, any]:
        """
        Process a user message and generate an AI response
        The agent proactively guides the conversation through the booking flow
        """
        analysis = analysis or await self.analyze_message(
            user_message=user_message,
            conversation_state=conversation_state,
            language=language,
        )
        intent = analysis.intent
        current_state = analysis.current_state
        faq_match = analysis.faq_match
        t0 = analysis.t0
        t1 = analysis.t1
        t2 = analysis.t2

        if analysis.fast_path_response:
            out = analysis.fast_path_response
            t_direct = perf_counter()
            if intent == "overview":
                print(f"chat_handler fast_path overview: intent={(t1-t0)*1000:.1f}ms total={(t_direct-t0)*1000:.1f}ms")
            else:
                score = faq_match.score if faq_match else 0.0
                print(f"chat_handler fast_path FAQ: intent={(t1-t0)*1000:.1f}ms faq={(t2-t1)*1000:.1f}ms total={(t_direct-t0)*1000:.1f}ms score={score:.3f}")
            return out

        state_prompt = self.flow_manager.get_state_prompt(current_state, customer_info or {})
        messages = self._build_llm_messages(
            user_message=user_message,
            current_state=current_state,
            intent=intent,
            state_prompt=state_prompt,
            conversation_history=conversation_history,
            customer_info=customer_info,
            faq_match=faq_match,
            language=language,
        )

        if not self.client:
            err = "I'm sorry, the AI service is not configured. Please contact support."
            return {"response": err, "response_en": err, "response_sv": None, "intent": "error", "next_state": conversation_state}

        try:
            _max_tok = self._max_tokens_for_intent(intent, current_state)
            print(f"OpenAI chat.completions.create starting  model={settings.openai_model}  max_tokens={_max_tok}")
            _llm_start = perf_counter()
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                temperature=0.4,
                max_tokens=_max_tok,
            )
            t3 = perf_counter()
            print(f"OpenAI chat.completions.create took {(t3-_llm_start)*1000:.1f}ms")
            raw = response.choices[0].message.content
            response_en, response_sv = self._normalize_model_output(raw, language)
            single = response_en or response_sv or raw
            next_state = self._determine_next_state(current_state, intent, user_message, customer_info)
            out = {
                "response": single,
                "response_en": response_en,
                "response_sv": response_sv,
                "intent": intent,
                "current_state": current_state.value,
                "next_state": next_state.value if next_state else current_state.value,
                "faq_used": faq_match is not None,
                "needs_human": self._should_escalate(user_message, single),
                "should_proceed": self._should_proceed_to_next_state(current_state, intent)
            }
            t4 = perf_counter()
            print(f"ChatHandler.process_message total took {(t4-t0)*1000:.1f}ms")
            return out
        except Exception as e:
            self.logger.exception("OpenAI chat completion failed")
            try:
                t_fail = perf_counter()
                print(f"chat_handler ERROR: intent={(t1-t0)*1000:.1f}ms faq={(t2-t1)*1000:.1f}ms total={(t_fail-t0)*1000:.1f}ms")
            except Exception:
                pass
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

        # If booking intent is clear, move to the booking recommendation step
        if intent == "book" and current_state in [
            ConversationState.PROFILE_COMPLETE,
            ConversationState.RECOMMENDING_BOOKING,
            ConversationState.ANSWERING_QUESTIONS,
        ]:
            return ConversationState.RECOMMENDING_BOOKING

        # If user provides date/time, move to confirmation
        if current_state == ConversationState.COLLECTING_BOOKING_DETAILS:
            # Check if message contains date/time indicators
            time_indicators = ["tomorrow", "today", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "am", "pm", ":", "at"]
            if any(indicator in user_message.lower() for indicator in time_indicators):
                return ConversationState.CONFIRMING_BOOKING

        # If user confirms, move to booking confirmed
        if current_state == ConversationState.CONFIRMING_BOOKING and intent in ["book", "greeting"]:
            return ConversationState.BOOKING_CONFIRMED

        # After profile completion, default to question-answering unless booking is explicit.
        if current_state == ConversationState.PROFILE_COMPLETE:
            return ConversationState.ANSWERING_QUESTIONS

        if current_state == ConversationState.RECOMMENDING_BOOKING:
            return (
                ConversationState.RECOMMENDING_BOOKING
                if intent == "book"
                else ConversationState.ANSWERING_QUESTIONS
            )

        if current_state == ConversationState.ANSWERING_QUESTIONS:
            if intent == "book":
                return ConversationState.RECOMMENDING_BOOKING
            return ConversationState.ANSWERING_QUESTIONS

        # Default: get next state from flow manager
        return self.flow_manager.get_next_state(current_state)

    def _should_proceed_to_next_state(self, current_state: ConversationState, intent: str) -> bool:
        """Determine if we should proactively move to next state"""
        if intent == "book" and current_state in [
            ConversationState.PROFILE_COMPLETE,
            ConversationState.RECOMMENDING_BOOKING,
            ConversationState.ANSWERING_QUESTIONS,
        ]:
            return True
        return False

    def _should_direct_answer_with_faq(self, intent: str, faq_match: Optional[FAQMatch]) -> bool:
        if not faq_match:
            return False
        if faq_match.score < FAQ_DIRECT_RESPONSE_THRESHOLD:
            return False
        return intent not in {"book", "cancel", "frustrated"}

    def _build_direct_faq_response(
        self,
        faq_match: FAQMatch,
        current_state: ConversationState,
        language: str,
        intent: str,
    ) -> Dict[str, any]:
        answer_en = faq_match.answer.strip()
        if faq_match.video_link:
            answer_en = f"{answer_en}\n\nVideo: {faq_match.video_link}"

        response_en = answer_en
        response_sv = faq_match.answer_sv
        if language == "sv" and not response_sv:
            response_sv = self._translate_text(answer_en, "sv") or answer_en

        next_state = current_state
        if current_state in {
            ConversationState.PROFILE_COMPLETE,
            ConversationState.RECOMMENDING_BOOKING,
            ConversationState.ANSWERING_QUESTIONS,
        }:
            next_state = ConversationState.ANSWERING_QUESTIONS

        response_text = response_sv if language == "sv" and response_sv else response_en
        return {
            "response": response_text,
            "response_en": response_en,
            "response_sv": response_sv,
            "intent": intent,
            "current_state": current_state.value,
            "next_state": next_state.value,
            "faq_used": True,
            "needs_human": False,
            "should_proceed": False,
            "faq_video_url": faq_match.video_link or None,
        }

    @staticmethod
    def _build_overview_prompt_response(
        current_state: ConversationState,
        language: str,
    ) -> Dict[str, any]:
        response_en = t("en", "service_overview_prompt")
        response_sv = t("sv", "service_overview_prompt")
        next_state = current_state
        if current_state in {
            ConversationState.PROFILE_COMPLETE,
            ConversationState.RECOMMENDING_BOOKING,
            ConversationState.ANSWERING_QUESTIONS,
        }:
            next_state = ConversationState.ANSWERING_QUESTIONS

        response = response_sv if language == "sv" else response_en
        return {
            "response": response,
            "response_en": response_en,
            "response_sv": response_sv,
            "intent": "overview",
            "current_state": current_state.value,
            "next_state": next_state.value,
            "faq_used": False,
            "needs_human": False,
            "should_proceed": False,
        }

    def _build_llm_messages(
        self,
        *,
        user_message: str,
        current_state: ConversationState,
        intent: str,
        state_prompt: str,
        conversation_history: Optional[List[Dict[str, str]]],
        customer_info: Optional[Dict],
        faq_match: Optional[FAQMatch],
        language: str,
    ) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": build_compact_system_prompt(language)}]
        messages.append(
            {
                "role": "system",
                "content": (
                    f"Current conversation state: {current_state.value}\n"
                    f"Current detected intent: {intent}\n\n"
                    f"{state_prompt}\n\n"
                    "Answer the user's current message first. Keep the reply concise unless they ask for more detail."
                ),
            }
        )
        if faq_match:
            messages.append(
                {
                    "role": "system",
                    "content": f"Relevant FAQ: {faq_match.answer}",
                }
            )
        if customer_info:
            messages.append({"role": "system", "content": f"Customer info: {customer_info}"})
        if conversation_history:
            messages.extend(self._trim_history(conversation_history, intent))
        messages.append({"role": "user", "content": user_message})
        return messages

    @staticmethod
    def _trim_history(conversation_history: List[Dict[str, str]], intent: str) -> List[Dict[str, str]]:
        limit = 4 if intent == "unknown" else 6
        return conversation_history[-limit:]

    @staticmethod
    def _max_tokens_for_intent(intent: str, current_state: ConversationState) -> int:
        if intent == "overview":
            return 90
        if intent == "book" or current_state in {
            ConversationState.RECOMMENDING_BOOKING,
            ConversationState.COLLECTING_BOOKING_DETAILS,
        }:
            return 180
        return 220

    @staticmethod
    def _normalize_model_output(raw: str, language: str) -> tuple[Optional[str], Optional[str]]:
        response_en, response_sv = ChatHandler._parse_bilingual_response(raw)
        if response_en or response_sv:
            if language == "sv" and not response_sv:
                response_sv = response_en
            if language == "en" and not response_en:
                response_en = response_sv
            return response_en, response_sv
        raw = (raw or "").strip()
        if not raw:
            return None, None
        if language == "sv":
            return None, raw
        return raw, None

    def _translate_text(self, text: str, target_lang: str) -> Optional[str]:
        if not text or not self.client:
            return None
        cache_key = (target_lang, text)
        cached = self._translation_cache.get(cache_key)
        if cached:
            return cached
        target_name = "Swedish" if target_lang == "sv" else "English"
        try:
            r = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": f"Reply with only the {target_name} translation. No other text, no explanation."},
                    {"role": "user", "content": f"Translate to {target_name}:\n\n{text}"}
                ],
                temperature=0,
                max_tokens=300,
            )
            out = (r.choices[0].message.content or "").strip()
            if out:
                self._translation_cache[cache_key] = out
                return out
            return None
        except Exception:
            return None

    def _get_swedish_from_ai(self, text_en: str) -> Optional[str]:
        return self._translate_text(text_en, "sv")

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
        elif "---SV---" in raw:
            rest = raw.split("---SV---", 1)
            en = rest[0].strip() or None
            sv = rest[1].strip() or None if len(rest) > 1 else None
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

    @staticmethod
    def warmup() -> bool:
        client = _get_openai_client()
        if not client:
            return False
        try:
            client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": "Reply with OK."},
                    {"role": "user", "content": "warmup"},
                ],
                temperature=0,
                max_tokens=2,
            )
            return True
        except Exception:
            return False