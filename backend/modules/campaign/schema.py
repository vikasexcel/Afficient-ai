"""Request / response schemas for the campaigns API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.campaign.model import ALL_CAMPAIGN_STATUSES


# ---------------------------------------------------------------------------
# Sub-objects (mirror the frontend campaign draft shape)
# ---------------------------------------------------------------------------


class CampaignSchedule(BaseModel):
    """When the campaign should start dialing.

    The frontend collects a local ``date`` + ``time`` + IANA ``timezone``.
    The service converts that to a UTC ``scheduled_at`` for storage.
    """

    start_immediately: bool = True
    date: str | None = None  # "YYYY-MM-DD"
    time: str | None = None  # "HH:mm"
    timezone: str | None = None


class CampaignBusinessHours(BaseModel):
    days: list[str] = Field(default_factory=list)
    start: str = "09:00"
    end: str = "17:00"
    skip_holidays: bool = False


class CampaignRetryConfig(BaseModel):
    """Retry policy consumed by the Retry Execution Engine.

    ``retry_interval_minutes`` + ``backoff_strategy`` are the canonical fields.
    ``backoff_minutes`` is kept (optional) for backward compatibility with
    campaigns persisted before the engine existed; when ``retry_interval_minutes``
    is omitted the engine falls back to it.
    """

    max_attempts: int = Field(default=5, ge=1, le=10)
    retry_interval_minutes: int = Field(default=15, ge=0)
    backoff_strategy: Literal["fixed", "exponential"] = "fixed"

    # Legacy / optional knobs.
    backoff_minutes: int | None = Field(default=None, ge=0)
    retry_on: list[str] | None = None


class CampaignPacing(BaseModel):
    """Throttle how fast the scheduler dials a campaign's leads.

    ``0`` on either field disables that specific limit (unlimited).
    """

    calls_per_hour: int = Field(default=60, ge=0, le=100000)
    max_concurrent_calls: int = Field(default=5, ge=0, le=10000)


class CampaignVoicemailConfig(BaseModel):
    """Answering Machine Detection (AMD) + Voicemail Drop settings.

    When ``voicemail_enabled`` the telephony layer asks the provider to run
    AMD; on a detected voicemail it plays ``voicemail_message_url`` instead of
    running the AI conversation. ``retry_on_voicemail`` decides whether a
    voicemail outcome is retried by the campaign retry engine or marked
    completed. ``amd_unknown_fallback`` chooses the behaviour when detection is
    inconclusive (default: continue the conversation as if human).
    """

    voicemail_enabled: bool = False
    voicemail_message_url: str | None = Field(default=None, max_length=2000)
    retry_on_voicemail: bool = False
    amd_unknown_fallback: Literal["human", "voicemail"] = "human"

    @field_validator("voicemail_message_url")
    @classmethod
    def _v_url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError(
                "voicemail_message_url must be an http(s) URL"
            )
        return v


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


class CreateCampaign(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    playbook_id: uuid.UUID | None = None
    lead_list_id: uuid.UUID | None = None
    schedule: CampaignSchedule | None = None
    business_hours: CampaignBusinessHours | None = None
    retry_config: CampaignRetryConfig | None = None
    pacing: CampaignPacing | None = None
    voicemail_config: CampaignVoicemailConfig | None = None
    # When true the service flips status to ``scheduled``/``active`` based on
    # the schedule instead of leaving the campaign as a ``draft``.
    launch: bool = False


class UpdateCampaign(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    playbook_id: uuid.UUID | None = None
    lead_list_id: uuid.UUID | None = None
    schedule: CampaignSchedule | None = None
    business_hours: CampaignBusinessHours | None = None
    retry_config: CampaignRetryConfig | None = None
    pacing: CampaignPacing | None = None
    voicemail_config: CampaignVoicemailConfig | None = None
    status: str | None = None


class ActivateCampaign(BaseModel):
    campaign_id: str


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    playbook_id: uuid.UUID | None = None
    lead_list_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    timezone: str | None = None
    business_hours: dict | None = None
    retry_config: dict | None = None
    voicemail_config: dict | None = None
    calls_per_hour: int | None = None
    max_concurrent_calls: int | None = None
    created_at: datetime
    updated_at: datetime

    # Enriched, read-only convenience fields for the listing UI.
    playbook_name: str | None = None
    lead_list_name: str | None = None
    lead_count: int | None = None

    model_config = {"from_attributes": True}


class SchedulerStatusOut(BaseModel):
    """Operational health of the Celery campaign call scheduler."""

    worker_running: bool
    beat_running: bool
    redis_connected: bool
    scheduler_online: bool
    queued_executions: int
    queued_execution_count: int
    active_executions: int
    last_scheduler_tick: str | None = None
    last_tick: str | None = None
    last_tick_recent: bool = False
    scheduler_interval_seconds: float = 60.0
    redis_error: str | None = None
    message: str


class CampaignListResponse(BaseModel):
    campaigns: list[CampaignOut]
    total: int


def is_valid_status(status: str) -> bool:
    return status in ALL_CAMPAIGN_STATUSES


# ---------------------------------------------------------------------------
# Workflow graph schemas  (Phase 3A)
# ---------------------------------------------------------------------------

#: Node types recognised by the execution engine.
VALID_NODE_TYPES: frozenset[str] = frozenset(
    {"CALL", "WAIT", "EMAIL", "LINKEDIN", "CONDITION", "STOP"}
)


class WorkflowNodeSchema(BaseModel):
    """A single node in a workflow graph.

    ``type`` is validated against the execution-engine registry.  All
    node-type-specific fields (``subject``, ``body``, ``duration``, ``unit``,
    ``action``, ``message``, ``condition_type``, ``source_node``) are passed
    through as-is via ``extra="allow"`` so the schema remains forward-compatible
    when new node types are added.

    Example nodes::

        {"id": "em_1",   "type": "EMAIL",    "subject": "Hi {{firstName}}", "body": "..."}
        {"id": "wait_1", "type": "WAIT",     "duration": 24, "unit": "hours"}
        {"id": "li_1",   "type": "LINKEDIN", "action": "CONNECT", "message": "..."}
        {"id": "cond_1", "type": "CONDITION","condition_type": "EMAIL_SENT", "source_node": "em_1"}
        {"id": "call_1", "type": "CALL"}
        {"id": "stop_1", "type": "STOP"}
    """

    id: str = Field(min_length=1, max_length=64)
    type: Literal["CALL", "WAIT", "EMAIL", "LINKEDIN", "CONDITION", "STOP"]
    label: str | None = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="allow")

    def to_node_dict(self) -> dict:
        """Return a plain dict for DB storage (includes all extra fields)."""
        return self.model_dump(exclude_none=True)


class WorkflowEdgeSchema(BaseModel):
    """A directed edge between two nodes.

    ``condition`` is only meaningful on edges leaving a CONDITION node:
    ``"TRUE"`` / ``"FALSE"`` (case-insensitive on write; stored upper-cased).

    Example edges::

        {"id": "e1", "source": "em_1",   "target": "wait_1"}
        {"id": "e2", "source": "cond_1", "target": "call_1", "condition": "TRUE"}
        {"id": "e3", "source": "cond_1", "target": "stop_1", "condition": "FALSE"}
    """

    id: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=64)
    condition: str | None = Field(default=None, max_length=16)
    label: str | None = Field(default=None, max_length=128)

    @field_validator("condition", mode="before")
    @classmethod
    def _normalise_condition(cls, v: Any) -> str | None:
        if v is None:
            return None
        upper = str(v).strip().upper()
        if upper not in ("TRUE", "FALSE", ""):
            raise ValueError(
                "edge 'condition' must be 'TRUE', 'FALSE', or null"
            )
        return upper or None

    def to_edge_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


class WorkflowGraphSchema(BaseModel):
    """PUT request body — the complete graph definition for a workflow."""

    nodes: list[WorkflowNodeSchema] = Field(min_length=1)
    edges: list[WorkflowEdgeSchema] = Field(default_factory=list)

    def to_nodes_list(self) -> list[dict]:
        return [n.to_node_dict() for n in self.nodes]

    def to_edges_list(self) -> list[dict]:
        return [e.to_edge_dict() for e in self.edges]


class WorkflowGraphResponse(BaseModel):
    """GET response — the active workflow graph for a campaign."""

    workflow_id: uuid.UUID
    campaign_id: uuid.UUID
    state: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    node_count: int
    edge_count: int
    is_graph: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkflowValidationResponse(BaseModel):
    """POST /validate response — structured validation result."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 3C — Workflow versioning schemas
# ---------------------------------------------------------------------------


class WorkflowVersionSummary(BaseModel):
    """One row in the version history list — no graph payload for brevity."""

    version: int
    workflow_id: uuid.UUID
    created_at: datetime
    created_by: uuid.UUID | None

    model_config = ConfigDict(from_attributes=True)


class WorkflowVersionDetail(BaseModel):
    """Full version snapshot including graph payload."""

    version: int
    workflow_id: uuid.UUID
    nodes: list[Any]
    edges: list[Any]
    created_at: datetime
    created_by: uuid.UUID | None

    model_config = ConfigDict(from_attributes=True)


class WorkflowVersionListResponse(BaseModel):
    """GET /workflow/versions response."""

    workflow_id: uuid.UUID
    versions: list[WorkflowVersionSummary]
    total: int


class WorkflowRestoreResponse(BaseModel):
    """POST /workflow/versions/{version}/restore response."""

    workflow_id: uuid.UUID
    restored_from_version: int
    new_version: int
    nodes: list[Any]
    edges: list[Any]


# ---------------------------------------------------------------------------
# Campaign Monitor payload (Phase 4F)
# ---------------------------------------------------------------------------


class MonitorExecution(BaseModel):
    """Flattened execution + lead row for the monitor dashboard."""

    id: uuid.UUID
    status: str
    lead_id: uuid.UUID | None
    lead_name: str | None
    lead_email: str | None
    lead_phone: str | None
    current_node_id: str | None
    attempt_number: int
    outcome: str | None
    retry_status: str | None
    next_retry_at: datetime | None
    last_failure_reason: str | None
    node_outputs: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class CampaignMonitorPayload(BaseModel):
    """GET /campaigns/{id}/monitor — single dashboard payload."""

    campaign_id: uuid.UUID
    campaign_name: str
    campaign_status: str
    campaign_created_at: datetime
    lead_list_id: uuid.UUID | None
    metrics: dict[str, Any]
    executions: list[MonitorExecution]
    workflow_nodes: list[Any]
    workflow_edges: list[Any]
