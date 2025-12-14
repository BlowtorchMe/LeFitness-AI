"""
Leads API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database.database import get_db
from app.services.lead_service import LeadService
from app.models.lead import Lead, LeadStatus
from pydantic import BaseModel

router = APIRouter()


class LeadResponse(BaseModel):
    """Lead response model"""
    id: int
    name: str
    phone: str
    email: str | None
    status: str
    source: str
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[LeadResponse])
async def list_leads(
    status: str | None = None,
    db: Session = Depends(get_db)
):
    """List all leads"""
    lead_service = LeadService(db)
    
    if status:
        try:
            status_enum = LeadStatus[status.upper()]
            leads = lead_service.get_leads_for_followup(status_enum)
        except KeyError:
            raise HTTPException(status_code=400, detail="Invalid status")
    else:
        # Get all leads (would need to implement)
        leads = db.query(Lead).all()
    
    return leads


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """Get a specific lead"""
    lead_service = LeadService(db)
    lead = lead_service.get_lead(lead_id)
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    return lead

