"""
FAQ schema and DB model.
Canonical shape for JSON, CSV, DB, and text-extraction output.
"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Column, Integer, Text, DateTime
from app.database.base import Base


class FAQSchema(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    video_link: Optional[str] = None

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
        return data


class FAQRecord(FAQSchema):
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FAQ(Base):
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    video_link = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_record(self) -> FAQRecord:
        return FAQRecord(
            id=self.id,
            question=self.question,
            answer=self.answer,
            video_link=self.video_link,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
