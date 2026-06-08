"""Pydantic response schemas for the Analytics module (Phase 5A).

All models are read-only — no mutation payloads are defined here.
"""

from __future__ import annotations

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class DailyDataPoint(BaseModel):
    date: str
    count: int


class DailyEmailPoint(BaseModel):
    date: str
    sent: int
    failed: int


class DailyCallPoint(BaseModel):
    date: str
    attempted: int
    completed: int
    voicemail: int


class DailyLinkedInPoint(BaseModel):
    date: str
    connections: int
    messages: int
    failed: int


class DailyExecutionPoint(BaseModel):
    date: str
    total: int
    completed: int
    failed: int


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class CampaignSummary(BaseModel):
    total: int
    active: int
    completed: int
    draft: int
    paused: int
    scheduled: int
    archived: int


class ExecutionSummary(BaseModel):
    total: int
    completed: int
    failed: int
    running: int
    queued: int
    completion_rate: float
    failure_rate: float


class LeadSummary(BaseModel):
    total: int
    new: int
    contacted: int
    qualified: int
    converted: int
    lost: int


class OverviewResponse(BaseModel):
    campaigns: CampaignSummary
    executions: ExecutionSummary
    leads: LeadSummary
    total_leads_processed: int


# ---------------------------------------------------------------------------
# Channel analytics
# ---------------------------------------------------------------------------


class EmailAnalyticsResponse(BaseModel):
    sent: int
    failed: int
    success_rate: float
    daily_trend: list[DailyEmailPoint]


class CallAnalyticsResponse(BaseModel):
    attempted: int
    completed: int
    failed: int
    voicemail: int
    daily_trend: list[DailyCallPoint]


class LinkedInAnalyticsResponse(BaseModel):
    connections_sent: int
    messages_sent: int
    failed: int
    daily_trend: list[DailyLinkedInPoint]


# ---------------------------------------------------------------------------
# Funnel
# ---------------------------------------------------------------------------


class FunnelStep(BaseModel):
    label: str
    count: int
    pct: float


class FunnelResponse(BaseModel):
    steps: list[FunnelStep]


# ---------------------------------------------------------------------------
# Workflow analytics
# ---------------------------------------------------------------------------


class WorkflowUsageStat(BaseModel):
    workflow_id: str
    campaign_id: str
    campaign_name: str
    execution_count: int


class NodeTypeStat(BaseModel):
    node_type: str
    count: int


class WorkflowAnalyticsResponse(BaseModel):
    most_used_workflows: list[WorkflowUsageStat]
    node_type_distribution: list[NodeTypeStat]
    total_workflows: int
    total_executions_in_period: int


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------


class TrendsResponse(BaseModel):
    executions_per_day: list[DailyExecutionPoint]
    campaign_growth: list[DailyDataPoint]
