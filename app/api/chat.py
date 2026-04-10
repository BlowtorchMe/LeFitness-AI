"""
Web chat API with profile gathering, gym selection, FAQ handling, and booking flow.
"""
import base64
import re
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.chat_handler import ChatHandler
from app.ai.translations import get as t
from app.database.database import SessionLocal, get_db
from app.models.conversation import Conversation, ConversationChannel, MessageDirection
from app.models.gym import Gym
from app.services.conversation_service import ConversationService
from app.services.lead_service import LeadService

router = APIRouter()
chat_handler = ChatHandler()

PROFILE_STATUS_PREFIX = "profile_status:"
GYM_SELECTION_PREFIX = "gym_selection:"
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
PHONE_PATTERNS = (
    r"\bphone\b",
    r"\bnumber\b",
    r"\bcall\b",
    r"\bcontact\b",
)
LOCATION_PATTERNS = (
    r"\baddress\b",
    r"\blocation\b",
    r"\bwhere\b.*\bare\b",
    r"\bwhere\b.*\blocated\b",
    r"\bfind\b.*\byou\b",
)
BOOKING_PATTERNS = (
    r"\bbook\b",
    r"\bbooking\b",
    r"\bappointment\b",
    r"\bschedule\b",
    r"\bvisit\b",
    r"\btrial\b",
)
GYM_SPECIFIC_PATTERNS = (
    r"\bmachines?\b",
    r"\bequipment\b",
    r"\bclasses?\b",
    r"\bparking\b",
    r"\bhours?\b",
    r"\bstaffed\b",
    r"\bsauna\b",
    *PHONE_PATTERNS,
    *LOCATION_PATTERNS,
    *BOOKING_PATTERNS,
)


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: Optional[str] = None
    language: Optional[str] = None
    action: Optional[str] = None
    action_value: Optional[str] = None
    action_label: Optional[str] = None


class ChatMessageHistory(BaseModel):
    role: str
    text: Optional[str] = None
    text_en: Optional[str] = None
    text_sv: Optional[str] = None


class ChatOption(BaseModel):
    id: str
    label: str
    action: str


class ChatSelectedGym(BaseModel):
    id: int
    name: str


class ChatResponse(BaseModel):
    session_id: str
    messages: List[str]
    history: Optional[List[ChatMessageHistory]] = None
    language: Optional[str] = None
    options: Optional[List[ChatOption]] = None
    input_disabled: bool = False
    selected_gym: Optional[ChatSelectedGym] = None


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


def _serialize_selected_gym(gym: Optional[Gym]) -> Optional[ChatSelectedGym]:
    if not gym:
        return None
    return ChatSelectedGym(id=gym.id, name=gym.name)


def _get_active_gyms(db: Session) -> List[Gym]:
    return db.query(Gym).filter(Gym.is_active.is_(True)).order_by(Gym.name.asc()).all()


def _get_gym_by_id(db: Session, gym_id: Optional[int]) -> Optional[Gym]:
    if not gym_id:
        return None
    return db.query(Gym).filter(Gym.id == gym_id).first()


def _auto_select_single_gym(lead, gyms: List[Gym]) -> Optional[Gym]:
    if lead.selected_gym_id:
        for gym in gyms:
            if gym.id == lead.selected_gym_id:
                return gym
    if len(gyms) == 1:
        lead.selected_gym_id = gyms[0].id
        return gyms[0]
    return None


def _booking_link_for_gym(gym: Gym) -> str:
    return gym.booking_url


def _recommend_booking_both(lead, gym: Optional[Gym]) -> tuple[str, str]:
    name = lead.name or "Customer"
    link = _booking_link_for_gym(gym) if gym else ""
    gym_name = gym.name if gym else None
    return (
        t("en", "booking_intro", name=name, link=link, gym_name=gym_name),
        t("sv", "booking_intro", name=name, link=link, gym_name=gym_name),
    )


def _follow_up_booking_both(lead, gym: Optional[Gym]) -> tuple[str, str]:
    name = lead.name or "Customer"
    link = _booking_link_for_gym(gym) if gym else ""
    gym_name = gym.name if gym else None
    return (
        t("en", "booking_follow_up", name=name, link=link, gym_name=gym_name),
        t("sv", "booking_follow_up", name=name, link=link, gym_name=gym_name),
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


def _gym_selection_state(lead) -> tuple[Optional[str], Optional[str]]:
    notes = getattr(lead, "notes", None) or ""
    if not notes.startswith(GYM_SELECTION_PREFIX):
        return None, None
    payload = notes[len(GYM_SELECTION_PREFIX) :]
    parts = payload.split(":", 1)
    reason = parts[0] if parts else None
    pending_question = None
    if len(parts) > 1 and parts[1]:
        try:
            pending_question = base64.urlsafe_b64decode(parts[1].encode("utf-8")).decode("utf-8")
        except Exception:
            pending_question = None
    return reason, pending_question


def _set_gym_selection_state(lead, reason: str, pending_question: Optional[str] = None) -> None:
    if pending_question:
        encoded = base64.urlsafe_b64encode(pending_question.encode("utf-8")).decode("utf-8")
        lead.notes = f"{GYM_SELECTION_PREFIX}{reason}:{encoded}"
    else:
        lead.notes = f"{GYM_SELECTION_PREFIX}{reason}"
    lead.conversation_state = "selecting_gym"


def _clear_gym_selection_state(lead) -> None:
    if getattr(lead, "notes", None) and lead.notes.startswith(GYM_SELECTION_PREFIX):
        lead.notes = None


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
    if lead.conversation_state not in {"profile_complete", "recommending_booking", "answering_questions", "selecting_gym"}:
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


def _save_inbound_message(
    conversation_service: ConversationService,
    lead,
    sender_id: str,
    text: str,
) -> None:
    lang = _lang(lead)
    if _profile_status(lead) or lead.conversation_state == "selecting_gym":
        user_en = text
        user_sv = text
    elif lang == "sv":
        user_en = None
        user_sv = text
    else:
        user_en = text
        user_sv = None
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


def _build_gym_options(gyms: List[Gym]) -> List[ChatOption]:
    return [ChatOption(id=str(gym.id), label=gym.name, action="select_gym") for gym in gyms]


def _gym_prompt_texts(lang: str, reason: str) -> tuple[str, str]:
    if reason == "booking":
        return (
            t("en", "select_gym_booking"),
            t("sv", "select_gym_booking"),
        )
    return (
        t("en", "select_gym_question"),
        t("sv", "select_gym_question"),
    )


def _append_gym_selection_prompt(
    responses: List[str],
    conversation_service: ConversationService,
    lead,
    sender_id: str,
    lang: str,
    reason: str,
) -> List[ChatOption]:
    prompt_en, prompt_sv = _gym_prompt_texts(lang, reason)
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
    return _build_gym_options(_get_active_gyms(conversation_service.db))


def _needs_booking_gym_selection(lead, current_state: str, gyms: List[Gym], current_gym: Optional[Gym]) -> bool:
    if current_gym or len(gyms) <= 1:
        return False
    if _profile_status(lead):
        return False
    return current_state in {"profile_complete", "recommending_booking"}


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
        lead.conversation_state = "profile_complete"
        lead.notes = None
        return
    lead.conversation_state = "gathering_profile"
    _set_profile_status(lead, next_status)
    _save_outbound_message(conversation_service, lead.id, sender_id, prompt_en, prompt_sv, commit=False)


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


def _find_gym_choice(gyms: List[Gym], action_value: Optional[str], action_label: Optional[str], message_text: str) -> Optional[Gym]:
    candidate = (action_value or "").strip()
    if candidate.isdigit():
        gym_id = int(candidate)
        for gym in gyms:
            if gym.id == gym_id:
                return gym
    normalized = (action_label or message_text or "").strip().lower()
    for gym in gyms:
        if normalized in {gym.name.lower(), gym.slug.lower()}:
            return gym
    return None


def _is_location_specific_question(message_text: str, intent: Optional[str]) -> bool:
    normalized = " ".join((message_text or "").strip().lower().split())
    if not normalized:
        return False
    if intent == "book":
        return True
    return any(re.search(pattern, normalized) for pattern in GYM_SPECIFIC_PATTERNS)


def _gym_reference_response(gym: Gym, message_text: str) -> Optional[tuple[str, str]]:
    normalized = " ".join((message_text or "").strip().lower().split())
    if any(re.search(pattern, normalized) for pattern in PHONE_PATTERNS):
        return (
            t("en", "gym_phone", gym_name=gym.name, phone=gym.phone or t("en", "gym_phone_missing")),
            t("sv", "gym_phone", gym_name=gym.name, phone=gym.phone or t("sv", "gym_phone_missing")),
        )
    if any(re.search(pattern, normalized) for pattern in LOCATION_PATTERNS):
        return (
            t("en", "gym_location", gym_name=gym.name, location=gym.location),
            t("sv", "gym_location", gym_name=gym.name, location=gym.location),
        )
    if any(re.search(pattern, normalized) for pattern in BOOKING_PATTERNS):
        link = _booking_link_for_gym(gym)
        return (
            t("en", "book_link_once", link=link),
            t("sv", "book_link_once", link=link),
        )
    return None


def _respond_for_profile_flow(
    lead,
    conversation_service: ConversationService,
    sender_id: str,
    lang: str,
    responses: List[str],
    gyms: List[Gym],
) -> List[ChatOption]:
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
        return []
    lead.conversation_state = "profile_complete"
    if not lead.selected_gym_id and len(gyms) > 1:
        _set_gym_selection_state(lead, "booking")
        return _append_gym_selection_prompt(
            responses,
            conversation_service,
            lead,
            sender_id,
            lang,
            "booking",
        )
    current_gym = _auto_select_single_gym(lead, gyms)
    lead.conversation_state = "recommending_booking"
    lead.notes = "waiting_for_calendar_booking"
    book_en, book_sv = _recommend_booking_both(lead, current_gym)
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
    return []


def _response_from_state(
    session_id: str,
    messages: List[str],
    lead,
    current_gym: Optional[Gym],
    *,
    history: Optional[List[ChatMessageHistory]] = None,
    options: Optional[List[ChatOption]] = None,
) -> ChatResponse:
    input_disabled = bool(options)
    return ChatResponse(
        session_id=session_id,
        messages=messages,
        history=history,
        language=lead.language or "en",
        options=options or None,
        input_disabled=input_disabled,
        selected_gym=_serialize_selected_gym(current_gym),
    )


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    session_id = request.session_id or uuid.uuid4().hex
    sender_id = session_id
    requested_lang = _normalize_lang(request.language)
    message_text = (request.message or "").strip()
    action = (request.action or "").strip()
    action_value = (request.action_value or "").strip()
    action_label = (request.action_label or "").strip()
    responses: List[str] = []
    options: List[ChatOption] = []

    lead_service = LeadService(db)
    conversation_service = ConversationService(db)
    lead = lead_service.get_lead_by_messenger_id(sender_id)
    active_gyms = _get_active_gyms(db)
    print("ACTIVE GYMS:", [(gym.id, gym.name, gym.slug, gym.is_active, gym.booking_url) for gym in active_gyms])
    print("=== CHAT ENDPOINT HIT ===")
    print("ACTIVE GYMS:", [(gym.id, gym.name, gym.slug, gym.is_active, gym.booking_url) for gym in active_gyms])
    print("CURRENT STATE:", lead.conversation_state if lead else None)
    print("SELECTED GYM ID:", lead.selected_gym_id if lead else None)
    if not message_text and not action and not lead:
        return ChatResponse(session_id=session_id, messages=_initial_messages(requested_lang), language=requested_lang)

    if not lead:
        lead = _create_web_lead(lead_service, sender_id, requested_lang)
        _persist_initial_messages(lead, conversation_service, sender_id)
    elif lead.language != requested_lang:
        lead.language = requested_lang

    current_gym = _auto_select_single_gym(lead, active_gyms) or _get_gym_by_id(db, lead.selected_gym_id)
    lang = _lang(lead)

    if not message_text and not action:
        conversations = _load_web_conversations(db, lead.id)
        if conversations:
            current_state = lead.conversation_state or "welcome"
            if _needs_booking_gym_selection(lead, current_state, active_gyms, current_gym):
                _set_gym_selection_state(lead, "booking")
                prompt_en, prompt_sv = _gym_prompt_texts(lang, "booking")
                follow_up = _save_outbound_message(
                    conversation_service,
                    lead.id,
                    sender_id,
                    prompt_en,
                    prompt_sv,
                    commit=False,
                )
                options = _build_gym_options(active_gyms)
                db.commit()
                conversations.append(follow_up)
                return _response_from_state(
                    session_id,
                    [],
                    lead,
                    current_gym,
                    history=_history_from_conversations(conversations),
                    options=options,
                )
            if lead.conversation_state == "selecting_gym" and not current_gym:
                options = _build_gym_options(active_gyms)
                return _response_from_state(
                    session_id,
                    [],
                    lead,
                    current_gym,
                    history=_history_from_conversations(conversations),
                    options=options,
                )
            if _should_send_booking_follow_up(lead, conversations):
                if not current_gym and len(active_gyms) > 1:
                    _set_gym_selection_state(lead, "booking")
                    prompt_en, prompt_sv = _gym_prompt_texts(lang, "booking")
                    follow_up = _save_outbound_message(
                        conversation_service,
                        lead.id,
                        sender_id,
                        prompt_en,
                        prompt_sv,
                        commit=False,
                    )
                    options = _build_gym_options(active_gyms)
                    db.commit()
                    conversations.append(follow_up)
                else:
                    follow_up_en, follow_up_sv = _follow_up_booking_both(lead, current_gym)
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
            return _response_from_state(
                session_id,
                [],
                lead,
                current_gym,
                history=_history_from_conversations(conversations),
                options=options,
            )

        responses.extend(_initial_messages(lang))
        db.commit()
        return _response_from_state(session_id, responses, lead, current_gym)

    current_state = lead.conversation_state or "welcome"
    pending_reason, pending_question = _gym_selection_state(lead)

    if _needs_booking_gym_selection(lead, current_state, active_gyms, current_gym):
        _set_gym_selection_state(lead, "booking")
        options = _append_gym_selection_prompt(
            responses,
            conversation_service,
            lead,
            sender_id,
            lang,
            "booking",
        )
        print("GYM OPTIONS:", options)
        db.commit()
        return _response_from_state(session_id, responses, lead, current_gym, options=options)

    if current_state == "selecting_gym":
        selected_gym = _find_gym_choice(active_gyms, action_value, action_label, message_text)
        if not selected_gym:
            prompt_en, prompt_sv = _gym_prompt_texts(lang, pending_reason or "question")
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
            db.commit()
            return _response_from_state(
                session_id,
                responses,
                lead,
                current_gym,
                options=_build_gym_options(active_gyms),
            )

        lead.selected_gym_id = selected_gym.id
        current_gym = selected_gym
        _clear_gym_selection_state(lead)
        selection_text = action_label or selected_gym.name
        _save_inbound_message(conversation_service, lead, sender_id, selection_text)

        if pending_reason == "booking":
            lead.conversation_state = "recommending_booking"
            lead.notes = "waiting_for_calendar_booking"
            book_en, book_sv = _recommend_booking_both(lead, current_gym)
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
            db.commit()
            return _response_from_state(session_id, responses, lead, current_gym)

        if pending_question:
            reference_response = _gym_reference_response(current_gym, pending_question)
            if reference_response:
                resp_en, resp_sv = reference_response
                lead.conversation_state = "answering_questions"
                _append_bot_message(
                    responses,
                    conversation_service,
                    lead,
                    sender_id,
                    lang,
                    resp_en,
                    resp_sv,
                    commit=False,
                    intent="gym_reference",
                )
                db.commit()
                return _response_from_state(session_id, responses, lead, current_gym)

            analysis = await chat_handler.analyze_message(
                user_message=pending_question,
                conversation_state="answering_questions",
                language=lang,
                selected_gym_id=current_gym.id,
            )
            if analysis.fast_path_response:
                ai_response = analysis.fast_path_response
            else:
                ai_response = await chat_handler.process_message(
                    user_message=pending_question,
                    conversation_history=conversation_service.get_conversation_history_for_ai(
                        lead_id=lead.id,
                        messenger_id=sender_id,
                        lang=lang,
                    ),
                    customer_info={
                        "name": lead.name,
                        "phone": lead.phone,
                        "selected_gym": current_gym.name,
                        "gym_location": current_gym.location,
                        "gym_phone": current_gym.phone,
                    },
                    conversation_state="answering_questions",
                    language=lang,
                    selected_gym_id=current_gym.id,
                    analysis=analysis,
                )
            resp_en = ai_response.get("response_en") or ai_response.get("response", "")
            resp_sv = ai_response.get("response_sv")
            lead.conversation_state = ai_response.get("next_state") or "answering_questions"
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
            return _response_from_state(session_id, responses, lead, current_gym)

        lead.conversation_state = "answering_questions"
        db.commit()
        return _response_from_state(session_id, responses, lead, current_gym)

    inbound_text = action_label or message_text
    if inbound_text:
        _save_inbound_message(conversation_service, lead, sender_id, inbound_text)

    status = _profile_status(lead)
    if status:
        _update_profile_from_message(lead, message_text or inbound_text)
        options = _respond_for_profile_flow(lead, conversation_service, sender_id, lang, responses, active_gyms)
        current_gym = _get_gym_by_id(db, lead.selected_gym_id)
        db.commit()
        return _response_from_state(session_id, responses, lead, current_gym, options=options)

    if current_state in {"welcome", "gathering_profile"}:
        options = _respond_for_profile_flow(lead, conversation_service, sender_id, lang, responses, active_gyms)
        current_gym = _get_gym_by_id(db, lead.selected_gym_id)
        db.commit()
        return _response_from_state(session_id, responses, lead, current_gym, options=options)

    if lead.notes == "waiting_for_calendar_booking" and _is_calendar_confirmation(message_text or inbound_text):
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
        return _response_from_state(session_id, responses, lead, current_gym)

    analysis = await chat_handler.analyze_message(
        user_message=message_text or inbound_text,
        conversation_state=current_state,
        language=lang,
        selected_gym_id=current_gym.id if current_gym else None,
    )

    if not current_gym and len(active_gyms) > 1 and _is_location_specific_question(message_text or inbound_text, analysis.intent):
        _set_gym_selection_state(
            lead,
            "booking" if analysis.intent == "book" else "question",
            pending_question=(message_text or inbound_text) if analysis.intent != "book" else None,
        )
        options = _append_gym_selection_prompt(
            responses,
            conversation_service,
            lead,
            sender_id,
            lang,
            "booking" if analysis.intent == "book" else "question",
        )
        db.commit()
        return _response_from_state(session_id, responses, lead, current_gym, options=options)

    if current_gym:
        reference_response = _gym_reference_response(current_gym, message_text or inbound_text)
        if reference_response:
            resp_en, resp_sv = reference_response
            if analysis.intent == "book":
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
                commit=False,
                intent="gym_reference",
            )
            db.commit()
            return _response_from_state(session_id, responses, lead, current_gym)

    if analysis.fast_path_response:
        ai_response = analysis.fast_path_response
    else:
        ai_response = await chat_handler.process_message(
            user_message=message_text or inbound_text,
            conversation_history=conversation_service.get_conversation_history_for_ai(
                lead_id=lead.id,
                messenger_id=sender_id,
                lang=lang,
            ),
            customer_info={
                "name": lead.name,
                "phone": lead.phone,
                "selected_gym": current_gym.name if current_gym else None,
                "gym_location": current_gym.location if current_gym else None,
                "gym_phone": current_gym.phone if current_gym else None,
            },
            conversation_state=current_state,
            language=lang,
            selected_gym_id=current_gym.id if current_gym else None,
            analysis=analysis,
        )

    if ai_response.get("should_proceed") and ai_response.get("intent") == "book":
        if not current_gym and len(active_gyms) > 1:
            _set_gym_selection_state(lead, "booking")
            options = _append_gym_selection_prompt(
                responses,
                conversation_service,
                lead,
                sender_id,
                lang,
                "booking",
            )
            db.commit()
            return _response_from_state(session_id, responses, lead, current_gym, options=options)

        current_gym = current_gym or _auto_select_single_gym(lead, active_gyms)
        if not current_gym:
            options = _append_gym_selection_prompt(
                responses,
                conversation_service,
                lead,
                sender_id,
                lang,
                "booking",
            )
            _set_gym_selection_state(lead, "booking")
            db.commit()
            return _response_from_state(session_id, responses, lead, current_gym, options=options)
        resp_en = t("en", "book_link_once", link=_booking_link_for_gym(current_gym))
        resp_sv = t("sv", "book_link_once", link=_booking_link_for_gym(current_gym))
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
        return _response_from_state(session_id, responses, lead, current_gym)

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

    return _response_from_state(session_id, responses, lead, current_gym)
