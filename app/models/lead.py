"""
Lead data model
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Enum
from app.database.base import Base
from datetime import datetime
import enum


class LeadStatus(enum.Enum):
    """Lead status enumeration"""
    NEW = "new"
    CONTACTED = "contacted"
    BOOKED = "booked"
    VISITED = "visited"
    CONVERTED = "converted"
    LOST = "lost"
    FOLLOWUP = "followup"


class Lead(Base):
    """Lead model for CRM"""
    __tablename__ = "leads"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True, index=True)  # Can be null for Messenger-only leads
    email = Column(String(255), nullable=True)
    
    # Messenger/Instagram identifiers
    messenger_id = Column(String(100), nullable=True, index=True)  # Facebook/Instagram user ID
    platform = Column(String(20), nullable=True)  # "messenger" or "instagram"
    
    # Source information
    source = Column(String(50), default="meta_ad")  # meta_ad, referral, etc.
    ad_campaign = Column(String(100), nullable=True)
    
    # Status
    status = Column(Enum(LeadStatus), default=LeadStatus.NEW)
    
    # Conversation tracking
    conversation_started = Column(DateTime, default=datetime.utcnow)
    last_contact = Column(DateTime, default=datetime.utcnow)
    message_count = Column(Integer, default=0)
    
    # Booking information
    booking_id = Column(Integer, nullable=True)
    booking_date = Column(DateTime, nullable=True)
    visited = Column(DateTime, nullable=True)
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Conversation state
    conversation_state = Column(String(50), default="welcome")  # Track conversation flow state
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Lead(id={self.id}, name={self.name}, phone={self.phone}, status={self.status})>"

