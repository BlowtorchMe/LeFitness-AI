"""
Service for managing Google Calendar webhook setup and renewal.
Hanterar webhook-livscykeln för alla konfigurerade gym-kalendrar.
"""
from app.integrations.google_calendar import GoogleCalendar
from app.config import settings
from app.services.gym_calendar_config import get_gym_calendar_config
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)

# Alla konfigurerade gym-slugs som har kalendrar
ALL_GYM_SLUGS = ["taby", "varmdo"]


class CalendarWebhookService:
    """Manages Google Calendar webhook lifecycle for all gyms"""

    def __init__(self):
        # Spara channel_id och resource_id per gym-slug
        # Struktur: {"taby": {"channel_id": "...", "resource_id": "..."}, ...}
        self.active_watches: Dict[str, Dict[str, str]] = {}

    def setup_webhook(self) -> Dict:
        """
        Set up Google Calendar webhooks for all configured gyms.
        Returnerar en sammanfattning av resultaten per gym.
        """
        if not settings.google_service_account:
            logger.warning("Google service account not configured - skipping webhook setup")
            return {"success": False, "error": "Google service account not configured"}

        if not settings.google_calendar_webhook_url:
            logger.warning("GOOGLE_CALENDAR_WEBHOOK_URL not set - skipping webhook setup")
            return {"success": False, "error": "Webhook URL not configured"}

        results = {}
        any_success = False

        for gym_slug in ALL_GYM_SLUGS:
            result = self._setup_webhook_for_gym(gym_slug)
            results[gym_slug] = result
            if result.get("success"):
                any_success = True

        return {
            "success": any_success,
            "gyms": results
        }

    def _setup_webhook_for_gym(self, gym_slug: str) -> Dict:
        """Sätter upp webhook för ett specifikt gym"""
        try:
            config = get_gym_calendar_config(gym_slug)
            if not config.calendar_id:
                logger.warning(f"No calendar_id configured for gym: {gym_slug}")
                return {"success": False, "error": f"No calendar_id for {gym_slug}"}

            calendar = GoogleCalendar(calendar_id=config.calendar_id)

            if not calendar.service:
                logger.error(f"Could not authenticate with Google Calendar for gym: {gym_slug}")
                return {"success": False, "error": "Calendar authentication failed"}

            webhook_url = settings.google_calendar_webhook_url
            logger.info(f"Setting up calendar webhook for gym '{gym_slug}': {webhook_url}")

            result = calendar.watch_calendar(webhook_url, expiration_hours=168)

            if result.get("success"):
                self.active_watches[gym_slug] = {
                    "channel_id": result.get("channel_id"),
                    "resource_id": result.get("resource_id"),
                    "calendar": calendar,
                }
                logger.info(f"✅ Calendar webhook for '{gym_slug}' set up successfully! Expires at: {result.get('expiration')}")
                return result
            else:
                logger.error(f"Failed to set up webhook for '{gym_slug}': {result.get('error')}")
                return result

        except Exception as e:
            logger.error(f"Error setting up calendar webhook for '{gym_slug}': {e}")
            return {"success": False, "error": str(e)}

    def renew_webhook(self) -> Dict:
        """Renew calendar webhooks for all gyms (call this every 6-7 days)"""
        logger.info("Renewing calendar webhooks for all gyms...")
        # Stop old webhooks first
        self.stop_webhook()
        # Set up new webhooks
        return self.setup_webhook()

    def stop_webhook(self) -> Dict:
        """Stop all active webhooks"""
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
                    logger.info(f"Calendar webhook stopped for gym '{gym_slug}'")
                results[gym_slug] = result
            except Exception as e:
                logger.error(f"Error stopping webhook for '{gym_slug}': {e}")
                results[gym_slug] = {"success": False, "error": str(e)}

        self.active_watches.clear()
        return {"results": results}


# Global instance
calendar_webhook_service = CalendarWebhookService()