"""
Gym data model and schemas.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.database.base import Base


class GymSchema(BaseModel):
    name: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    phone: Optional[str] = None
    booking_url: str = Field(..., min_length=1)
    calendar_id: Optional[str] = None
    is_active: bool = True

    class Config:
        extra = "forbid"

    @model_validator(mode="before")
    @classmethod
    def strip_strings(cls, data):
        if isinstance(data, dict):
            normalized = dict(data)
            for key in ("name", "slug", "location", "booking_url"):
                if isinstance(normalized.get(key), str):
                    normalized[key] = normalized[key].strip()
            if isinstance(normalized.get("phone"), str):
                phone = normalized["phone"].strip()
                normalized["phone"] = phone or None
            if isinstance(normalized.get("calendar_id"), str):
                cal = normalized["calendar_id"].strip()
                normalized["calendar_id"] = cal or None
            if isinstance(normalized.get("slug"), str):
                normalized["slug"] = normalized["slug"].strip().lower()
            return normalized
        return data


class GymRecord(GymSchema):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Gym(Base):
    __tablename__ = "gyms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    location = Column(Text, nullable=False)
    phone = Column(String(50), nullable=True)
    booking_url = Column(Text, nullable=False)
    calendar_id = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_record(self) -> GymRecord:
        return GymRecord(
            id=self.id,
            name=self.name,
            slug=self.slug,
            location=self.location,
            phone=self.phone,
            booking_url=self.booking_url,
            calendar_id=self.calendar_id,
            is_active=bool(self.is_active),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
