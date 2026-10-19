import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.lead import Lead, LeadAnalysis
from app.schemas.lead import LeadCreate, WebhookResponse
from app.services.crm_service import get_crm_route
from app.services.notification_service import send_lead_notification
from app.services.openai_service import qualify_lead

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook/lead", response_model=WebhookResponse, status_code=201)
def receive_lead(payload: LeadCreate, db: Session = Depends(get_db)):
    lead = Lead(
        name=payload.name,
        email=payload.email,
        company=payload.company,
        message=payload.message,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    ai_result = qualify_lead(
        name=payload.name,
        email=payload.email,
        company=payload.company,
        message=payload.message,
    )

    if ai_result is None:
        db.delete(lead)
        db.commit()
        raise HTTPException(status_code=502, detail="AI qualification failed. Check your OPENAI_API_KEY and try again.")

    crm_route = get_crm_route(ai_result["lead_score"])

    analysis = LeadAnalysis(
        lead_id=lead.id,
        lead_score=ai_result["lead_score"],
        priority=ai_result["priority"],
        summary=ai_result["summary"],
        recommended_action=ai_result["recommended_action"],
        crm_route=crm_route,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    send_lead_notification(
        company=payload.company,
        priority=ai_result["priority"],
        lead_score=ai_result["lead_score"],
        crm_route=crm_route,
    )

    return WebhookResponse(status="qualified", lead_id=lead.id, analysis=analysis)
