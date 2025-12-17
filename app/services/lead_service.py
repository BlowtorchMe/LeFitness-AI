"""
Lead management service
"""
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from app.models.lead import Lead, LeadStatus
from app.database.database import get_db
from datetime import datetime


class LeadService:
    """Service for managing leads"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_lead(
        self,
        name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        messenger_id: Optional[str] = None,
        platform: Optional[str] = None,
        source: str = "meta_ad",
        ad_campaign: Optional[str] = None
    ) -> Lead:
        """Create a new lead"""
        lead = Lead(
            name=name,
            phone=phone,
            email=email,
            messenger_id=messenger_id,
            platform=platform,
            source=source,
            ad_campaign=ad_campaign,
            status=LeadStatus.NEW,
            conversation_started=datetime.utcnow(),
            last_contact=datetime.utcnow()
        )
        
        self.db.add(lead)
        self.db.commit()
        self.db.refresh(lead)
        
        return lead
    
    def get_lead_by_phone(self, phone: str) -> Optional[Lead]:
        """Get lead by phone number"""
        return self.db.query(Lead).filter(Lead.phone == phone).first()
    
    def get_lead_by_messenger_id(self, messenger_id: str) -> Optional[Lead]:
        """Get lead by Messenger/Instagram ID"""
        return self.db.query(Lead).filter(Lead.messenger_id == messenger_id).first()
    
    def get_lead_by_email(self, email: str) -> Optional[Lead]:
        """Get lead by email address"""
        return self.db.query(Lead).filter(Lead.email == email).first()
    
    def get_lead(self, lead_id: int) -> Optional[Lead]:
        """Get lead by ID"""
        return self.db.query(Lead).filter(Lead.id == lead_id).first()
    
    def update_lead_status(self, lead_id: int, status: LeadStatus) -> Optional[Lead]:
        """Update lead status"""
        lead = self.get_lead(lead_id)
        if lead:
            lead.status = status
            lead.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(lead)
        return lead
    
    def link_booking(self, lead_id: int, booking_id: int, booking_date: datetime) -> Optional[Lead]:
        """Link a booking to a lead"""
        lead = self.get_lead(lead_id)
        if lead:
            lead.booking_id = booking_id
            lead.booking_date = booking_date
            lead.status = LeadStatus.BOOKED
            lead.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(lead)
        return lead
    
    def mark_visited(self, lead_id: int) -> Optional[Lead]:
        """Mark lead as visited"""
        lead = self.get_lead(lead_id)
        if lead:
            lead.visited = datetime.utcnow()
            lead.status = LeadStatus.VISITED
            lead.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(lead)
        return lead
    
    def get_leads_for_followup(self, status: Optional[LeadStatus] = None) -> List[Lead]:
        """Get leads that need follow-up"""
        query = self.db.query(Lead)
        
        if status:
            query = query.filter(Lead.status == status)
        else:
            # Default: leads that booked but didn't show, or visited but didn't convert
            query = query.filter(
                Lead.status.in_([LeadStatus.BOOKED, LeadStatus.VISITED])
            )
        
        return query.all()
    
    def increment_message_count(self, lead_id: int) -> Optional[Lead]:
        """Increment message count for a lead"""
        lead = self.get_lead(lead_id)
        if lead:
            lead.message_count += 1
            lead.last_contact = datetime.utcnow()
            self.db.commit()
            self.db.refresh(lead)
        return lead

