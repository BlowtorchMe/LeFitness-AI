"""
FAQ API: JSON import, add one, reindex.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database.database import get_db
from app.models.gym import Gym
from app.models.faq import FAQ, FAQSchema, FAQRecord
from app.faq_indexer import run_indexer, upsert_faq_embedding, delete_faq_embeddings

router = APIRouter(dependencies=[Depends(require_admin)])


class FAQImportResponse(BaseModel):
    imported: int
    reindexed: bool
    reindex_count: int = 0
    reindex_error: Optional[str] = None


class FAQImportItem(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    video_link: Optional[str] = None

    class Config:
        extra = "ignore"

    @model_validator(mode="before")
    @classmethod
    def strip_strings(cls, data):
        if isinstance(data, dict):
            for key in ("question", "answer"):
                if key in data and isinstance(data.get(key), str):
                    data = {**data, key: data[key].strip()}
            if "video_link" in data and isinstance(data.get("video_link"), str):
                value = data["video_link"].strip()
                data = {**data, "video_link": value if value else None}
        return data


class ReindexResponse(BaseModel):
    success: bool
    count: int
    error: Optional[str] = None


class FAQListResponse(BaseModel):
    items: List[FAQRecord]
    total: int
    page: int
    size: int


MAX_IMPORT_SIZE = 500


def _load_gym_map(db: Session, gym_ids: List[int]) -> dict[int, Gym]:
    if not gym_ids:
        return {}
    gyms = db.query(Gym).filter(Gym.id.in_(gym_ids)).all()
    gym_map = {gym.id: gym for gym in gyms}
    missing = [gym_id for gym_id in gym_ids if gym_id not in gym_map]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown gym ids: {missing}")
    return gym_map


def _apply_faq_body(faq: FAQ, body: FAQSchema, db: Session) -> None:
    faq.question = body.question
    faq.answer = body.answer
    faq.video_link = body.video_link
    gym_map = _load_gym_map(db, body.gym_ids)
    faq.gyms = [gym_map[gym_id] for gym_id in body.gym_ids]


@router.post("/import", response_model=FAQImportResponse)
async def import_faqs(
    body: List[FAQImportItem],
    reindex: bool = False,
    db: Session = Depends(get_db),
):
    """Import FAQs from JSON array. Optionally run indexer after (?reindex=true)."""
    if not body:
        return FAQImportResponse(imported=0, reindexed=False)
    if len(body) > MAX_IMPORT_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Too many items: max {MAX_IMPORT_SIZE}, got {len(body)}",
        )
    try:
        for item in body:
            faq = FAQ(question=item.question, answer=item.answer, video_link=item.video_link)
            faq.gyms = []
            db.add(faq)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")
    imported = len(body)
    reindex_count = 0
    reindex_error = None
    if reindex and imported:
        result = run_indexer(recreate_table=False)
        reindex_count = result.get("count", 0)
        reindex_error = result.get("error")
    return FAQImportResponse(
        imported=imported,
        reindexed=reindex,
        reindex_count=reindex_count,
        reindex_error=reindex_error,
    )


@router.post("/reindex", response_model=ReindexResponse)
async def reindex_faqs():
    """Run FAQ indexer (embed FAQs from DB into pgvector). For admin use."""
    result = run_indexer(recreate_table=False)
    return ReindexResponse(
        success=result["success"],
        count=result["count"],
        error=result.get("error"),
    )


@router.post("/", response_model=FAQRecord)
async def create_faq(body: FAQSchema, db: Session = Depends(get_db)):
    """Add one FAQ. Example for admin form (add one by one)."""
    faq = FAQ()
    _apply_faq_body(faq, body, db)
    db.add(faq)
    try:
        db.flush()
        sync = upsert_faq_embedding(faq)
        if not sync.get("success"):
            raise HTTPException(status_code=500, detail=f"Failed to index FAQ embedding: {sync.get('error')}")
        db.commit()
        db.refresh(faq)
        return faq.to_record()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create FAQ: {str(e)}")


@router.get("/", response_model=FAQListResponse)
async def list_faqs(
    page: int = 1,
    size: int = 10,
    db: Session = Depends(get_db),
):
    """List FAQs with pagination. page=1-based, size=page size (default 10)."""
    if page < 1:
        page = 1
    if size < 1:
        size = 10
    if size > 100:
        size = 100
    total = db.query(FAQ).count()
    offset = (page - 1) * size
    rows = db.query(FAQ).order_by(FAQ.id.asc()).offset(offset).limit(size).all()
    return FAQListResponse(
        items=[r.to_record() for r in rows],
        total=total,
        page=page,
        size=size,
    )


def _validate_faq_id(faq_id: int) -> None:
    if faq_id < 1:
        raise HTTPException(status_code=422, detail="faq_id must be a positive integer")


@router.get("/{faq_id}", response_model=FAQRecord)
async def get_faq(faq_id: int, db: Session = Depends(get_db)):
    """Get one FAQ by id."""
    _validate_faq_id(faq_id)
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return faq.to_record()


@router.put("/{faq_id}", response_model=FAQRecord)
async def update_faq(faq_id: int, body: FAQSchema, db: Session = Depends(get_db)):
    """Update an existing FAQ."""
    _validate_faq_id(faq_id)
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    try:
        _apply_faq_body(faq, body, db)
        sync = upsert_faq_embedding(faq)
        if not sync.get("success"):
            raise HTTPException(status_code=500, detail=f"Failed to update FAQ embedding: {sync.get('error')}")
        db.commit()
        db.refresh(faq)
        return faq.to_record()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update FAQ: {str(e)}")


@router.delete("/{faq_id}", status_code=204)
async def delete_faq(faq_id: int, db: Session = Depends(get_db)):
    """Delete an FAQ."""
    _validate_faq_id(faq_id)
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    try:
        sync = delete_faq_embeddings(faq_id)
        if not sync.get("success"):
            raise HTTPException(status_code=500, detail=f"Failed to delete FAQ embedding: {sync.get('error')}")
        db.delete(faq)
        db.commit()
        return None
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete FAQ: {str(e)}")
