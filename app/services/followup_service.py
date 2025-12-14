"""
Follow-up automation service
"""
from typing import List, Dict
from app.services.lead_service import LeadService
from app.integrations.twilio_sms import TwilioSMS
from app.models.lead import LeadStatus
from app.config import settings
from datetime import datetime, timedelta


class FollowupService:
    """Service for automated follow-ups"""
    
    def __init__(self, lead_service: LeadService):
        self.lead_service = lead_service
        self.sms = TwilioSMS()
    
    def followup_missed_appointments(self) -> List[Dict]:
        """
        Follow up with customers who missed appointments
        
        Returns:
            List of follow-up results
        """
        # Get leads who booked but didn't show up
        leads = self.lead_service.get_leads_for_followup(LeadStatus.BOOKED)
        results = []
        
        for lead in leads:
            # Check if booking was missed (more than 1 day ago, no visit recorded)
            if lead.booking_date and not lead.visited:
                days_since_booking = (datetime.utcnow() - lead.booking_date).days
                
                if days_since_booking >= 1:
                    message = f"Hi {lead.name}! We missed you at your appointment. Would you like to book a new appointment? I'd be happy to help!"
                    
                    result = self.sms.send_followup(lead.phone, message)
                    
                    if result.get("success"):
                        lead.status = LeadStatus.FOLLOWUP
                        lead.last_contact = datetime.utcnow()
                        self.lead_service.db.commit()
                    
                    results.append({
                        "lead_id": lead.id,
                        "name": lead.name,
                        "phone": lead.phone,
                        "result": result
                    })
        
        return results
    
    def followup_trial_expired(self, days_after_trial: int = 3) -> List[Dict]:
        """
        Follow up with customers whose trial period expired
        
        Args:
            days_after_trial: Days after trial expiration to follow up
        
        Returns:
            List of follow-up results
        """
        # Get leads who visited but didn't convert
        leads = self.lead_service.get_leads_for_followup(LeadStatus.VISITED)
        results = []
        
        for lead in leads:
            if lead.visited:
                days_since_visit = (datetime.utcnow() - lead.visited).days
                
                # Check if trial period + follow-up period has passed
                if days_since_visit >= (settings.free_trial_days + days_after_trial):
                    message = f"Hi {lead.name}! Your free trial period has ended. Would you like to continue your fitness journey with us? We have great membership options available!"
                    
                    result = self.sms.send_followup(lead.phone, message)
                    
                    if result.get("success"):
                        lead.last_contact = datetime.utcnow()
                        self.lead_service.db.commit()
                    
                    results.append({
                        "lead_id": lead.id,
                        "name": lead.name,
                        "phone": lead.phone,
                        "result": result
                    })
        
        return results

