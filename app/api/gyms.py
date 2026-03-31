"""
Gym admin API endpoints.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database.database import get_db
from app.models.gym import Gym, GymRecord, GymSchema

router = APIRouter(dependencies=[Depends(require_admin)])


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
async def create_gym(body: GymSchema, db: Session = Depends(get_db)):
    _ensure_unique_slug(db, body.slug)
    gym = Gym(
        name=body.name,
        slug=body.slug,
        location=body.location,
        phone=body.phone,
        booking_url=body.booking_url,
        is_active=body.is_active,
    )
    db.add(gym)
    db.commit()
    db.refresh(gym)
    return gym.to_record()


@router.put("/{gym_id}", response_model=GymRecord)
async def update_gym(gym_id: int, body: GymSchema, db: Session = Depends(get_db)):
    gym = db.query(Gym).filter(Gym.id == gym_id).first()
    if not gym:
        raise HTTPException(status_code=404, detail="Gym not found")
    _ensure_unique_slug(db, body.slug, gym_id=gym_id)
    gym.name = body.name
    gym.slug = body.slug
    gym.location = body.location
    gym.phone = body.phone
    gym.booking_url = body.booking_url
    gym.is_active = body.is_active
    db.commit()
    db.refresh(gym)
    return gym.to_record()


@router.delete("/{gym_id}", response_model=GymRecord)
async def delete_gym(gym_id: int, db: Session = Depends(get_db)):
    gym = db.query(Gym).filter(Gym.id == gym_id).first()
    if not gym:
        raise HTTPException(status_code=404, detail="Gym not found")
    gym.is_active = False
    db.commit()
    db.refresh(gym)
    return gym.to_record()
