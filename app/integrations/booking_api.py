"""
Booking system API integration
DEPRECATED: Replaced by Google Calendar integration
This file is kept for backward compatibility but should not be used
"""
import requests
from app.config import settings
from typing import Dict, Optional, List
from datetime import datetime


class BookingAPI:
    """DEPRECATED: Use GoogleCalendar instead"""
    
    def __init__(self):
        # This class is deprecated
        pass
    
    def create_booking(
        self,
        customer_name: str,
        phone: str,
        email: Optional[str],
        appointment_time: datetime,
        appointment_type: str = "trial_activation"
    ) -> Dict[str, any]:
        """
        Create a booking in the booking system
        
        Args:
            customer_name: Customer name
            phone: Customer phone number
            email: Customer email (optional)
            appointment_time: Appointment datetime
            appointment_type: Type of appointment (trial_activation, tour, etc.)
        
        Returns:
            Dict with booking result
        """
        booking_data = {
            "customer_name": customer_name,
            "phone": phone,
            "email": email,
            "appointment_time": appointment_time.isoformat(),
            "appointment_type": appointment_type,
            "status": "confirmed"
        }
        
        try:
            response = requests.post(
                f"{self.api_url}/bookings",
                headers=self.headers,
                json=booking_data
            )
            
            if response.status_code in [200, 201]:
                return {
                    "success": True,
                    "booking_id": response.json().get("id"),
                    "booking": response.json()
                }
            else:
                return {
                    "success": False,
                    "error": response.text,
                    "status_code": response.status_code
                }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_available_slots(self, date: str) -> List[Dict]:
        """
        Get available booking slots for a date
        
        Args:
            date: Date string (YYYY-MM-DD)
        
        Returns:
            List of available time slots
        """
        try:
            response = requests.get(
                f"{self.api_url}/bookings/available",
                headers=self.headers,
                params={"date": date}
            )
            
            if response.status_code == 200:
                return response.json().get("slots", [])
            else:
                return []
        
        except Exception as e:
            return []
    
    def update_booking(self, booking_id: str, updates: Dict) -> Dict[str, any]:
        """Update an existing booking"""
        try:
            response = requests.patch(
                f"{self.api_url}/bookings/{booking_id}",
                headers=self.headers,
                json=updates
            )
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "booking": response.json()
                }
            else:
                return {
                    "success": False,
                    "error": response.text
                }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def cancel_booking(self, booking_id: str) -> Dict[str, any]:
        """Cancel a booking"""
        return self.update_booking(booking_id, {"status": "cancelled"})
    
    def get_booking(self, booking_id: str) -> Optional[Dict]:
        """Get booking details"""
        try:
            response = requests.get(
                f"{self.api_url}/bookings/{booking_id}",
                headers=self.headers
            )
            
            if response.status_code == 200:
                return response.json()
            return None
        
        except Exception as e:
            return None

