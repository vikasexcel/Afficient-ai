#!/usr/bin/env python3
"""Dry-run the Email Reply -> Call Follow-Up workflow.

This script creates temporary DB rows, simulates a positive email reply, and
runs the real campaign worker. External telephony is mocked at the HTTP
dispatch boundary, so no real call is placed.

Run from the backend directory:
    python scripts/simulate_email_reply_call.py

Optional:
    python scripts/simulate_email_reply_call.py \
        --playbook-id <uuid> \
        --to-number +917541006707
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database.models  # noqa: F401 - register ORM models
from database.session import SessionLocal
from modules.campaign.execution_model import Execution
from modules.campaign.model import Campaign
from modules.campaign.workflow_model import Workflow
from modules.campaign.worker import run_execution
from modules.leads.model import Lead, LeadActivity
from modules.playbook.model import PLAYBOOK_STATUS_ACTIVE, Playbook


@dataclass
class FakeResponse:
    body: dict[str, Any]

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.body


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _parse_uuid(value: str | None, *, label: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise SystemExit(f"{label} must be a UUID, got: {value}") from exc


def _find_playbook(db, playbook_id: uuid.UUID | None, org_id: uuid.UUID | None) -> Playbook:
    query = db.query(Playbook)
    if playbook_id:
        playbook = query.filter(Playbook.id == playbook_id).first()
        if playbook is None:
            raise SystemExit(f"No playbook found for id {playbook_id}")
        return playbook

    if org_id:
        query = query.filter(Playbook.organization_id == org_id)

    playbook = (
        query.filter(Playbook.status == PLAYBOOK_STATUS_ACTIVE)
        .order_by(Playbook.created_at.desc())
        .first()
    )
    if playbook is None:
        raise SystemExit(
            "No active playbook found. Re-run with --playbook-id <uuid> "
            "for a published/active playbook."
        )
    return playbook


def _fake_http_post_factory(captured: dict[str, Any]):
    def _fake_http_post(url, *, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "id": str(uuid.uuid4()),
                "call_sid": None,
                "room_name": f"sim-room-{uuid.uuid4().hex[:8]}",
                "status": "initiated",
            }
        )

    return _fake_http_post


async def _run(args: argparse.Namespace) -> int:
    import modules.campaign.worker as worker

    playbook_arg = _parse_uuid(args.playbook_id, label="--playbook-id")
    org_arg = _parse_uuid(args.org_id, label="--org-id")
    to_number = args.to_number.strip()

    captured: dict[str, Any] = {}
    original_http_post = worker.httpx.post
    original_dialing = worker.settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED
    original_http_dispatch = worker.settings.CAMPAIGN_DISPATCH_VIA_HTTP
    created: dict[str, uuid.UUID | None] = {
        "execution_id": None,
        "workflow_id": None,
        "campaign_id": None,
        "lead_id": None,
    }

    db = SessionLocal()
    try:
        playbook = _find_playbook(db, playbook_arg, org_arg)
        org_id = org_arg or playbook.organization_id

        suffix = random.randint(100000, 999999)
        lead_phone = f"+141555{suffix}"
        lead = Lead(
            organization_id=org_id,
            first_name="Simulation",
            last_name="Lead",
            email=f"simulation.{uuid.uuid4().hex[:8]}@example.com",
            phone=lead_phone,
            phone_normalized=_digits(lead_phone),
            company="Simulation Co",
            job_title="Buyer",
        )
        db.add(lead)
        db.flush()
        created["lead_id"] = lead.id

        campaign = Campaign(
            organization_id=org_id,
            name=f"Sim Email Reply Call {uuid.uuid4().hex[:8]}",
            status="active",
            playbook_id=None,
        )
        db.add(campaign)
        db.flush()
        created["campaign_id"] = campaign.id

        nodes = [
            {
                "id": "cond_1",
                "type": "CONDITION",
                "condition_type": "EMAIL_REPLIED",
                "source_node": "email_1",
            },
            {
                "id": "call_1",
                "type": "CALL",
                "config": {
                    "playbook_id": str(playbook.id),
                    "to_number": to_number,
                },
            },
        ]
        edges = [
            {
                "id": "e1",
                "source": "cond_1",
                "target": "call_1",
                "condition": "TRUE",
            },
        ]
        workflow = Workflow(
            campaign_id=campaign.id,
            state="active",
            nodes=nodes,
            edges=edges,
        )
        db.add(workflow)
        db.flush()
        created["workflow_id"] = workflow.id

        execution = Execution(
            workflow_id=workflow.id,
            lead_id=lead.id,
            status="queued",
            current_node_id="cond_1",
            node_outputs={
                "email_1": {
                    "sent": True,
                    "to": lead.email,
                    "sent_at": "2026-06-10T07:00:00+00:00",
                    "message_id": f"<{uuid.uuid4()}@simulation.local>",
                    "replied": True,
                    "within_window": True,
                    "match_method": "webhook",
                    "reply_subject": "Re: quick question",
                    "reply_body": "Yes, please call me.",
                }
            },
            context={
                "campaign_id": str(campaign.id),
                "playbook_id": str(campaign.playbook_id),
                "org_id": str(org_id),
                "lead": {
                    "id": str(lead.id),
                    "organization_id": str(org_id),
                    "name": "Simulation Lead",
                    "first_name": lead.first_name,
                    "last_name": lead.last_name,
                    "phone": lead.phone,
                    "email": lead.email,
                    "company": lead.company,
                    "job_title": lead.job_title,
                },
            },
        )
        db.add(execution)
        db.commit()
        created["execution_id"] = execution.id

        worker.settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED = True
        worker.settings.CAMPAIGN_DISPATCH_VIA_HTTP = True
        worker.httpx.post = _fake_http_post_factory(captured)

        await run_execution(db, execution)
        db.refresh(execution)

        payload = captured.get("json") or {}
        checks = {
            "execution_running": execution.status == "running",
            "condition_routed_to_call": execution.current_node_id == "call_1",
            "http_dispatch_attempted": bool(captured.get("url")),
            "call_node_phone_used": payload.get("to_number") == to_number,
            "call_node_playbook_used": payload.get("playbook_id") == str(playbook.id),
            "execution_id_sent": payload.get("execution_id") == str(execution.id),
            "telephony_call_id_saved": bool((execution.context or {}).get("telephony_call_id")),
        }
        passed = all(checks.values())

        print("\nEmail Reply -> Call simulation")
        print("=" * 33)
        print(f"Result: {'PASS' if passed else 'FAIL'}")
        print(f"Organization: {org_id}")
        print(f"Playbook: {playbook.id} ({playbook.name})")
        print(f"Campaign playbook_id: {campaign.playbook_id}")
        print(f"CALL node to_number: {to_number}")
        print(f"Lead phone: {lead.phone}")
        print(f"Execution: {execution.id}")
        print("\nChecks:")
        for name, ok in checks.items():
            print(f"  {'PASS' if ok else 'FAIL'} {name}")
        print("\nCaptured HTTP dispatch payload:")
        print(json.dumps(payload, indent=2, sort_keys=True))

        return 0 if passed else 1
    finally:
        worker.httpx.post = original_http_post
        worker.settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED = original_dialing
        worker.settings.CAMPAIGN_DISPATCH_VIA_HTTP = original_http_dispatch

        if not args.keep:
            try:
                db.rollback()
                if created["lead_id"]:
                    db.query(LeadActivity).filter(
                        LeadActivity.lead_id == created["lead_id"]
                    ).delete(synchronize_session=False)
                if created["execution_id"]:
                    db.query(Execution).filter(
                        Execution.id == created["execution_id"]
                    ).delete(synchronize_session=False)
                    db.flush()
                if created["workflow_id"]:
                    db.query(Workflow).filter(
                        Workflow.id == created["workflow_id"]
                    ).delete(synchronize_session=False)
                    db.flush()
                if created["campaign_id"]:
                    db.query(Campaign).filter(
                        Campaign.id == created["campaign_id"]
                    ).delete(synchronize_session=False)
                    db.flush()
                if created["lead_id"]:
                    db.query(Lead).filter(
                        Lead.id == created["lead_id"]
                    ).delete(synchronize_session=False)
                db.commit()
            except Exception as exc:
                db.rollback()
                print(f"\nCleanup warning: {exc}")
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run the Email Reply -> Call Follow-Up workflow."
    )
    parser.add_argument("--playbook-id", help="Active playbook UUID to use.")
    parser.add_argument("--org-id", help="Organization UUID. Defaults to playbook org.")
    parser.add_argument(
        "--to-number",
        default="+917541006707",
        help="CALL node phone override to verify.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep temporary DB rows for manual inspection.",
    )
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
