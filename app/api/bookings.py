"""
Bookings API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database.database import get_db
from app.services.booking_service import BookingService
from app.models.booking import Booking
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()


class BookingResponse(BaseModel):
    """Booking response model"""
    id: int
    customer_name: str
    phone: str
    email: str | None
    appointment_time: datetime
    status: str
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[BookingResponse])
async def list_bookings(db: Session = Depends(get_db)):
    """List all bookings"""
    bookings = db.query(Booking).all()
    return bookings


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(booking_id: int, db: Session = Depends(get_db)):
    """Get a specific booking"""
    booking_service = BookingService(db)
    booking = booking_service.get_booking(booking_id)
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    return booking


@router.get("/available/slots")
async def get_available_slots(date: str, db: Session = Depends(get_db)):
    """Get available booking slots for a date (format: YYYY-MM-DD)"""
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        booking_service = BookingService(db)
        slots = booking_service.get_available_slots(date_obj)
        return {"date": date, "slots": slots}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

