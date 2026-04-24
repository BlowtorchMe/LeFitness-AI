"""
FAQ API: JSON import, add one, reindex.
"""
import json
import logging
from typing import List, Optional

import openai
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import settings
from app.database.database import get_db
from app.models.gym import Gym
from app.models.faq import FAQ, FAQSchema, FAQRecord
from app.faq_indexer import run_indexer, upsert_faq_embedding, delete_faq_embeddings

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_admin)])


class FAQImportResponse(BaseModel):
    imported: int
    reindexed: bool
    reindex_count: int = 0
    reindex_error: Optional[str] = None


class FAQImportItem(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    question_sv: Optional[str] = None
    answer_sv: Optional[str] = None
    video_link: Optional[str] = None
    gym_ids: Optional[List[int]] = None  # absent = global; present = gym-specific

    class Config:
        extra = "ignore"

    @model_validator(mode="before")
    @classmethod
    def strip_and_validate(cls, data):
        if isinstance(data, dict):
            for key in ("question", "answer", "question_sv", "answer_sv"):
                if key in data and isinstance(data.get(key), str):
                    v = data[key].strip()
                    data = {**data, key: v if v else None}
            if "video_link" in data and isinstance(data.get("video_link"), str):
                v = data["video_link"].strip()
                data = {**data, "video_link": v if v else None}
        has_en = bool(data.get("question") and data.get("answer"))
        has_sv = bool(data.get("question_sv") and data.get("answer_sv"))
        if not has_en and not has_sv:
            raise ValueError("Each item needs question+answer or question_sv+answer_sv")
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


class FAQWriteBody(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    source_lang: str = "en"
    video_link: Optional[str] = None
    gym_ids: List[int] = Field(default_factory=list)

    class Config:
        extra = "forbid"

    @model_validator(mode="before")
    @classmethod
    def strip_and_normalize(cls, data):
        if isinstance(data, dict):
            for key in ("question", "answer"):
                if key in data and isinstance(data.get(key), str):
                    data = {**data, key: data[key].strip()}
            if "video_link" in data and isinstance(data.get("video_link"), str):
                v = data["video_link"].strip()
                data = {**data, "video_link": v if v else None}
            if "source_lang" in data and data["source_lang"] not in ("en", "sv"):
                data = {**data, "source_lang": "en"}
        return data


def _translate(text: str, target_lang: str) -> Optional[str]:
    if not settings.openai_api_key or not text.strip():
        return None
    target_name = "Swedish" if target_lang == "sv" else "English"
    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)
        r = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": f"Reply with only the {target_name} translation. No explanation."},
                {"role": "user", "content": f"Translate to {target_name}:\n\n{text}"},
            ],
            temperature=0,
            max_tokens=400,
        )
        return (r.choices[0].message.content or "").strip() or None
    except Exception:
        logger.warning("faq_translate_failed target=%s", target_lang)
        return None


def _load_gym_map(db: Session, gym_ids: List[int]) -> dict[int, Gym]:
    if not gym_ids:
        return {}
    gyms = db.query(Gym).filter(Gym.id.in_(gym_ids)).all()
    gym_map = {gym.id: gym for gym in gyms}
    missing = [gym_id for gym_id in gym_ids if gym_id not in gym_map]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown gym ids: {missing}")
    return gym_map


def _apply_faq_body(faq: FAQ, body: FAQWriteBody, db: Session) -> None:
    if body.source_lang == "sv":
        faq.question_sv = body.question
        faq.answer_sv = body.answer
        faq.question = _translate(body.question, "en") or body.question
        faq.answer = _translate(body.answer, "en") or body.answer
    else:
        faq.question = body.question
        faq.answer = body.answer
        faq.question_sv = _translate(body.question, "sv")
        faq.answer_sv = _translate(body.answer, "sv")
    faq.video_link = body.video_link
    gym_map = _load_gym_map(db, body.gym_ids)
    faq.gyms = [gym_map[gym_id] for gym_id in body.gym_ids]


@router.get("/export")
async def export_faqs(db: Session = Depends(get_db)):
    """Export all FAQs as a JSON file. Only includes non-empty fields."""
    rows = db.query(FAQ).order_by(FAQ.id).all()
    items = []
    for faq in rows:
        item: dict = {}
        if faq.question:
            item["question"] = faq.question
        if faq.answer:
            item["answer"] = faq.answer
        if faq.question_sv:
            item["question_sv"] = faq.question_sv
        if faq.answer_sv:
            item["answer_sv"] = faq.answer_sv
        if faq.video_link:
            item["video_link"] = faq.video_link
        gym_ids = [g.id for g in faq.gyms]
        if gym_ids:
            item["gym_ids"] = gym_ids
        items.append(item)
    content = json.dumps(items, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=faqs.json"},
    )


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
        all_gym_ids = {gid for item in body if item.gym_ids for gid in item.gym_ids}
        gym_map: dict[int, Gym] = {}
        if all_gym_ids:
            gyms = db.query(Gym).filter(Gym.id.in_(all_gym_ids)).all()
            gym_map = {g.id: g for g in gyms}
            missing = all_gym_ids - gym_map.keys()
            if missing:
                raise HTTPException(status_code=400, detail=f"Unknown gym ids: {sorted(missing)}")

        for item in body:
            has_en = bool(item.question and item.answer)
            has_sv = bool(item.question_sv and item.answer_sv)

            q_en = item.question or (_translate(item.question_sv, "en") if item.question_sv else None)
            a_en = item.answer or (_translate(item.answer_sv, "en") if item.answer_sv else None)
            q_sv = item.question_sv or (_translate(item.question, "sv") if item.question else None)
            a_sv = item.answer_sv or (_translate(item.answer, "sv") if item.answer else None)

            if not q_en or not a_en:
                raise HTTPException(status_code=400, detail="Could not resolve English question/answer")

            faq = FAQ(
                question=q_en,
                answer=a_en,
                question_sv=q_sv,
                answer_sv=a_sv,
                video_link=item.video_link,
            )
            faq.gyms = [gym_map[gid] for gid in (item.gym_ids or [])]
            db.add(faq)

        db.commit()
    except HTTPException:
        db.rollback()
        raise
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
async def create_faq(body: FAQWriteBody, db: Session = Depends(get_db)):
    """Add one FAQ. Example for admin form (add one by one)."""
    faq = FAQ()
    _apply_faq_body(faq, body, db)
    db.add(faq)
    try:
        db.commit()
        db.refresh(faq)
        sync = upsert_faq_embedding(faq)
        if not sync.get("success"):
            raise HTTPException(status_code=500, detail=f"Failed to index FAQ embedding: {sync.get('error')}")
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
async def update_faq(faq_id: int, body: FAQWriteBody, db: Session = Depends(get_db)):
    """Update an existing FAQ."""
    _validate_faq_id(faq_id)
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    try:
        _apply_faq_body(faq, body, db)
        db.commit()
        db.refresh(faq)
        sync = upsert_faq_embedding(faq)
        if not sync.get("success"):
            raise HTTPException(status_code=500, detail=f"Failed to update FAQ embedding: {sync.get('error')}")
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
