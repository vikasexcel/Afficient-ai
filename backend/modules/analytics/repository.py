"""Read-only SQL queries for Phase 5A analytics.

All methods accept an ``org_id`` and optional ``days`` window.  They join
through ``workflows → campaigns`` to enforce tenant isolation on execution
data (executions have no direct ``organization_id`` column).

No writes or mutations are performed here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.campaign.execution_model import Execution
from modules.campaign.model import Campaign
from modules.campaign.workflow_model import Workflow
from modules.leads.model import Lead, LeadActivity

# Call outcomes that represent a connected/completed call (not retryable).
_COMPLETED_CALL_OUTCOMES = frozenset(
    {"qualified", "meeting_booked", "completed", "opted_out", "do_not_call"}
)

# LinkedIn activity types tracked via LeadActivity.
_LI_TYPES = ("li_connect", "li_message", "li_failed")

# Email activity types.
_EMAIL_TYPES = ("email_sent", "email_failed")


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


class AnalyticsRepository:
    """Stateless, read-only analytics query helper."""

    # ------------------------------------------------------------------ #
    # Campaigns
    # ------------------------------------------------------------------ #

    @staticmethod
    def campaign_summary(db: Session, org_id: uuid.UUID) -> dict:
        rows = db.execute(
            select(Campaign.status, func.count(Campaign.id).label("cnt"))
            .where(Campaign.organization_id == org_id)
            .group_by(Campaign.status)
        ).all()
        by_status: dict[str, int] = {r.status: r.cnt for r in rows}
        total = sum(by_status.values())
        return {
            "total": total,
            "active": by_status.get("active", 0),
            "completed": by_status.get("completed", 0),
            "draft": by_status.get("draft", 0),
            "paused": by_status.get("paused", 0),
            "scheduled": by_status.get("scheduled", 0),
            "archived": by_status.get("archived", 0),
        }

    # ------------------------------------------------------------------ #
    # Executions
    # ------------------------------------------------------------------ #

    @staticmethod
    def execution_summary(db: Session, org_id: uuid.UUID, days: int) -> dict:
        since = _since(days)
        rows = db.execute(
            select(Execution.status, func.count(Execution.id).label("cnt"))
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Campaign.organization_id == org_id,
                Execution.created_at >= since,
            )
            .group_by(Execution.status)
        ).all()
        by_status: dict[str, int] = {r.status: r.cnt for r in rows}
        total = sum(by_status.values())
        completed = by_status.get("completed", 0)
        failed = by_status.get("failed", 0)
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": by_status.get("running", 0),
            "queued": by_status.get("queued", 0),
            "completion_rate": round(completed / total * 100, 2) if total else 0.0,
            "failure_rate": round(failed / total * 100, 2) if total else 0.0,
        }

    # ------------------------------------------------------------------ #
    # Leads
    # ------------------------------------------------------------------ #

    @staticmethod
    def lead_summary(db: Session, org_id: uuid.UUID) -> dict:
        rows = db.execute(
            select(Lead.status, func.count(Lead.id).label("cnt"))
            .where(Lead.organization_id == org_id)
            .group_by(Lead.status)
        ).all()
        by_status: dict[str, int] = {r.status: r.cnt for r in rows}
        return {
            "total": sum(by_status.values()),
            "new": by_status.get("new", 0),
            "contacted": by_status.get("contacted", 0),
            "qualified": by_status.get("qualified", 0),
            "converted": by_status.get("converted", 0),
            "lost": by_status.get("lost", 0),
        }

    # ------------------------------------------------------------------ #
    # Email
    # ------------------------------------------------------------------ #

    @staticmethod
    def email_analytics(db: Session, org_id: uuid.UUID, days: int) -> dict:
        since = _since(days)

        totals = db.execute(
            select(LeadActivity.activity_type, func.count(LeadActivity.id).label("cnt"))
            .where(
                LeadActivity.organization_id == org_id,
                LeadActivity.activity_type.in_(_EMAIL_TYPES),
                LeadActivity.created_at >= since,
            )
            .group_by(LeadActivity.activity_type)
        ).all()
        by_type: dict[str, int] = {r.activity_type: r.cnt for r in totals}
        sent = by_type.get("email_sent", 0)
        failed = by_type.get("email_failed", 0)
        total = sent + failed

        trend_rows = db.execute(
            select(
                func.date_trunc("day", LeadActivity.created_at).label("day"),
                LeadActivity.activity_type,
                func.count(LeadActivity.id).label("cnt"),
            )
            .where(
                LeadActivity.organization_id == org_id,
                LeadActivity.activity_type.in_(_EMAIL_TYPES),
                LeadActivity.created_at >= since,
            )
            .group_by(
                func.date_trunc("day", LeadActivity.created_at),
                LeadActivity.activity_type,
            )
            .order_by(func.date_trunc("day", LeadActivity.created_at))
        ).all()

        daily: dict[str, dict[str, int]] = {}
        for row in trend_rows:
            key = row.day.strftime("%Y-%m-%d")
            d = daily.setdefault(key, {"sent": 0, "failed": 0})
            if row.activity_type == "email_sent":
                d["sent"] += row.cnt
            else:
                d["failed"] += row.cnt

        return {
            "sent": sent,
            "failed": failed,
            "success_rate": round(sent / total * 100, 2) if total else 0.0,
            "daily_trend": [
                {"date": k, "sent": v["sent"], "failed": v["failed"]}
                for k, v in sorted(daily.items())
            ],
        }

    # ------------------------------------------------------------------ #
    # Calls
    # ------------------------------------------------------------------ #

    @staticmethod
    def call_analytics(db: Session, org_id: uuid.UUID, days: int) -> dict:
        since = _since(days)

        outcome_rows = db.execute(
            select(
                Execution.outcome,
                func.count(Execution.id).label("cnt"),
            )
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Campaign.organization_id == org_id,
                Execution.outcome.isnot(None),
                Execution.created_at >= since,
            )
            .group_by(Execution.outcome)
        ).all()

        attempted = completed = failed = voicemail = 0
        for row in outcome_rows:
            attempted += row.cnt
            outcome = (row.outcome or "").lower()
            if outcome == "voicemail":
                voicemail += row.cnt
            elif outcome in _COMPLETED_CALL_OUTCOMES:
                completed += row.cnt
            else:
                failed += row.cnt

        trend_rows = db.execute(
            select(
                func.date_trunc("day", Execution.created_at).label("day"),
                Execution.outcome,
                func.count(Execution.id).label("cnt"),
            )
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Campaign.organization_id == org_id,
                Execution.outcome.isnot(None),
                Execution.created_at >= since,
            )
            .group_by(
                func.date_trunc("day", Execution.created_at),
                Execution.outcome,
            )
            .order_by(func.date_trunc("day", Execution.created_at))
        ).all()

        daily: dict[str, dict[str, int]] = {}
        for row in trend_rows:
            key = row.day.strftime("%Y-%m-%d")
            d = daily.setdefault(key, {"attempted": 0, "completed": 0, "voicemail": 0})
            outcome = (row.outcome or "").lower()
            d["attempted"] += row.cnt
            if outcome in _COMPLETED_CALL_OUTCOMES:
                d["completed"] += row.cnt
            elif outcome == "voicemail":
                d["voicemail"] += row.cnt

        return {
            "attempted": attempted,
            "completed": completed,
            "failed": failed,
            "voicemail": voicemail,
            "daily_trend": [
                {
                    "date": k,
                    "attempted": v["attempted"],
                    "completed": v["completed"],
                    "voicemail": v["voicemail"],
                }
                for k, v in sorted(daily.items())
            ],
        }

    # ------------------------------------------------------------------ #
    # LinkedIn
    # ------------------------------------------------------------------ #

    @staticmethod
    def linkedin_analytics(db: Session, org_id: uuid.UUID, days: int) -> dict:
        since = _since(days)

        totals = db.execute(
            select(LeadActivity.activity_type, func.count(LeadActivity.id).label("cnt"))
            .where(
                LeadActivity.organization_id == org_id,
                LeadActivity.activity_type.in_(_LI_TYPES),
                LeadActivity.created_at >= since,
            )
            .group_by(LeadActivity.activity_type)
        ).all()
        by_type: dict[str, int] = {r.activity_type: r.cnt for r in totals}

        trend_rows = db.execute(
            select(
                func.date_trunc("day", LeadActivity.created_at).label("day"),
                LeadActivity.activity_type,
                func.count(LeadActivity.id).label("cnt"),
            )
            .where(
                LeadActivity.organization_id == org_id,
                LeadActivity.activity_type.in_(_LI_TYPES),
                LeadActivity.created_at >= since,
            )
            .group_by(
                func.date_trunc("day", LeadActivity.created_at),
                LeadActivity.activity_type,
            )
            .order_by(func.date_trunc("day", LeadActivity.created_at))
        ).all()

        daily: dict[str, dict[str, int]] = {}
        for row in trend_rows:
            key = row.day.strftime("%Y-%m-%d")
            d = daily.setdefault(key, {"connections": 0, "messages": 0, "failed": 0})
            if row.activity_type == "li_connect":
                d["connections"] += row.cnt
            elif row.activity_type == "li_message":
                d["messages"] += row.cnt
            elif row.activity_type == "li_failed":
                d["failed"] += row.cnt

        return {
            "connections_sent": by_type.get("li_connect", 0),
            "messages_sent": by_type.get("li_message", 0),
            "failed": by_type.get("li_failed", 0),
            "daily_trend": [
                {
                    "date": k,
                    "connections": v["connections"],
                    "messages": v["messages"],
                    "failed": v["failed"],
                }
                for k, v in sorted(daily.items())
            ],
        }

    # ------------------------------------------------------------------ #
    # Funnel
    # ------------------------------------------------------------------ #

    @staticmethod
    def funnel(db: Session, org_id: uuid.UUID, days: int) -> dict:
        since = _since(days)

        uploaded = db.execute(
            select(func.count(Lead.id)).where(Lead.organization_id == org_id)
        ).scalar_one() or 0

        workflow_started = db.execute(
            select(func.count(func.distinct(Execution.lead_id)))
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Campaign.organization_id == org_id,
                Execution.lead_id.isnot(None),
                Execution.created_at >= since,
            )
        ).scalar_one() or 0

        email_sent = db.execute(
            select(func.count(func.distinct(LeadActivity.lead_id)))
            .where(
                LeadActivity.organization_id == org_id,
                LeadActivity.activity_type == "email_sent",
                LeadActivity.created_at >= since,
            )
        ).scalar_one() or 0

        call_connected = db.execute(
            select(func.count(func.distinct(Execution.lead_id)))
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Campaign.organization_id == org_id,
                Execution.outcome.in_(
                    ["qualified", "meeting_booked", "completed"]
                ),
                Execution.lead_id.isnot(None),
                Execution.created_at >= since,
            )
        ).scalar_one() or 0

        qualified = db.execute(
            select(func.count(Lead.id))
            .where(
                Lead.organization_id == org_id,
                Lead.status == "qualified",
            )
        ).scalar_one() or 0

        meeting_booked = db.execute(
            select(func.count(func.distinct(Execution.lead_id)))
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Campaign.organization_id == org_id,
                Execution.outcome == "meeting_booked",
                Execution.lead_id.isnot(None),
                Execution.created_at >= since,
            )
        ).scalar_one() or 0

        steps = [
            ("Lead Uploaded", int(uploaded)),
            ("Workflow Started", int(workflow_started)),
            ("Email Sent", int(email_sent)),
            ("Call Connected", int(call_connected)),
            ("Qualified", int(qualified)),
            ("Meeting Booked", int(meeting_booked)),
        ]
        top = steps[0][1] or 1
        return {
            "steps": [
                {"label": label, "count": count, "pct": round(count / top * 100, 1)}
                for label, count in steps
            ]
        }

    # ------------------------------------------------------------------ #
    # Workflow analytics
    # ------------------------------------------------------------------ #

    @staticmethod
    def workflow_analytics(db: Session, org_id: uuid.UUID, days: int) -> dict:
        since = _since(days)

        wf_rows = db.execute(
            select(
                Workflow.id,
                Campaign.id.label("campaign_id"),
                Campaign.name.label("campaign_name"),
                func.count(Execution.id).label("execution_count"),
            )
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .join(Execution, Execution.workflow_id == Workflow.id)
            .where(
                Campaign.organization_id == org_id,
                Execution.created_at >= since,
            )
            .group_by(Workflow.id, Campaign.id, Campaign.name)
            .order_by(func.count(Execution.id).desc())
            .limit(5)
        ).all()

        most_used = [
            {
                "workflow_id": str(r.id),
                "campaign_id": str(r.campaign_id),
                "campaign_name": r.campaign_name,
                "execution_count": r.execution_count,
            }
            for r in wf_rows
        ]

        # Node type distribution — fetch workflow node arrays and aggregate in Python.
        node_rows = db.execute(
            select(Workflow.nodes)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(Campaign.organization_id == org_id)
        ).all()

        node_counts: dict[str, int] = {}
        for row in node_rows:
            for node in (row.nodes or []):
                ntype = node.get("type", "unknown") if isinstance(node, dict) else "unknown"
                node_counts[ntype] = node_counts.get(ntype, 0) + 1

        node_dist = sorted(
            [{"node_type": k, "count": v} for k, v in node_counts.items()],
            key=lambda x: -x["count"],
        )

        total_exec = db.execute(
            select(func.count(Execution.id))
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Campaign.organization_id == org_id,
                Execution.created_at >= since,
            )
        ).scalar_one() or 0

        total_wf = db.execute(
            select(func.count(Workflow.id))
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(Campaign.organization_id == org_id)
        ).scalar_one() or 0

        return {
            "most_used_workflows": most_used,
            "node_type_distribution": node_dist,
            "total_workflows": int(total_wf),
            "total_executions_in_period": int(total_exec),
        }

    # ------------------------------------------------------------------ #
    # Meetings booked trend
    # ------------------------------------------------------------------ #

    @staticmethod
    def meetings_trend(db: Session, org_id: uuid.UUID, days: int) -> dict:
        since = _since(days)

        rows = db.execute(
            select(
                func.date_trunc("day", Execution.created_at).label("day"),
                Campaign.id.label("campaign_id"),
                Campaign.name.label("campaign_name"),
                func.count(Execution.id).label("cnt"),
            )
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Campaign.organization_id == org_id,
                Execution.outcome == "meeting_booked",
                Execution.lead_id.isnot(None),
                Execution.created_at >= since,
            )
            .group_by(
                func.date_trunc("day", Execution.created_at),
                Campaign.id,
                Campaign.name,
            )
            .order_by(func.date_trunc("day", Execution.created_at))
        ).all()

        # Aggregate into {date: {campaign_id: {name, count}}}
        daily: dict[str, dict[str, dict]] = {}
        for row in rows:
            key = row.day.strftime("%Y-%m-%d")
            if key not in daily:
                daily[key] = {}
            cid = str(row.campaign_id)
            if cid not in daily[key]:
                daily[key][cid] = {"name": row.campaign_name, "count": 0}
            daily[key][cid]["count"] += row.cnt

        result = []
        grand_total = 0
        for date, campaigns in sorted(daily.items()):
            day_total = sum(v["count"] for v in campaigns.values())
            grand_total += day_total
            result.append({
                "date": date,
                "total": day_total,
                "by_campaign": [
                    {"campaign_id": cid, "campaign_name": v["name"], "count": v["count"]}
                    for cid, v in campaigns.items()
                ],
            })

        return {"total": grand_total, "daily": result}

    # ------------------------------------------------------------------ #
    # Trends
    # ------------------------------------------------------------------ #

    @staticmethod
    def trends(db: Session, org_id: uuid.UUID, days: int) -> dict:
        since = _since(days)

        exec_rows = db.execute(
            select(
                func.date_trunc("day", Execution.created_at).label("day"),
                Execution.status,
                func.count(Execution.id).label("cnt"),
            )
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Campaign.organization_id == org_id,
                Execution.created_at >= since,
            )
            .group_by(
                func.date_trunc("day", Execution.created_at),
                Execution.status,
            )
            .order_by(func.date_trunc("day", Execution.created_at))
        ).all()

        exec_daily: dict[str, dict[str, int]] = {}
        for row in exec_rows:
            key = row.day.strftime("%Y-%m-%d")
            d = exec_daily.setdefault(key, {"total": 0, "completed": 0, "failed": 0})
            d["total"] += row.cnt
            if row.status == "completed":
                d["completed"] += row.cnt
            elif row.status == "failed":
                d["failed"] += row.cnt

        camp_rows = db.execute(
            select(
                func.date_trunc("day", Campaign.created_at).label("day"),
                func.count(Campaign.id).label("cnt"),
            )
            .where(
                Campaign.organization_id == org_id,
                Campaign.created_at >= since,
            )
            .group_by(func.date_trunc("day", Campaign.created_at))
            .order_by(func.date_trunc("day", Campaign.created_at))
        ).all()

        return {
            "executions_per_day": [
                {"date": k, "total": v["total"], "completed": v["completed"], "failed": v["failed"]}
                for k, v in sorted(exec_daily.items())
            ],
            "campaign_growth": [
                {"date": r.day.strftime("%Y-%m-%d"), "count": r.cnt}
                for r in camp_rows
            ],
        }
