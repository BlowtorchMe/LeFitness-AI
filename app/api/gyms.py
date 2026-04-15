"""
Gym admin API endpoints.
"""
import logging
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database.database import get_db
from app.models.gym import Gym, GymRecord, GymSchema
from app.services.calendar_webhook_service import calendar_webhook_service

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_admin)])


def _renew_watchers() -> None:
    """Re-register calendar watches after gym changes. Runs in background."""
    try:
        result = calendar_webhook_service.renew_webhook()
        logger.info("Calendar watchers renewed after gym change: %s", result.get("success"))
    except Exception:
        logger.exception("Failed to renew calendar watchers after gym change")


@router.get("/", response_model=List[GymRecord])
async def list_gyms(db: Session = Depends(get_db)):
    gyms = db.query(Gym).order_by(Gym.name.asc()).all()
    return [gym.to_record() for gym in gyms]


@router.get("/{gym_id}", response_model=GymRecord)
async def get_gym(gym_id: int, db: Session = Depends(get_db)):
    gym = db.query(Gym).filter(Gym.id == gym_id).first()
    if not gym:
        raise HTTPException(status_code=404, detail="Gym not found")
    return gym.to_record()


def _ensure_unique_slug(db: Session, slug: str, gym_id: int | None = None) -> None:
    query = db.query(Gym).filter(Gym.slug == slug)
    if gym_id is not None:
        query = query.filter(Gym.id != gym_id)
    if query.first():
        raise HTTPException(status_code=400, detail="Gym slug already exists")


@router.post("/", response_model=GymRecord)
async def create_gym(body: GymSchema, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    _ensure_unique_slug(db, body.slug)
    gym = Gym(
        name=body.name,
        slug=body.slug,
        location=body.location,
        phone=body.phone,
        booking_url=body.booking_url,
        calendar_id=body.calendar_id,
        is_active=body.is_active,
    )
    db.add(gym)
    db.commit()
    db.refresh(gym)
    if body.calendar_id and body.is_active:
        background_tasks.add_task(_renew_watchers)
    return gym.to_record()


@router.put("/{gym_id}", response_model=GymRecord)
async def update_gym(gym_id: int, body: GymSchema, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    gym = db.query(Gym).filter(Gym.id == gym_id).first()
    if not gym:
        raise HTTPException(status_code=404, detail="Gym not found")
    old_calendar_id = gym.calendar_id
    _ensure_unique_slug(db, body.slug, gym_id=gym_id)
    gym.name = body.name
    gym.slug = body.slug
    gym.location = body.location
    gym.phone = body.phone
    gym.booking_url = body.booking_url
    gym.calendar_id = body.calendar_id
    gym.is_active = body.is_active
    db.commit()
    db.refresh(gym)
    # Renew if calendar_id changed or active status changed
    if body.calendar_id != old_calendar_id or not body.is_active:
        background_tasks.add_task(_renew_watchers)
    return gym.to_record()


@router.delete("/{gym_id}", response_model=GymRecord)
async def delete_gym(gym_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    gym = db.query(Gym).filter(Gym.id == gym_id).first()
    if not gym:
        raise HTTPException(status_code=404, detail="Gym not found")
    gym.is_active = False
    db.commit()
    db.refresh(gym)
    background_tasks.add_task(_renew_watchers)
    return gym.to_record()
