from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.lead import Lead
from app.schemas.lead import LeadOut, PaginatedLeads

router = APIRouter()


@router.get("/leads", response_model=PaginatedLeads)
def list_leads(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum records to return"),
    db: Session = Depends(get_db),
):
    total = db.query(Lead).count()
    items = db.query(Lead).order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()
    return PaginatedLeads(total=total, skip=skip, limit=limit, items=items)


@router.get("/leads/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead
