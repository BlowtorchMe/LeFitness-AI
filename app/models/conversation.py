"""
Conversation data model
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Enum, Boolean
from app.database.base import Base
from datetime import datetime
import enum


class MessageDirection(enum.Enum):
    """Message direction enumeration"""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class ConversationChannel(enum.Enum):
    """Conversation channel enumeration"""
    SMS = "sms"
    MESSENGER = "messenger"
    WHATSAPP = "whatsapp"


class Conversation(Base):
    """Conversation model for tracking messages"""
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    
    # Channel information
    channel = Column(Enum(ConversationChannel), nullable=False)
    phone_number = Column(String(20), nullable=True)
    messenger_id = Column(String(100), nullable=True)
    
    # Message details
    direction = Column(Enum(MessageDirection), nullable=False)
    message_text = Column(Text, nullable=False)
    
    # AI processing
    intent = Column(String(50), nullable=True)
    ai_response = Column(Text, nullable=True)
    faq_used = Column(String(50), nullable=True)
    needs_human = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f"<Conversation(id={self.id}, channel={self.channel}, direction={self.direction})>"

