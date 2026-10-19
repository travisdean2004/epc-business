from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr


class LeadCreate(BaseModel):
    name: str
    email: EmailStr
    company: str
    message: str


class LeadAnalysisOut(BaseModel):
    id: int
    lead_id: int
    lead_score: int
    priority: str
    summary: str
    recommended_action: str
    crm_route: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadOut(BaseModel):
    id: int
    name: str
    email: str
    company: str
    message: str
    created_at: datetime
    analysis: Optional[LeadAnalysisOut] = None

    model_config = {"from_attributes": True}


class WebhookResponse(BaseModel):
    status: str
    lead_id: int
    analysis: LeadAnalysisOut


class PaginatedLeads(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[LeadOut]
