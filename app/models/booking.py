"""
Booking data model
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text
from app.database.base import Base
from datetime import datetime
import enum


class BookingStatus(enum.Enum):
    """Booking status enumeration"""
    CONFIRMED = "confirmed"
    PENDING = "pending"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    RESCHEDULED = "rescheduled"


class AppointmentType(enum.Enum):
    """Appointment type enumeration"""
    TRIAL_ACTIVATION = "trial_activation"
    GYM_TOUR = "gym_tour"
    CONSULTATION = "consultation"
    OTHER = "other"


class Booking(Base):
    """Booking model"""
    __tablename__ = "bookings"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    
    # Customer information
    customer_name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    email = Column(String(255), nullable=True)
    
    # Appointment details
    appointment_time = Column(DateTime, nullable=False, index=True)
    appointment_type = Column(Enum(AppointmentType), default=AppointmentType.TRIAL_ACTIVATION)
    duration_minutes = Column(Integer, default=60)
    
    # Status
    status = Column(Enum(BookingStatus), default=BookingStatus.CONFIRMED)
    
    # Reminders
    reminder_sent = Column(DateTime, nullable=True)
    reminder_count = Column(Integer, default=0)
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Google Calendar event ID
    external_booking_id = Column(String(100), nullable=True)  # Stores Google Calendar event ID
    calendar_link = Column(String(500), nullable=True)  # Google Calendar HTML link
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Booking(id={self.id}, customer={self.customer_name}, time={self.appointment_time}, status={self.status})>"

