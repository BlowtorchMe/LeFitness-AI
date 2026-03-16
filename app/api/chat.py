"""
Web chat API with a minimal request pipeline:
1. lightweight initial greeting
2. deterministic profile collection
3. FAQ/direct answers when possible
4. LLM fallback for broader questions
"""
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.chat_handler import ChatHandler
from app.ai.conversation_flow import ConversationFlow
from app.ai.translations import get as t
from app.database.database import SessionLocal, get_db
from app.models.conversation import Conversation, ConversationChannel, MessageDirection
from app.services.conversation_service import ConversationService
from app.services.lead_service import LeadService

router = APIRouter()
chat_handler = ChatHandler()

PROFILE_STATUS_PREFIX = "profile_status:"
BOOKING_STATES = {
    "profile_complete",
    "answering_questions",
    "recommending_booking",
    "collecting_booking_details",
}
CALENDAR_CONFIRM_PATTERNS = (
    r"^(yes|yep|yeah|done|confirmed|scheduled|booked)[.! ]*$",
    r"^(i('ve| have)?\s+booked(\s+it)?|i\s+booked(\s+it)?|booked\s+it|it's\s+booked|it is booked)[.! ]*$",
    r"^(i('ve| have)?\s+scheduled(\s+it)?|i\s+scheduled(\s+it)?|scheduled\s+it|done\s+booking)[.! ]*$",
    r"^(yes[, ]+i('ve| have)?\s+(booked|scheduled)(\s+it)?)[.! ]*$",
)


# Machine descriptions for QR-code entry
# MACHINE_VIDEO_BASE_URL = (getattr(__import__('app.config', fromlist=['settings']).config, 'settings', None) and
#                           __import__('app.config', fromlist=['settings']).config.settings.machine_video_base_url or "").rstrip("/") if False else ""

MACHINES = {
    "leg-press": {
        "name": "Leg Press",
        "description_en": "The leg press machine mainly trains the quadriceps and glutes. Keep your feet hip-width apart, press through your heels, and avoid locking your knees at the top.",
        "description_sv": "Leg press-maskinen tränar främst framsida lår och säte. Ha fötterna ungefär höftbrett, pressa genom hälarna och undvik att låsa knäna i toppläget.",
    },
    "lat-pulldown": {
        "name": "Lat Pulldown",
        "description_en": "The lat pulldown mainly trains the back, especially the lats, and also assists with biceps activation. Pull the bar down with control toward the upper chest.",
        "description_sv": "Lat pulldown tränar främst ryggen, särskilt lats, och hjälper även till att aktivera biceps. Dra ner stången kontrollerat mot övre delen av bröstet.",
    },
    "chest-press": {
        "name": "Chest Press",
        "description_en": "The chest press machine mainly trains the chest, shoulders, and triceps. Keep your back against the pad and press the handles forward in a controlled motion.",
        "description_sv": "Chest press-maskinen tränar främst bröst, axlar och triceps. Håll ryggen mot ryggstödet och pressa handtagen framåt med kontroll.",
    },
}


def _build_machine_video_url(slug: str) -> Optional[str]:
    from app.config import settings as _s
    base = (_s.machine_video_base_url or "").rstrip("/")
    return f"{base}/{slug}.mp4" if base else None


def _get_machine_from_message(message_text: str) -> Optional[dict]:
    slug = (message_text or "").strip().lower()
    machine = MACHINES.get(slug)
    if not machine:
        return None
    return {
        "slug": slug,
        "name": machine["name"],
        "description_en": machine["description_en"],
        "description_sv": machine["description_sv"],
        "video_url": _build_machine_video_url(slug),
    }


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


def _fill_translation_background(conversation_id: int, source_text: str, target_lang: str) -> None:
    try:
        db = SessionLocal()
        try:
            translated = chat_handler._translate_text(source_text, target_lang)
            if not translated:
                return
            conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                return
            if target_lang == "sv":
                conv.message_text_sv = translated
            else:
                conv.message_text_en = translated
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def _normalize_lang(lang: Optional[str]) -> str:
    value = (lang or "en").strip().lower()
    return value if value in {"en", "sv"} else "en"


def _lang(lead) -> str:
    return "sv" if getattr(lead, "language", None) == "sv" else "en"


def _select_lang_text(lang: str, text_en: Optional[str], text_sv: Optional[str], fallback: str = "") -> str:
    if lang == "sv":
        return text_sv or text_en or fallback
    return text_en or text_sv or fallback


def _get_calendar_link() -> str:
    flow = ConversationFlow()
    return flow._get_calendar_link(datetime.now())


def _recommend_booking_both(lead) -> tuple[str, str]:
    name = lead.name or "Customer"
    link = _get_calendar_link()
    return (
        t("en", "booking_intro", name=name, link=link),
        t("sv", "booking_intro", name=name, link=link),
    )


def _follow_up_booking_both(lead) -> tuple[str, str]:
    name = lead.name or "Customer"
    link = _get_calendar_link()
    return (
        t("en", "booking_follow_up", name=name, link=link),
        t("sv", "booking_follow_up", name=name, link=link),
    )


def _sanitize_bilingual_output(
    text_en: Optional[str],
    text_sv: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    if text_en and ("---SV---" in text_en or "---EN---" in text_en):
        parsed_en, parsed_sv = ChatHandler._parse_bilingual_response(text_en)
        text_en = parsed_en or text_en
        text_sv = text_sv or parsed_sv
    if text_sv and ("---SV---" in text_sv or "---EN---" in text_sv):
        parsed_en, parsed_sv = ChatHandler._parse_bilingual_response(text_sv)
        text_en = text_en or parsed_en
        text_sv = parsed_sv or text_sv
    return text_en, text_sv


def _is_calendar_confirmation(message_text: str) -> bool:
    normalized = " ".join((message_text or "").strip().lower().split())
    if not normalized:
        return False
    return any(re.fullmatch(pattern, normalized) for pattern in CALENDAR_CONFIRM_PATTERNS)


def _profile_status(lead) -> Optional[str]:
    notes = getattr(lead, "notes", None) or ""
    if notes.startswith(PROFILE_STATUS_PREFIX):
        return notes[len(PROFILE_STATUS_PREFIX) :]
    return None


def _set_profile_status(lead, status: str) -> None:
    lead.notes = f"{PROFILE_STATUS_PREFIX}{status}"


def _next_profile_prompt(lead) -> tuple[str, Optional[str], Optional[str]]:
    if not lead.name or lead.name == "Customer":
        return "waiting_for_name", t("en", "please_enter_name"), t("sv", "please_enter_name")
    if not lead.email:
        return "waiting_for_email", t("en", "please_enter_email"), t("sv", "please_enter_email")
    if not lead.phone:
        return "waiting_for_phone", t("en", "please_enter_phone"), t("sv", "please_enter_phone")
    return "complete", None, None


def _is_valid_phone(phone: str) -> bool:
    normalized = phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    return bool(normalized) and (normalized.isdigit() or normalized.startswith("+"))


def _initial_messages(lang: str) -> List[str]:
    welcome_en = chat_handler.get_welcome_message(language="en")
    welcome_sv = chat_handler.get_welcome_message(language="sv")
    prompt_en = t("en", "please_enter_name")
    prompt_sv = t("sv", "please_enter_name")
    return [
        _select_lang_text(lang, welcome_en, welcome_sv),
        _select_lang_text(lang, prompt_en, prompt_sv),
    ]


def _load_web_conversations(db: Session, lead_id: int) -> List[Conversation]:
    return (
        db.query(Conversation)
        .filter(
            Conversation.lead_id == lead_id,
            Conversation.channel == ConversationChannel.WEB,
        )
        .order_by(Conversation.created_at.asc())
        .all()
    )


def _history_from_conversations(conversations: List[Conversation]) -> List[ChatMessageHistory]:
    history: List[ChatMessageHistory] = []
    for conv in conversations:
        text_en = conv.message_text_en or conv.message_text_sv
        history.append(
            ChatMessageHistory(
                role="user" if conv.direction == MessageDirection.INBOUND else "bot",
                text=text_en,
                text_en=text_en,
                text_sv=conv.message_text_sv,
            )
        )
    return history


def _should_send_booking_follow_up(lead, conversations: List[Conversation]) -> bool:
    if not conversations:
        return False
    if lead.conversation_state not in {"profile_complete", "recommending_booking", "answering_questions"}:
        return False
    if lead.notes == "calendar_booking_pending_verification":
        return False
    last_message_at = conversations[-1].created_at
    if not last_message_at:
        return False
    return last_message_at <= datetime.utcnow() - timedelta(days=1)


def _save_outbound_message(
    conversation_service: ConversationService,
    lead_id: int,
    sender_id: str,
    text_en: Optional[str],
    text_sv: Optional[str],
    *,
    commit: bool = False,
    intent: Optional[str] = None,
    ai_response: Optional[str] = None,
    faq_used: Optional[bool] = None,
    flush: bool = False,
    refresh: bool = False,
) -> Conversation:
    return conversation_service.save_message(
        lead_id=lead_id,
        channel=ConversationChannel.WEB,
        direction=MessageDirection.OUTBOUND,
        message_text_en=text_en,
        message_text_sv=text_sv,
        messenger_id=sender_id,
        intent=intent,
        ai_response=ai_response,
        faq_used="true" if faq_used else None,
        commit=commit,
        flush=flush,
        refresh=refresh,
    )


def _append_bot_message(
    responses: List[str],
    conversation_service: ConversationService,
    lead,
    sender_id: str,
    lang: str,
    text_en: Optional[str],
    text_sv: Optional[str],
    background_tasks: Optional[BackgroundTasks] = None,
    *,
    commit: bool = False,
    intent: Optional[str] = None,
    ai_response: Optional[str] = None,
    faq_used: Optional[bool] = None,
) -> Conversation:
    text_en, text_sv = _sanitize_bilingual_output(text_en, text_sv)
    response_text = _select_lang_text(lang, text_en, text_sv)
    responses.append(response_text)
    needs_translation_id = bool(background_tasks and ((text_en and not text_sv) or (text_sv and not text_en)))
    conv = _save_outbound_message(
        conversation_service,
        lead.id,
        sender_id,
        text_en,
        text_sv,
        commit=commit,
        intent=intent,
        ai_response=ai_response or response_text,
        faq_used=faq_used,
        flush=needs_translation_id,
        refresh=needs_translation_id,
    )
    if background_tasks:
        if text_en and not text_sv:
            background_tasks.add_task(_fill_translation_background, conv.id, text_en, "sv")
        elif text_sv and not text_en:
            background_tasks.add_task(_fill_translation_background, conv.id, text_sv, "en")
    return conv


def _create_web_lead(lead_service: LeadService, sender_id: str, requested_lang: str):
    lead = lead_service.create_lead(
        name="Customer",
        messenger_id=sender_id,
        platform="web",
        email=None,
        source="web_chat",
        commit=False,
    )
    lead.language = requested_lang
    lead.conversation_state = "gathering_profile"
    return lead


def _persist_initial_messages(
    lead,
    conversation_service: ConversationService,
    sender_id: str,
) -> None:
    welcome_en = chat_handler.get_welcome_message(language="en")
    welcome_sv = chat_handler.get_welcome_message(language="sv")
    _save_outbound_message(conversation_service, lead.id, sender_id, welcome_en, welcome_sv, commit=False)
    next_status, prompt_en, prompt_sv = _next_profile_prompt(lead)
    if next_status == "complete":
        lead.conversation_state = "recommending_booking"
        lead.notes = "waiting_for_calendar_booking"
        book_en, book_sv = _recommend_booking_both(lead)
        _save_outbound_message(conversation_service, lead.id, sender_id, book_en, book_sv, commit=False)
        return
    lead.conversation_state = "gathering_profile"
    _set_profile_status(lead, next_status)
    _save_outbound_message(conversation_service, lead.id, sender_id, prompt_en, prompt_sv, commit=False)


def _prepare_inbound_texts(lead, message_text: str) -> tuple[Optional[str], Optional[str]]:
    if _profile_status(lead):
        return message_text, message_text
    if _lang(lead) == "sv":
        return None, message_text
    return message_text, None


def _update_profile_from_message(lead, message_text: str) -> None:
    status = _profile_status(lead)
    if status == "waiting_for_name" and message_text.strip():
        lead.name = message_text.strip()
    elif status == "waiting_for_email" and "@" in message_text:
        lead.email = message_text.strip()
    elif status == "waiting_for_phone" and _is_valid_phone(message_text.strip()):
        lead.phone = (
            message_text.strip()
            .replace("-", "")
            .replace(" ", "")
            .replace("(", "")
            .replace(")", "")
        )


def _respond_for_profile_flow(
    lead,
    conversation_service: ConversationService,
    sender_id: str,
    lang: str,
    responses: List[str],
) -> None:
    next_status, prompt_en, prompt_sv = _next_profile_prompt(lead)
    if next_status != "complete":
        lead.conversation_state = "gathering_profile"
        _set_profile_status(lead, next_status)
        _append_bot_message(
            responses,
            conversation_service,
            lead,
            sender_id,
            lang,
            prompt_en,
            prompt_sv,
            commit=False,
        )
        return
    lead.conversation_state = "recommending_booking"
    lead.notes = "waiting_for_calendar_booking"
    book_en, book_sv = _recommend_booking_both(lead)
    _append_bot_message(
        responses,
        conversation_service,
        lead,
        sender_id,
        lang,
        book_en,
        book_sv,
        commit=False,
    )

@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    session_id = request.session_id or uuid.uuid4().hex
    sender_id = session_id
    requested_lang = _normalize_lang(request.language)
    message_text = (request.message or "").strip()
    responses: List[str] = []

    import time as _time
    _ep_start = _time.perf_counter()
    print("chat endpoint started")
    _t_lead = _time.perf_counter()
    lead_service = LeadService(db)
    conversation_service = ConversationService(db)
    lead = lead_service.get_lead_by_messenger_id(sender_id)
    print(f"lead/service setup + get_lead_by_messenger_id took {(_time.perf_counter()-_t_lead)*1000:.1f}ms")

    if not message_text and not lead:
        print(f"chat endpoint total took {(_time.perf_counter()-_ep_start)*1000:.1f}ms")
        return ChatResponse(session_id=session_id, messages=_initial_messages(requested_lang), language=requested_lang)

    if not lead:
        lead = _create_web_lead(lead_service, sender_id, requested_lang)
        _persist_initial_messages(lead, conversation_service, sender_id)
    elif lead.language != requested_lang:
        lead.language = requested_lang

    lang = _lang(lead)

    if not message_text:
        conversations = _load_web_conversations(db, lead.id)
        if conversations:
            if _should_send_booking_follow_up(lead, conversations):
                follow_up_en, follow_up_sv = _follow_up_booking_both(lead)
                follow_up = _save_outbound_message(
                    conversation_service,
                    lead.id,
                    sender_id,
                    follow_up_en,
                    follow_up_sv,
                    commit=False,
                )
                lead.conversation_state = "recommending_booking"
                lead.notes = "waiting_for_calendar_booking"
                db.commit()
                conversations.append(follow_up)
            elif db.is_modified(lead):
                db.commit()
            return ChatResponse(
                session_id=session_id,
                messages=[],
                history=_history_from_conversations(conversations),
                language=lead.language or "en",
            )

        responses.extend(_initial_messages(lang))
        db.commit()
        print(f"chat endpoint total took {(_time.perf_counter()-_ep_start)*1000:.1f}ms")
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    user_en, user_sv = _prepare_inbound_texts(lead, message_text)
    _t_save = _time.perf_counter()
    conversation_service.save_message(
        lead_id=lead.id,
        channel=ConversationChannel.WEB,
        direction=MessageDirection.INBOUND,
        message_text_en=user_en,
        message_text_sv=user_sv,
        messenger_id=sender_id,
        commit=False,
        flush=False,
        refresh=False,
    )
    lead.message_count += 1
    lead.last_contact = datetime.utcnow()
    print(f"save inbound message took {(_time.perf_counter()-_t_save)*1000:.1f}ms")

    # QR-code machine entry: respond with machine description + video
    machine_entry = bool(request.machine_entry)
    machine = _get_machine_from_message(message_text)
    if machine:
        response_text = machine["description_sv"] if lang == "sv" else machine["description_en"]
        responses.append(response_text)
        _save_outbound_message(
            conversation_service,
            lead.id,
            sender_id,
            machine["description_en"],
            machine["description_sv"],
            intent="machine_info",
            ai_response=response_text,
            commit=False,
        )
        lead.message_count += 1
        db.commit()
        return ChatResponse(
            session_id=session_id,
            messages=responses,
            language=lead.language or "en",
            faq_video_url=machine["video_url"],
        )

    status = _profile_status(lead)
    current_state = lead.conversation_state or "welcome"

    if status:
        _update_profile_from_message(lead, message_text)
        _respond_for_profile_flow(lead, conversation_service, sender_id, lang, responses)
        db.commit()
        print(f"chat endpoint total took {(_time.perf_counter()-_ep_start)*1000:.1f}ms")
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    if current_state in {"welcome", "gathering_profile"}:
        _respond_for_profile_flow(lead, conversation_service, sender_id, lang, responses)
        db.commit()
        print(f"chat endpoint total took {(_time.perf_counter()-_ep_start)*1000:.1f}ms")
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    if lead.notes == "waiting_for_calendar_booking" and _is_calendar_confirmation(message_text):
        confirm_en = t("en", "booking_confirm_calendar")
        confirm_sv = t("sv", "booking_confirm_calendar")
        _append_bot_message(
            responses,
            conversation_service,
            lead,
            sender_id,
            lang,
            confirm_en,
            confirm_sv,
            commit=False,
        )
        lead.notes = "calendar_booking_pending_verification"
        db.commit()
        print(f"chat endpoint total took {(_time.perf_counter()-_ep_start)*1000:.1f}ms")
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    _t0 = _time.perf_counter()
    analysis = await chat_handler.analyze_message(
        user_message=message_text,
        conversation_state=current_state,
        language=lang,
    )
    print(f"chat.py analyze_message took {(_time.perf_counter()-_t0)*1000:.1f}ms")
    if analysis.fast_path_response:
        ai_response = analysis.fast_path_response
        print("chat.py fast_path used — skipping LLM call")
    else:
        _th = _time.perf_counter()
        conversation_history = conversation_service.get_conversation_history_for_ai(
            lead_id=lead.id,
            messenger_id=sender_id,
            lang=lang,
        )
        print(f"get_conversation_history_for_ai took {(_time.perf_counter()-_th)*1000:.1f}ms")
        _tai = _time.perf_counter()
        ai_response = await chat_handler.process_message(
            user_message=message_text,
            conversation_history=conversation_history,
            customer_info={"name": lead.name, "phone": lead.phone},
            conversation_state=current_state,
            language=lang,
            analysis=analysis,
        )
        print(f"chat_handler.process_message took {(_time.perf_counter()-_tai)*1000:.1f}ms")

    if ai_response.get("should_proceed") and ai_response.get("intent") == "book":
        resp_en = t("en", "book_link_once", link=_get_calendar_link())
        resp_sv = t("sv", "book_link_once", link=_get_calendar_link())
        lead.notes = "waiting_for_calendar_booking"
        lead.conversation_state = "recommending_booking"
        _append_bot_message(
            responses,
            conversation_service,
            lead,
            sender_id,
            lang,
            resp_en,
            resp_sv,
            background_tasks,
            intent=ai_response.get("intent"),
            faq_used=ai_response.get("faq_used"),
            commit=False,
        )
        db.commit()
        print(f"chat endpoint total took {(_time.perf_counter()-_ep_start)*1000:.1f}ms")
        return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en")

    resp_en = ai_response.get("response_en") or ai_response.get("response", "")
    resp_sv = ai_response.get("response_sv")
    resp_en, resp_sv = _sanitize_bilingual_output(resp_en, resp_sv)

    next_state = ai_response.get("next_state")
    if next_state and next_state != current_state:
        lead.conversation_state = next_state

    _append_bot_message(
        responses,
        conversation_service,
        lead,
        sender_id,
        lang,
        resp_en,
        resp_sv,
        background_tasks,
        intent=ai_response.get("intent"),
        faq_used=ai_response.get("faq_used"),
        commit=False,
    )
    db.commit()

    faq_video = ai_response.get("faq_video_url") if isinstance(locals().get("ai_response"), dict) else None
    print(f"chat endpoint total took {(_time.perf_counter()-_ep_start)*1000:.1f}ms")
    return ChatResponse(session_id=session_id, messages=responses, language=lead.language or "en", faq_video_url=faq_video)