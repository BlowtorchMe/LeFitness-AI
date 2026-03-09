"""
Web chat API - allows chat from a web page instead of Messenger/Instagram
Same flow as Messenger/Instagram: welcome, profile (name, email, phone), then booking link.
"""
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.database import get_db, SessionLocal
from app.models.conversation import ConversationChannel, MessageDirection, Conversation
from app.services.lead_service import LeadService
from app.services.conversation_service import ConversationService
from app.ai.chat_handler import ChatHandler
from app.ai.conversation_flow import ConversationFlow
from app.ai.translations import get as t
from app.ai.user_translate import translate_text as translate_user_message
from app.ai.faq_handler import FAQHandler

router = APIRouter()
chat_handler = ChatHandler()
faq_handler = FAQHandler()


# =========================
# MACHINE / QR CONFIG
# =========================

MEDIA_BASE_URL = "http://192.168.1.57:8080/videos"

MACHINES = {
    "leg-press": {
        "name": "Leg Press",
        "description_en": "The leg press machine mainly trains the quadriceps and glutes. Keep your feet hip-width apart, press through your heels, and avoid locking your knees at the top.",
        "description_sv": "Leg press-maskinen tränar främst framsida lår och säte. Ha fötterna ungefär höftbrett, pressa genom hälarna och undvik att låsa knäna i toppläget.",
    },
    "lat-pulldown": {
        "name": "Lat Pulldown",
        "description_en": "The lat pulldown mainly trains the back, especially the lats, and also assists with biceps activation. Pull the bar down with control toward the upper chest and avoid shrugging your shoulders.",
        "description_sv": "Lat pulldown tränar främst ryggen, särskilt lats, och hjälper även till att aktivera biceps. Dra ner stången kontrollerat mot övre delen av bröstet och undvik att dra upp axlarna.",
    },
    "chest-press": {
        "name": "Chest Press",
        "description_en": "The chest press machine mainly trains the chest, shoulders, and triceps. Keep your back against the pad, wrists straight, and press the handles forward in a controlled motion.",
        "description_sv": "Chest press-maskinen tränar främst bröst, axlar och triceps. Håll ryggen mot ryggstödet, handlederna raka och pressa handtagen framåt med kontroll.",
    },
}


def _build_video_url(machine_slug: str) -> str:
    return f"{MEDIA_BASE_URL}/{machine_slug}.mp4"


def _normalize_machine_slug(text: str) -> str:
    return (text or "").strip().lower()


def _get_machine_from_message(message_text: str) -> Optional[dict]:
    slug = _normalize_machine_slug(message_text)
    machine = MACHINES.get(slug)
    if not machine:
        return None

    return {
        "slug": slug,
        "name": machine["name"],
        "description_en": machine["description_en"],
        "description_sv": machine["description_sv"],
        "video_url": _build_video_url(slug),
    }


def _fill_sv_background(conversation_id: int, text_en: str) -> None:
    try:
        db = SessionLocal()
        try:
            sv = chat_handler._get_swedish_from_ai(text_en)
            if sv:
                conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
                if conv:
                    conv.message_text_sv = sv
                    db.commit()
        finally:
            db.close()
    except Exception:
        pass


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
    machine_entry: Optional[bool] = False


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
    faq_video_url: Optional[str] = None


class ChatAttachment(BaseModel):
    type: str
    url: str
    title: Optional[str] = None


class ChatOutgoingMessage(BaseModel):
    text: str
    attachments: Optional[List[ChatAttachment]] = None


@router.post("", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    session_id = request.session_id or uuid.uuid4().hex
    sender_id = session_id
    message_text = (request.message or "").strip()
    requested_lang = (request.language or "en").strip().lower()
    machine_entry = bool(request.machine_entry)

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
                history.append(
                    ChatMessageHistory(
                        role="user" if c.direction == MessageDirection.INBOUND else "bot",
                        text=te,
                        text_en=te,
                        text_sv=ts,
                    )
                )
            return ChatResponse(
                session_id=session_id,
                messages=[],
                history=history,
                language=lead.language or "en",
            )

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
            commit=False,
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
                commit=False,
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
                commit=False,
            )
            lead.conversation_state = "recommending_booking"

        lead_service.db.commit()
        return ChatResponse(
            session_id=session_id,
            messages=responses,
            language=lead.language or "en",
        )

    lang_lead = _lang(lead)
    if lead.notes and lead.notes.startswith("profile_status:"):
        user_en = user_sv = message_text
    else:
        user_en = message_text if lang_lead == "en" else (translate_user_message(message_text, "sv", "en") or message_text)
        user_sv = message_text if lang_lead == "sv" else (translate_user_message(message_text, "en", "sv") or message_text)

    conversation_service.save_message(
        lead_id=lead.id,
        channel=ConversationChannel.WEB,
        direction=MessageDirection.INBOUND,
        message_text_en=user_en,
        message_text_sv=user_sv,
        messenger_id=sender_id,
        commit=False,
    )
    lead_service.increment_message_count(lead.id, commit=False)

    # QR-entry: hoppa över onboarding direkt
    machine = _get_machine_from_message(message_text)
    if machine and machine_entry:
        response_text = machine["description_sv"] if lang_lead == "sv" else machine["description_en"]
        responses.append(response_text)

        conversation_service.save_message(
            lead_id=lead.id,
            channel=ConversationChannel.WEB,
            direction=MessageDirection.OUTBOUND,
            message_text_en=machine["description_en"],
            message_text_sv=machine["description_sv"],
            messenger_id=sender_id,
            intent="machine_info",
            ai_response=response_text,
            faq_used="true",
            commit=False,
        )

        lead_service.increment_message_count(lead.id, commit=False)
        lead_service.db.commit()

        return ChatResponse(
            session_id=session_id,
            messages=responses,
            language=lead.language or "en",
            faq_video_url=machine["video_url"],
        )

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
                commit=False,
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
                commit=False,
            )
            lead.conversation_state = "recommending_booking"

        lead_service.db.commit()
        return ChatResponse(
            session_id=session_id,
            messages=responses,
            language=lead.language or "en",
        )

    if lead.notes and lead.notes.startswith("profile_status:"):
        status = lead.notes.split(":")[1]
        if status == "waiting_for_name" and message_text.strip():
            lead.name = message_text.strip()
        elif status == "waiting_for_email" and "@" in message_text:
            lead.email = message_text.strip()
        elif status == "waiting_for_phone":
            phone = message_text.strip().replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
            if phone and (phone.isdigit() or phone.startswith("+")):
                lead.phone = phone

        next_status, prompt_en, prompt_sv = _next_profile_prompt(lead)
        if next_status != "complete":
            lead.notes = f"profile_status:{next_status}"
            prompt = prompt_sv if lang_lead == "sv" else prompt_en
            responses.append(prompt)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=ConversationChannel.WEB,
                direction=MessageDirection.OUTBOUND,
                message_text_en=prompt_en,
                message_text_sv=prompt_sv,
                messenger_id=sender_id,
                commit=False,
            )
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
                commit=False,
            )
            lead.conversation_state = "recommending_booking"

        lead_service.db.commit()
        return ChatResponse(
            session_id=session_id,
            messages=responses,
            language=lead.language or "en",
        )

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
            commit=False,
        )
        lead.notes = "calendar_booking_pending_verification"
        lead_service.db.commit()
        return ChatResponse(
            session_id=session_id,
            messages=responses,
            language=lead.language or "en",
        )

    current_state = lead.conversation_state or "welcome"
    if current_state == "gathering_profile" or (lead.notes and lead.notes.startswith("profile_status:")):
        lead_service.db.commit()
        fallback = t(_lang(lead), "enter_info_above")
        return ChatResponse(
            session_id=session_id,
            messages=responses if responses else [fallback],
            language=lead.language or "en",
        )

    # vanlig scanner i chatten ska också fungera
    machine = _get_machine_from_message(message_text)
    if machine:
        response_text = machine["description_sv"] if lang_lead == "sv" else machine["description_en"]
        responses.append(response_text)

        conversation_service.save_message(
            lead_id=lead.id,
            channel=ConversationChannel.WEB,
            direction=MessageDirection.OUTBOUND,
            message_text_en=machine["description_en"],
            message_text_sv=machine["description_sv"],
            messenger_id=sender_id,
            intent="machine_info",
            ai_response=response_text,
            faq_used="true",
            commit=False,
        )

        lead_service.increment_message_count(lead.id, commit=False)
        lead_service.db.commit()

        return ChatResponse(
            session_id=session_id,
            messages=responses,
            language=lead.language or "en",
            faq_video_url=machine["video_url"],
        )

    faq = await faq_handler.get_answer(message_text)
    if faq:
        answer_en = (faq.get("answer") or "").strip()
        video = faq.get("video_link")

        answer_sv = None
        if answer_en and lang_lead == "sv":
            answer_sv = translate_user_message(answer_en, "en", "sv") or answer_en

        response_text = answer_sv if (lang_lead == "sv" and answer_sv) else answer_en
        if not response_text:
            response_text = answer_en or "Sorry, I couldn't find an answer."

        responses.append(response_text)

        conv = conversation_service.save_message(
            lead_id=lead.id,
            channel=ConversationChannel.WEB,
            direction=MessageDirection.OUTBOUND,
            message_text_en=answer_en,
            message_text_sv=answer_sv,
            messenger_id=sender_id,
            intent="faq",
            ai_response=response_text,
            faq_used="true",
            commit=False,
        )
        if answer_en and not answer_sv:
            background_tasks.add_task(_fill_sv_background, conv.id, answer_en)

        lead_service.increment_message_count(lead.id, commit=False)
        lead_service.db.commit()

        return ChatResponse(
            session_id=session_id,
            messages=responses,
            language=lead.language or "en",
            faq_video_url=video,
        )

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
            resp_en, resp_sv = _recommend_booking_both(lead)
        elif intent == "book" and current_state == "recommending_booking":
            resp_en = t("en", "book_link_once", link=link)
            resp_sv = t("sv", "book_link_once", link=link)
            lead.notes = "waiting_for_calendar_booking"
            lead.conversation_state = "recommending_booking"
        else:
            resp_en = ai_response.get("response_en") or ai_response.get("response", "")
            resp_sv = ai_response.get("response_sv")

        response_text = (resp_sv if lang_lead == "sv" else resp_en) or resp_en or ai_response.get("response", "")
        responses.append(response_text)

        conv = conversation_service.save_message(
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
        if resp_en and not resp_sv:
            background_tasks.add_task(_fill_sv_background, conv.id, resp_en)

        lead_service.db.commit()
        return ChatResponse(
            session_id=session_id,
            messages=responses,
            language=lead.language or "en",
            faq_video_url=ai_response.get("faq_video_url"),
        )

    resp_en = ai_response.get("response_en") or ai_response.get("response", "")
    resp_sv = ai_response.get("response_sv")

    if lang_lead == "sv":
        response_text = resp_sv or resp_en or ai_response.get("response", "")
    else:
        response_text = resp_en or ai_response.get("response", "")

    if ai_response.get("next_state") and ai_response["next_state"] != current_state:
        lead.conversation_state = ai_response["next_state"]

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

    responses.append(response_text)

    conv = conversation_service.save_message(
        lead_id=lead.id,
        channel=ConversationChannel.WEB,
        direction=MessageDirection.OUTBOUND,
        message_text_en=resp_en,
        message_text_sv=resp_sv,
        messenger_id=sender_id,
        intent=ai_response.get("intent"),
        ai_response=response_text,
        faq_used="true" if ai_response.get("faq_used") else None,
        commit=False,
    )
    if resp_en and not resp_sv:
        background_tasks.add_task(_fill_sv_background, conv.id, resp_en)

    lead_service.increment_message_count(lead.id, commit=False)
    lead_service.db.commit()

    return ChatResponse(
        session_id=session_id,
        messages=responses,
        language=lead.language or "en",
        faq_video_url=ai_response.get("faq_video_url"),
    )