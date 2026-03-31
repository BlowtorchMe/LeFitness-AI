"""
FAQ schema and DB model.
Canonical shape for JSON, CSV, DB, and text-extraction output.
"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.gym import GymRecord


faq_gyms = Table(
    "faq_gyms",
    Base.metadata,
    Column("faq_id", Integer, ForeignKey("faqs.id", ondelete="CASCADE"), primary_key=True),
    Column("gym_id", Integer, ForeignKey("gyms.id", ondelete="CASCADE"), primary_key=True),
)


class FAQSchema(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    video_link: Optional[str] = None
    gym_ids: List[int] = Field(default_factory=list)

    class Config:
        extra = "forbid"

    @model_validator(mode="before")
    @classmethod
    def strip_strings(cls, data):
        if isinstance(data, dict):
            for key in ("question", "answer"):
                if key in data and isinstance(data.get(key), str):
                    data = {**data, key: data[key].strip()}
            if "video_link" in data and isinstance(data.get("video_link"), str):
                v = data["video_link"].strip()
                data = {**data, "video_link": v if v else None}
            if "gym_ids" in data and isinstance(data.get("gym_ids"), list):
                gym_ids = []
                for value in data["gym_ids"]:
                    try:
                        gym_id = int(value)
                    except (TypeError, ValueError):
                        continue
                    if gym_id > 0 and gym_id not in gym_ids:
                        gym_ids.append(gym_id)
                data = {**data, "gym_ids": gym_ids}
        return data


class FAQRecord(FAQSchema):
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    gyms: List[GymRecord] = Field(default_factory=list)


class FAQ(Base):
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    video_link = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    gyms = relationship("Gym", secondary=faq_gyms, lazy="joined")

    def to_record(self) -> FAQRecord:
        return FAQRecord(
            id=self.id,
            question=self.question,
            answer=self.answer,
            video_link=self.video_link,
            gym_ids=[gym.id for gym in self.gyms],
            gyms=[gym.to_record() for gym in self.gyms],
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
