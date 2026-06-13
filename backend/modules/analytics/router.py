"""Read-only analytics API — Phase 5A.

All endpoints are GET-only and scoped to the current tenant's organisation.
No mutations are performed.

Prefix: /analytics (registered in main.py under API_PREFIX)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.dependencies import get_db
from modules.auth.tenant import get_current_tenant
from modules.analytics.repository import AnalyticsRepository
from modules.analytics.schema import (
    CallAnalyticsResponse,
    EmailAnalyticsResponse,
    FunnelResponse,
    LinkedInAnalyticsResponse,
    MeetingsTrendResponse,
    OverviewResponse,
    TrendsResponse,
    WorkflowAnalyticsResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _org_uuid(tenant: dict) -> uuid.UUID:
    return uuid.UUID(str(tenant["organization_id"]))


def _days_param(days: int = Query(default=30, ge=1, le=365)) -> int:
    return days


# ---------------------------------------------------------------------------
# Overview — campaigns + executions + leads
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    days: int = Depends(_days_param),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Aggregate KPIs: campaign counts, execution rates, lead statuses."""
    org_id = _org_uuid(tenant)
    campaigns = AnalyticsRepository.campaign_summary(db, org_id)
    executions = AnalyticsRepository.execution_summary(db, org_id, days)
    leads = AnalyticsRepository.lead_summary(db, org_id)
    return OverviewResponse(
        campaigns=campaigns,
        executions=executions,
        leads=leads,
        total_leads_processed=executions["completed"] + executions["failed"],
    )


# ---------------------------------------------------------------------------
# Email analytics
# ---------------------------------------------------------------------------


@router.get("/email", response_model=EmailAnalyticsResponse)
async def email_analytics(
    days: int = Depends(_days_param),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Emails sent, failed, success rate, and daily trend."""
    return AnalyticsRepository.email_analytics(db, _org_uuid(tenant), days)


# ---------------------------------------------------------------------------
# Call analytics
# ---------------------------------------------------------------------------


@router.get("/calls", response_model=CallAnalyticsResponse)
async def call_analytics(
    days: int = Depends(_days_param),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Calls attempted, completed, failed, voicemail, and daily trend."""
    return AnalyticsRepository.call_analytics(db, _org_uuid(tenant), days)


# ---------------------------------------------------------------------------
# LinkedIn analytics
# ---------------------------------------------------------------------------


@router.get("/linkedin", response_model=LinkedInAnalyticsResponse)
async def linkedin_analytics(
    days: int = Depends(_days_param),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """LinkedIn connections sent, messages sent, failures, and daily trend."""
    return AnalyticsRepository.linkedin_analytics(db, _org_uuid(tenant), days)


# ---------------------------------------------------------------------------
# Lead funnel
# ---------------------------------------------------------------------------


@router.get("/funnel", response_model=FunnelResponse)
async def funnel_analytics(
    days: int = Depends(_days_param),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Lead conversion funnel: uploaded → started → emailed → called → qualified → booked."""
    return AnalyticsRepository.funnel(db, _org_uuid(tenant), days)


# ---------------------------------------------------------------------------
# Workflow analytics
# ---------------------------------------------------------------------------


@router.get("/workflow", response_model=WorkflowAnalyticsResponse)
async def workflow_analytics(
    days: int = Depends(_days_param),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Most-used workflows, node type distribution, execution counts."""
    return AnalyticsRepository.workflow_analytics(db, _org_uuid(tenant), days)


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------


@router.get("/meetings", response_model=MeetingsTrendResponse)
async def meetings_trend(
    days: int = Depends(_days_param),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Meetings booked per day, broken down by campaign."""
    return AnalyticsRepository.meetings_trend(db, _org_uuid(tenant), days)


@router.get("/trends", response_model=TrendsResponse)
async def trends(
    days: int = Depends(_days_param),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Executions per day and campaign growth within the date window."""
    return AnalyticsRepository.trends(db, _org_uuid(tenant), days)
