"""
Service for managing Google Calendar webhook setup and renewal
"""
from app.integrations.google_calendar import GoogleCalendar
from app.config import settings
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

class CalendarWebhookService:
    """Manages Google Calendar webhook lifecycle"""
    
    def __init__(self):
        self.calendar: Optional[GoogleCalendar] = None
        self.channel_id: Optional[str] = None
        self.resource_id: Optional[str] = None
    
    def setup_webhook(self) -> Dict:
        """Set up Google Calendar webhook"""
        if not settings.google_calendar_id or not settings.google_service_account:
            logger.warning("Google Calendar not configured - skipping webhook setup")
            return {"success": False, "error": "Google Calendar not configured"}
        
        if not settings.google_calendar_webhook_url:
            logger.warning("GOOGLE_CALENDAR_WEBHOOK_URL not set - skipping webhook setup")
            return {"success": False, "error": "Webhook URL not configured"}
        
        try:
            self.calendar = GoogleCalendar()
            
            if not self.calendar.service:
                logger.error("Could not authenticate with Google Calendar")
                return {"success": False, "error": "Calendar authentication failed"}
            
            webhook_url = settings.google_calendar_webhook_url
            logger.info(f"Setting up calendar webhook: {webhook_url}")
            
            result = self.calendar.watch_calendar(webhook_url, expiration_hours=168)
            
            if result.get("success"):
                self.channel_id = result.get("channel_id")
                self.resource_id = result.get("resource_id")
                logger.info(f"✅ Calendar webhook set up successfully! Expires at: {result.get('expiration')}")
                return result
            else:
                logger.error(f"Failed to set up webhook: {result.get('error')}")
                return result
                
        except Exception as e:
            logger.error(f"Error setting up calendar webhook: {e}")
            return {"success": False, "error": str(e)}
    
    def renew_webhook(self) -> Dict:
        """Renew the calendar webhook (call this every 6-7 days)"""
        logger.info("Renewing calendar webhook...")
        # Stop old webhook first if exists
        if self.channel_id and self.resource_id:
            try:
                self.stop_webhook()
            except Exception as e:
                logger.warning(f"Could not stop old webhook: {e}")
        # Set up new webhook
        return self.setup_webhook()
    
    def stop_webhook(self) -> Dict:
        """Stop the current webhook"""
        if not self.calendar or not self.channel_id or not self.resource_id:
            return {"success": False, "error": "No active webhook to stop"}
        
        try:
            result = self.calendar.stop_watch(self.channel_id, self.resource_id)
            if result.get("success"):
                logger.info("Calendar webhook stopped")
            return result
        except Exception as e:
            logger.error(f"Error stopping webhook: {e}")
            return {"success": False, "error": str(e)}


# Global instance
calendar_webhook_service = CalendarWebhookService()

