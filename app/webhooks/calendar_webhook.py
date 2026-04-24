"""
Google Calendar webhook handler.
Receives push notifications when calendar events are created or updated.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request
from sqlalchemy.exc import IntegrityError

from app.database.database import SessionLocal
from app.integrations.google_calendar import GoogleCalendar
from app.models.booking import Booking, AppointmentType, BookingStatus
from app.models.conversation import ConversationChannel, MessageDirection
from app.models.gym import Gym
from app.models.lead import LeadStatus
from app.services.conversation_service import ConversationService
from app.services.lead_service import LeadService

router = APIRouter()
logger = logging.getLogger(__name__)

# Per-gym debounce: skip processing if same gym was processed within this window
_DEBOUNCE_SECONDS = 30
_last_processed: dict[str, datetime] = {}


def _get_calendar_for_gym(gym_slug: str, db) -> Optional[GoogleCalendar]:
    gym = db.query(Gym).filter(Gym.slug == gym_slug, Gym.is_active.is_(True)).first()
    if not gym or not gym.calendar_id:
        return None
    try:
        cal = GoogleCalendar(calendar_id=gym.calendar_id)
        if not cal.service:
            return None
        return cal
    except Exception as e:
        logger.warning("Could not create calendar for gym '%s': %s", gym_slug, e)
        return None


def _format_event_dt(event_dt: datetime, lang: str) -> str:
    day = str(event_dt.day)
    if lang == "sv":
        return f"{day} {event_dt.strftime('%B')} kl {event_dt.strftime('%H:%M')}"
    hour = event_dt.strftime("%I").lstrip("0") or "12"
    return f"{event_dt.strftime('%B')} {day} at {hour}{event_dt.strftime(':%M %p')}"


def _save_confirmation_message(db, lead, event_dt: datetime) -> None:
    from app.ai.translations import get as t
    lang = lead.language or "en"
    dt_en = _format_event_dt(event_dt, "en")
    dt_sv = _format_event_dt(event_dt, "sv")
    confirm_en = t("en", "booking_confirmed_webhook", dt=dt_en)
    confirm_sv = t("sv", "booking_confirmed_webhook", dt=dt_sv)
    conv_service = ConversationService(db)
    conv_service.save_message(
        lead_id=lead.id,
        channel=ConversationChannel.WEB,
        direction=MessageDirection.OUTBOUND,
        message_text_en=confirm_en,
        message_text_sv=confirm_sv,
        messenger_id=lead.messenger_id,
        commit=False,
        flush=False,
        refresh=False,
    )


@router.post("")
async def handle_calendar_webhook(request: Request, background_tasks: BackgroundTasks):
    headers = dict(request.headers)
    resource_state = headers.get("x-goog-resource-state") or headers.get("X-Goog-Resource-State")
    gym_slug = headers.get("x-goog-channel-token") or headers.get("X-Goog-Channel-Token")
    logger.debug("Calendar webhook received: resource_state=%s gym=%s", resource_state, gym_slug)

    if resource_state == "sync":
        return {"status": "ok"}

    if resource_state in ["exists", "not_exists"]:
        key = gym_slug or "__all__"
        now = datetime.utcnow()
        last = _last_processed.get(key)
        if last and (now - last).total_seconds() < _DEBOUNCE_SECONDS:
            logger.debug("Calendar webhook debounced for gym=%s", gym_slug)
            return {"status": "ok"}
        _last_processed[key] = now
        background_tasks.add_task(_run_process_calendar_changes, gym_slug)

    return {"status": "ok"}

def _select_customer_attendee(event: dict, gym: Gym):
    attendees = event.get("attendees", []) or []
    organizer_email = ((event.get("organizer") or {}).get("email") or "").strip().lower()
    creator_email = ((event.get("creator") or {}).get("email") or "").strip().lower()
    calendar_email = (gym.calendar_id or "").strip().lower()

    blocked_emails = {email for email in [organizer_email, creator_email, calendar_email] if email}

    candidates = []
    for attendee in attendees:
        email = (attendee.get("email") or "").strip().lower()
        if not email:
            continue
        if attendee.get("self"):
            continue
        if attendee.get("organizer"):
            continue
        if email in blocked_emails:
            continue
        candidates.append(attendee)

    if candidates:
        return candidates[0]

    for attendee in attendees:
        email = (attendee.get("email") or "").strip().lower()
        if email and email not in blocked_emails:
            return attendee

    return attendees[0] if attendees else None

def _run_process_calendar_changes(gym_slug: Optional[str]) -> None:
    """Sync wrapper so FastAPI BackgroundTasks can call the async function."""
    asyncio.run(process_calendar_changes(gym_slug=gym_slug))


async def process_calendar_changes(gym_slug: Optional[str] = None):
    """
    Fetch new events from calendar(s) and save them as bookings.
    If gym_slug is provided (from X-Goog-Channel-Token), only that gym is checked.
    Falls back to scanning all active gyms with a calendar_id when gym_slug is absent.
    When a lead is matched, saves a confirmation message to their conversation history.
    """
    db = SessionLocal()
    try:
        lead_service = LeadService(db)
        start_time = datetime.utcnow() - timedelta(hours=24)
        end_time = datetime.utcnow() + timedelta(days=90)
        total_new = 0
        total_matched = 0
        matched_session_ids: list[str] = []

        if gym_slug:
            slugs_to_check = [gym_slug]
        else:
            slugs_to_check = [
                g.slug
                for g in db.query(Gym).filter(Gym.is_active.is_(True), Gym.calendar_id.isnot(None)).all()
                if g.calendar_id
            ]

        for gym_slug in slugs_to_check:
            gym = db.query(Gym).filter(Gym.slug == gym_slug, Gym.is_active.is_(True)).first()
            if not gym or not gym.calendar_id:
                logger.info("Skipping gym '%s' — not found or no calendar_id", gym_slug)
                continue

            calendar = _get_calendar_for_gym(gym_slug, db)
            if not calendar:
                logger.info("Skipping gym '%s' — calendar not configured", gym_slug)
                continue

            events = calendar.get_recent_events(start_time=start_time, end_time=end_time)
            logger.debug("Gym '%s': %d events fetched", gym_slug, len(events))

            for event in events:
                event_id = event.get("id")
                if not event_id:
                    continue

                if db.query(Booking).filter(Booking.external_booking_id == event_id).first():
                    continue

                event_start = event.get("start", {}).get("dateTime")
                if not event_start:
                    continue
                try:
                    event_dt = datetime.fromisoformat(event_start.replace("Z", "+00:00"))
                except Exception:
                    continue

                event_end = event.get("end", {}).get("dateTime")
                duration_minutes = 60
                if event_end:
                    try:
                        end_dt = datetime.fromisoformat(event_end.replace("Z", "+00:00"))
                        duration_minutes = int((end_dt - event_dt).total_seconds() / 60)
                    except Exception:
                        pass

                # Identify customer attendee — skip organizer and self (gym calendar owner)
                attendees = event.get("attendees", [])
                customer_attendee = _select_customer_attendee(event, gym)

                attendee_email = customer_attendee.get("email") if customer_attendee else None
                attendee_name = customer_attendee.get("displayName") if customer_attendee else None
                event_summary = event.get("summary", "")
                customer_name = (
                    attendee_name
                    or (event_summary.split("-")[-1].strip() if "-" in event_summary else event_summary)
                    or "Customer"
                )

                logger.info(
                    "Event '%s': customer_email=%s organizer=%s creator=%s attendees=%s",
                    event_id[:12],
                    attendee_email,
                    (event.get("organizer") or {}).get("email"),
                    (event.get("creator") or {}).get("email"),
                    [a.get("email") for a in attendees],
                )

                # Match lead by email
                lead = None
                if attendee_email:
                    lead = lead_service.get_lead_by_email(attendee_email)
                    if lead:
                        logger.info("Matched lead id=%d by email for event %s", lead.id, event_id)
                    else:
                        logger.info("No lead found for email %s", attendee_email)

                booking = Booking(
                    lead_id=lead.id if lead else None,
                    gym_id=gym.id,
                    customer_name=customer_name,
                    phone=lead.phone if lead else None,
                    email=attendee_email,
                    appointment_time=event_dt,
                    appointment_type=AppointmentType.TRIAL_ACTIVATION,
                    duration_minutes=duration_minutes,
                    status=BookingStatus.CONFIRMED,
                    external_booking_id=event_id,
                    calendar_link=event.get("htmlLink"),
                )

                try:
                    with db.begin_nested():
                        db.add(booking)
                        db.flush()
                except IntegrityError:
                    logger.info("Duplicate event %s skipped (concurrent insert)", event_id)
                    continue

                total_new += 1

                if lead:
                    total_matched += 1
                    lead.status = LeadStatus.BOOKED
                    lead.booking_id = booking.id
                    lead.booking_date = event_dt
                    lead.notes = f"calendar_booking_saved:{event_id}"
                    lead.conversation_state = "booking_confirmed"
                    _save_confirmation_message(db, lead, event_dt)
                    if lead.messenger_id:
                        matched_session_ids.append(lead.messenger_id)

        db.commit()
        if total_new or total_matched:
            logger.info("Calendar sync done: %d new bookings, %d leads matched", total_new, total_matched)
        else:
            logger.debug("Calendar sync done: no new bookings")

        # Push SSE after commit so the confirmation message is visible when frontend fetches
        if matched_session_ids:
            from app.sse_manager import sse_manager
            for sid in matched_session_ids:
                sse_manager.push(sid, {"type": "booking_confirmed", "data": ""})

    except Exception:
        logger.exception("Calendar webhook processing failed")
        db.rollback()
    finally:
        db.close()
