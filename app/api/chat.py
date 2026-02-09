"""
Web chat API - allows chat from a web page instead of Messenger/Instagram
Same flow as Messenger/Instagram: welcome, profile (name, email, phone), then booking link.
"""
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database.database import get_db
from app.models.conversation import ConversationChannel, MessageDirection, Conversation
from app.services.lead_service import LeadService
from app.services.conversation_service import ConversationService
from app.ai.chat_handler import ChatHandler
from app.ai.conversation_flow import ConversationFlow
from app.ai.translations import get as t
from app.ai.user_translate import translate_text as translate_user_message

router = APIRouter()
chat_handler = ChatHandler()


def _get_calendar_link() -> str:
    flow = ConversationFlow()
    return flow._get_calendar_link(datetime.now())


def _lang(lead) -> str:
    return "sv" if (lead.language == "sv") else "en"


def _recommend_booking_message(lead) -> str:
    return t(_lang(lead), "booking_intro", name=lead.name or "Customer", link=_get_calendar_link())


def _recommend_booking_both(lead) -> tuple:
    name = lead.name or "Customer"
    link = _get_calendar_link()
    return t("en", "booking_intro", name=name, link=link), t("sv", "booking_intro", name=name, link=link)


def _next_profile_prompt(lead) -> tuple:
    """Return (next_status, message_en, message_sv) for profile gathering. message_* is None when complete."""
    if not lead.name or lead.name == "Customer":
        return "waiting_for_name", t("en", "please_enter_name"), t("sv", "please_enter_name")
    if not lead.email:
        return "waiting_for_email", t("en", "please_enter_email"), t("sv", "please_enter_email")
    if not lead.phone:
        return "waiting_for_phone", t("en", "please_enter_phone"), t("sv", "please_enter_phone")
    return "complete", None, None


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: Optional[str] = None
    language: Optional[str] = None


class ChatMessageHistory(BaseModel):
    role: str
    text: Optional[str] = None
    text_en: Optional[str] = None
    text_sv: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    messages: List[str]
    history: Optional[List[ChatMessageHistory]] = None
    language: Optional[str] = None


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """
    Web chat endpoint. Same flow as Messenger/Instagram: welcome, name, email, phone, then booking link.
    """
    session_id = request.session_id or uuid.uuid4().hex
    sender_id = session_id
    message_text = (request.message or "").strip()
    requested_lang = (request.language or "en").strip().lower()
    if requested_lang not in ("en", "sv"):
        requested_lang = "en"
    responses: List[str] = []

    lead_service = LeadService(db)
    conversation_service = ConversationService(db)
    lead = lead_service.get_lead_by_messenger_id(sender_id)

    if not lead:
        lead = lead_service.create_lead(
            name="Customer",
            messenger_id=sender_id,
            platform="web",
            email=None,
            source="web_chat",
        )
        lead.conversation_state = "welcome"
        lead.language = requested_lang
        lead_service.db.commit()
    else:
        if lead.language != requested_lang:
            lead.language = requested_lang
            lead_service.db.commit()

    if not message_text:
        convs = (
            db.query(Conversation)
            .filter(
                Conversation.lead_id == lead.id,
                Conversation.channel == ConversationChannel.WEB,
            )
            .order_by(Conversation.created_at.asc())
            .all()
        )
        if convs:
            history = []
            for c in convs:
                te = c.message_text_en or c.message_text_sv
                ts = c.message_text_sv
                history.append(ChatMessageHistory(
                    role="user" if c.direction == MessageDirection.INBOUND else "bot",
                    text=te,
                    text_en=te,
                    text_sv=ts,
                ))
            return ChatResponse(session_id=session_id, messages=[], history=history, language=lead.language or "en")

        welcome_en = chat_handler.get_welcome_message(language="en")
        welcome_sv = chat_handler.get_welcome_message(language="sv")
        welcome = welcome_sv if _lang(lead) == "sv" else welcome_en
        responses.append(welcome)
        conversation_service.save_message(
            lead_id=lead.id,
            channel=ConversationChannel.WEB,
            direction=MessageDirection.OUTBOUND,
            message_text_en=welcome_en,
            message_text_sv=welcome_sv,
            messenger_id=sender_id,
        )
        status, prompt_en, prompt_sv = _next_profile_prompt(lead)
        if status != "complete":
            prompt = prompt_sv if _lang(lead) == "sv" else prompt_en
            responses.append(prompt)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=ConversationChannel.WEB,
                direction=MessageDirection.OUTBOUND,
                message_text_en=prompt_en,
                message_text_sv=prompt_sv,
                messenger_id=sender_id,
            )
            lead.notes = f"profile_status:{status}"
            lead.conversation_state = "gathering_profile"
        else:
            lead.conversation_state = "profile_complete"
            lead.notes = "waiting_for_calendar_booking"
            book_en, book_sv = _recommend_booking_both(lead)
            responses.append(book_sv if _lang(lead) == "sv" else book_en)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=ConversationChannel.WEB,
                direction=MessageDirection.OUTBOUND,
                message_text_en=book_en,
                message_text_sv=book_sv,
                messenger_id=sender_id,
            )
            lead.conversation_state = "recommending_booking"
        lead_service.db.commit()
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    lang_lead = _lang(lead)
    user_en = message_text if lang_lead == "en" else (translate_user_message(message_text, "sv", "en") or message_text)
    user_sv = message_text if lang_lead == "sv" else (translate_user_message(message_text, "en", "sv") or message_text)
    conversation_service.save_message(
        lead_id=lead.id,
        channel=ConversationChannel.WEB,
        direction=MessageDirection.INBOUND,
        message_text_en=user_en,
        message_text_sv=user_sv,
        messenger_id=sender_id,
    )
    lead_service.increment_message_count(lead.id)
    lead_service.db.commit()

    if not lead.conversation_state or lead.conversation_state == "welcome":
        status, prompt_en, prompt_sv = _next_profile_prompt(lead)
        if status != "complete":
            prompt = prompt_sv if lang_lead == "sv" else prompt_en
            responses.append(prompt)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=ConversationChannel.WEB,
                direction=MessageDirection.OUTBOUND,
                message_text_en=prompt_en,
                message_text_sv=prompt_sv,
                messenger_id=sender_id,
            )
            lead.notes = f"profile_status:{status}"
            lead.conversation_state = "gathering_profile"
        else:
            lead.conversation_state = "profile_complete"
            lead.notes = "waiting_for_calendar_booking"
            book_en, book_sv = _recommend_booking_both(lead)
            responses.append(book_sv if lang_lead == "sv" else book_en)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=ConversationChannel.WEB,
                direction=MessageDirection.OUTBOUND,
                message_text_en=book_en,
                message_text_sv=book_sv,
                messenger_id=sender_id,
            )
            lead.conversation_state = "recommending_booking"
        lead_service.db.commit()
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    if lead.notes and lead.notes.startswith("profile_status:"):
        status = lead.notes.split(":")[1]
        if status == "waiting_for_name":
            if message_text.strip():
                lead.name = message_text.strip()
                lead_service.db.commit()
        elif status == "waiting_for_email":
            if "@" in message_text:
                lead.email = message_text.strip()
                lead_service.db.commit()
        elif status == "waiting_for_phone":
            phone = message_text.strip().replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
            if phone and (phone.isdigit() or phone.startswith("+")):
                lead.phone = phone
                lead_service.db.commit()

        next_status, prompt_en, prompt_sv = _next_profile_prompt(lead)
        if next_status != "complete":
            lead.notes = f"profile_status:{next_status}"
            lead_service.db.commit()
            prompt = prompt_sv if lang_lead == "sv" else prompt_en
            responses.append(prompt)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=ConversationChannel.WEB,
                direction=MessageDirection.OUTBOUND,
                message_text_en=prompt_en,
                message_text_sv=prompt_sv,
                messenger_id=sender_id,
            )
        else:
            lead.conversation_state = "profile_complete"
            lead.notes = "waiting_for_calendar_booking"
            lead_service.db.commit()
            book_en, book_sv = _recommend_booking_both(lead)
            responses.append(book_sv if lang_lead == "sv" else book_en)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=ConversationChannel.WEB,
                direction=MessageDirection.OUTBOUND,
                message_text_en=book_en,
                message_text_sv=book_sv,
                messenger_id=sender_id,
            )
            lead.conversation_state = "recommending_booking"
        lead_service.db.commit()
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    if lead.notes == "waiting_for_calendar_booking" and any(
        w in message_text.lower() for w in ["booked", "done", "yes", "confirmed", "scheduled"]
    ):
        confirm_en = t("en", "booking_confirm_calendar")
        confirm_sv = t("sv", "booking_confirm_calendar")
        responses.append(confirm_sv if lang_lead == "sv" else confirm_en)
        conversation_service.save_message(
            lead_id=lead.id,
            channel=ConversationChannel.WEB,
            direction=MessageDirection.OUTBOUND,
            message_text_en=confirm_en,
            message_text_sv=confirm_sv,
            messenger_id=sender_id,
        )
        lead.notes = "calendar_booking_pending_verification"
        lead_service.db.commit()
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    current_state = lead.conversation_state or "welcome"
    if current_state == "gathering_profile" or (lead.notes and lead.notes.startswith("profile_status:")):
        lead_service.db.commit()
        fallback = t(_lang(lead), "enter_info_above")
        return ChatResponse(session_id=session_id, messages=responses if responses else [fallback], language=lead.language or "en")

    conversation_history = conversation_service.get_conversation_history_for_ai(
        lead_id=lead.id,
        messenger_id=sender_id,
        lang=lang_lead,
    )
    ai_response = await chat_handler.process_message(
        user_message=message_text,
        conversation_history=conversation_history,
        customer_info={"name": lead.name, "phone": lead.phone},
        conversation_state=current_state,
        language=_lang(lead),
    )

    if ai_response.get("should_proceed"):
        intent = ai_response.get("intent")
        link = _get_calendar_link()
        if current_state == "profile_complete":
            lead.conversation_state = "recommending_booking"
            lead.notes = "waiting_for_calendar_booking"
            lead_service.db.commit()
            resp_en, resp_sv = _recommend_booking_both(lead)
        elif intent == "book" and current_state == "recommending_booking":
            resp_en = t("en", "book_link_once", link=link)
            resp_sv = t("sv", "book_link_once", link=link)
            lead.notes = "waiting_for_calendar_booking"
            lead.conversation_state = "recommending_booking"
            lead_service.db.commit()
        else:
            resp_en = ai_response.get("response_en") or ai_response.get("response", "")
            resp_sv = ai_response.get("response_sv")
        response_text = (resp_sv if lang_lead == "sv" else resp_en) or resp_en or ai_response.get("response", "")
        responses.append(response_text)
        conversation_service.save_message(
            lead_id=lead.id,
            channel=ConversationChannel.WEB,
            direction=MessageDirection.OUTBOUND,
            message_text_en=resp_en,
            message_text_sv=resp_sv,
            messenger_id=sender_id,
            intent=ai_response.get("intent"),
            ai_response=response_text,
            faq_used="true" if ai_response.get("faq_used") else None,
        )
        lead_service.db.commit()
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    resp_en = ai_response.get("response_en") or ai_response.get("response", "")
    resp_sv = ai_response.get("response_sv")
    if lang_lead == "sv":
        response_text = resp_sv or resp_en or ai_response.get("response", "")
    else:
        response_text = resp_en or ai_response.get("response", "")
    if ai_response.get("next_state") and ai_response["next_state"] != current_state:
        lead.conversation_state = ai_response["next_state"]
        lead_service.db.commit()

    calendar_keywords = ["calendar", "available", "time slot", "schedule", "appointment", "book", "booking"]
    if any(k in message_text.lower() for k in calendar_keywords) and current_state in [
        "profile_complete",
        "recommending_booking",
        "collecting_booking_details",
    ]:
        link = _get_calendar_link()
        resp_en = t("en", "book_link_once", link=link)
        resp_sv = t("sv", "book_link_once", link=link)
        response_text = resp_sv if lang_lead == "sv" else resp_en
        lead.notes = "waiting_for_calendar_booking"
        lead.conversation_state = "recommending_booking"
        lead_service.db.commit()

    responses.append(response_text)
    conversation_service.save_message(
        lead_id=lead.id,
        channel=ConversationChannel.WEB,
        direction=MessageDirection.OUTBOUND,
        message_text_en=resp_en,
        message_text_sv=resp_sv,
        messenger_id=sender_id,
        intent=ai_response.get("intent"),
        ai_response=response_text,
        faq_used="true" if ai_response.get("faq_used") else None,
    )
    lead_service.increment_message_count(lead.id)
    lead_service.db.commit()

    return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")
