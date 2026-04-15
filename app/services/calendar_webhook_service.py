"""
Service for managing Google Calendar webhook setup and renewal.
"""
import logging
from typing import Dict, List, Optional

from app.config import settings
from app.database.database import SessionLocal
from app.integrations.google_calendar import GoogleCalendar
from app.models.gym import Gym

logger = logging.getLogger(__name__)


def _get_active_gym_slugs_with_calendar() -> List[Dict[str, str]]:
    """Return list of {slug, calendar_id} for active gyms that have a calendar_id set."""
    db = SessionLocal()
    try:
        gyms = (
            db.query(Gym)
            .filter(Gym.is_active.is_(True), Gym.calendar_id.isnot(None))
            .all()
        )
        return [{"slug": g.slug, "calendar_id": g.calendar_id} for g in gyms if g.calendar_id]
    finally:
        db.close()


class CalendarWebhookService:
    """Manages Google Calendar webhook lifecycle for all gyms"""

    def __init__(self):
        self.active_watches: Dict[str, Dict[str, str]] = {}

    def setup_webhook(self) -> Dict:
        if not settings.google_service_account:
            logger.warning("Google service account not configured - skipping webhook setup")
            return {"success": False, "error": "Google service account not configured"}

        if not settings.google_calendar_webhook_url:
            logger.warning("GOOGLE_CALENDAR_WEBHOOK_URL not set - skipping webhook setup")
            return {"success": False, "error": "Webhook URL not configured"}

        gyms = _get_active_gym_slugs_with_calendar()
        if not gyms:
            logger.info("No active gyms with calendar_id configured — skipping webhook setup")
            return {"success": False, "error": "No gyms with calendar configured"}

        results = {}
        any_success = False

        for gym in gyms:
            result = self._setup_webhook_for_gym(gym["slug"], gym["calendar_id"])
            results[gym["slug"]] = result
            if result.get("success"):
                any_success = True

        return {"success": any_success, "gyms": results}

    def _setup_webhook_for_gym(self, gym_slug: str, calendar_id: str) -> Dict:
        try:
            calendar = GoogleCalendar(calendar_id=calendar_id)

            if not calendar.service:
                logger.error("Could not authenticate with Google Calendar for gym: %s", gym_slug)
                return {"success": False, "error": "Calendar authentication failed"}

            webhook_url = settings.google_calendar_webhook_url
            logger.info("Setting up calendar webhook for gym '%s': %s", gym_slug, webhook_url)

            result = calendar.watch_calendar(webhook_url, expiration_hours=168, token=gym_slug)

            if result.get("success"):
                self.active_watches[gym_slug] = {
                    "channel_id": result.get("channel_id"),
                    "resource_id": result.get("resource_id"),
                    "calendar": calendar,
                }
                logger.info(
                    "Calendar webhook for '%s' set up successfully. Expires: %s",
                    gym_slug,
                    result.get("expiration"),
                )
            else:
                logger.error("Failed to set up webhook for '%s': %s", gym_slug, result.get("error"))

            return result

        except Exception as e:
            logger.error("Error setting up calendar webhook for '%s': %s", gym_slug, e)
            return {"success": False, "error": str(e)}

    def renew_webhook(self) -> Dict:
        logger.info("Renewing calendar webhooks for all gyms...")
        self.stop_webhook()
        return self.setup_webhook()

    def stop_webhook(self) -> Dict:
        results = {}
        for gym_slug, watch_info in list(self.active_watches.items()):
            channel_id = watch_info.get("channel_id")
            resource_id = watch_info.get("resource_id")
            calendar = watch_info.get("calendar")

            if not calendar or not channel_id or not resource_id:
                results[gym_slug] = {"success": False, "error": "Incomplete watch info"}
                continue

            try:
                result = calendar.stop_watch(channel_id, resource_id)
                if result.get("success"):
                    logger.info("Calendar webhook stopped for gym '%s'", gym_slug)
                results[gym_slug] = result
            except Exception as e:
                logger.error("Error stopping webhook for '%s': %s", gym_slug, e)
                results[gym_slug] = {"success": False, "error": str(e)}

        self.active_watches.clear()
        return {"results": results}


# Global instance
calendar_webhook_service = CalendarWebhookService()
