from dataclasses import dataclass
from typing import Optional
from app.config import settings


@dataclass
class GymCalendarConfig:
    calendar_id: Optional[str]
    appointment_schedule_link: Optional[str]


def get_gym_calendar_config(gym_slug: str) -> GymCalendarConfig:
    gym = (gym_slug or "").strip().lower()

    if gym == "taby":
        return GymCalendarConfig(
            calendar_id=settings.google_calendar_taby_id,
            appointment_schedule_link=settings.google_appointment_schedule_taby_link,
        )

    if gym == "varmdo":
        return GymCalendarConfig(
            calendar_id=settings.google_calendar_varmdo_id,
            appointment_schedule_link=settings.google_appointment_schedule_varmdo_link,
        )

    raise ValueError(f"Unknown gym slug: {gym_slug}")