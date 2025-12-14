"""
Reminder scheduling service
"""
from typing import List, Dict
from app.services.booking_service import BookingService
from app.integrations.twilio_sms import TwilioSMS
from app.config import settings
from datetime import datetime


class ReminderService:
    """Service for sending appointment reminders"""
    
    def __init__(self, booking_service: BookingService):
        self.booking_service = booking_service
        self.sms = TwilioSMS()
    
    def send_reminders(self, hours_before: int = 2) -> List[Dict]:
        """
        Send reminders for upcoming appointments
        
        Args:
            hours_before: How many hours before appointment to send reminder
        
        Returns:
            List of reminder results
        """
        bookings = self.booking_service.get_bookings_needing_reminder(hours_before)
        results = []
        
        for booking in bookings:
            result = self.sms.send_reminder(
                to=booking.phone,
                appointment_time=booking.appointment_time.strftime("%H:%M"),
                date=booking.appointment_time.strftime("%Y-%m-%d")
            )
            
            if result.get("success"):
                booking.reminder_sent = datetime.utcnow()
                booking.reminder_count += 1
                self.booking_service.db.commit()
            
            results.append({
                "booking_id": booking.id,
                "customer": booking.customer_name,
                "phone": booking.phone,
                "result": result
            })
        
        return results

