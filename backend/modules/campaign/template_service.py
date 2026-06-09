"""Business logic for workflow templates.

``WorkflowTemplateService`` is the single entry-point for all template
operations.  It delegates data access to
:class:`~modules.campaign.template_repository.WorkflowTemplateRepository` and
graph validation to
:meth:`~modules.campaign.workflow_service.WorkflowService.validate_graph_detailed`.

System template seeding
-----------------------
:meth:`seed_system_templates` is idempotent — it skips templates whose
well-known UUIDs already exist in the database.  It can be called:

* During ``alembic upgrade`` (via the data migration).
* On application startup as a safety net.
* In tests to pre-populate the template table.

The 5 built-in templates mirror the seed rows inserted by the migration in
``q3r4s5t6u7v8_create_workflow_templates``.  If you add a template here,
also add a corresponding row in the migration so freshly-deployed instances
get the data.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from common.logging import get_logger
from modules.campaign.template_model import WorkflowTemplate
from modules.campaign.template_repository import WorkflowTemplateRepository
from modules.campaign.workflow_service import WorkflowService

log = get_logger("campaign.template_service")


# ---------------------------------------------------------------------------
# Built-in system template definitions
#
# Keyed by their stable UUIDs so seed_system_templates can upsert safely.
# Any change here must be reflected in the Alembic migration as well.
# ---------------------------------------------------------------------------

SYSTEM_TEMPLATES: list[dict] = [
    {
        "id": "00000000-0001-0000-0000-000000000001",
        "name": "Cold Outreach",
        "description": (
            "Combines an initial call with a follow-up email for cold leads. "
            "Waits 24 hours after the call before sending the email."
        ),
        "category": "cold-outreach",
        "nodes": [
            {"id": "call_1",  "type": "CALL",  "label": "Initial call"},
            {"id": "wait_1",  "type": "WAIT",  "label": "Wait 24 h",
             "duration": 24, "unit": "hours"},
            {"id": "email_1", "type": "EMAIL", "label": "Follow-up email",
             "subject": "Following up on our call",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "I wanted to follow up after our conversation earlier. "
                 "Would you have 15 minutes this week to connect?\n\n"
                 "Best,\nThe Team"
             )},
            {"id": "stop_1",  "type": "STOP",  "label": "Done"},
        ],
        "edges": [
            {"id": "e1", "source": "call_1",  "target": "wait_1"},
            {"id": "e2", "source": "wait_1",  "target": "email_1"},
            {"id": "e3", "source": "email_1", "target": "stop_1"},
        ],
    },
    {
        "id": "00000000-0002-0000-0000-000000000002",
        "name": "Follow-Up Sequence",
        "description": (
            "Sends two emails spaced 48 hours apart. If the second email is "
            "delivered, a call is placed to engaged leads. Undelivered leads "
            "are stopped."
        ),
        "category": "follow-up",
        "nodes": [
            {"id": "email_1", "type": "EMAIL", "label": "First email",
             "subject": "Reaching out — {{company}}",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "I came across {{company}} and thought we could help. "
                 "Open to a quick chat?\n\nBest,\nThe Team"
             )},
            {"id": "wait_1",  "type": "WAIT",  "label": "Wait 48 h",
             "duration": 48, "unit": "hours"},
            {"id": "email_2", "type": "EMAIL", "label": "Follow-up email",
             "subject": "Re: Reaching out — {{company}}",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "Just following up in case my earlier message got buried. "
                 "Happy to share some ideas that have worked for similar "
                 "companies like {{company}}.\n\nBest,\nThe Team"
             )},
            {"id": "cond_1",  "type": "CONDITION", "label": "Email delivered?",
             "condition_type": "EMAIL_SENT", "source_node": "email_2"},
            {"id": "call_1",  "type": "CALL",  "label": "Call engaged leads"},
            {"id": "stop_1",  "type": "STOP",  "label": "Done"},
        ],
        "edges": [
            {"id": "e1", "source": "email_1", "target": "wait_1"},
            {"id": "e2", "source": "wait_1",  "target": "email_2"},
            {"id": "e3", "source": "email_2", "target": "cond_1"},
            {"id": "e4", "source": "cond_1",  "target": "call_1",
             "condition": "TRUE"},
            {"id": "e5", "source": "cond_1",  "target": "stop_1",
             "condition": "FALSE"},
        ],
    },
    {
        "id": "00000000-0003-0000-0000-000000000003",
        "name": "LinkedIn Outreach",
        "description": (
            "Sends a LinkedIn connection request, waits one day for acceptance, "
            "then follows up with a direct message."
        ),
        "category": "linkedin",
        "nodes": [
            {"id": "li_connect", "type": "LINKEDIN", "label": "Send connection",
             "action": "CONNECT",
             "message": (
                 "Hi {{firstName}}, I noticed your work at {{company}} and "
                 "thought it would be great to connect."
             )},
            {"id": "wait_1",    "type": "WAIT",     "label": "Wait 1 day",
             "duration": 1, "unit": "days"},
            {"id": "li_msg",    "type": "LINKEDIN", "label": "Send message",
             "action": "MESSAGE",
             "message": (
                 "Hi {{firstName}}, thanks for connecting! I'd love to share "
                 "how we've been helping {{jobTitle}}s at companies like "
                 "{{company}}. Would you be open to a quick chat?"
             )},
            {"id": "stop_1",    "type": "STOP",     "label": "Done"},
        ],
        "edges": [
            {"id": "e1", "source": "li_connect", "target": "wait_1"},
            {"id": "e2", "source": "wait_1",     "target": "li_msg"},
            {"id": "e3", "source": "li_msg",     "target": "stop_1"},
        ],
    },
    {
        "id": "00000000-0004-0000-0000-000000000004",
        "name": "Qualification",
        "description": (
            "Emails a lead, waits one day, then places a qualification call. "
            "If the call connects the lead is qualified. Otherwise a "
            "missed-call email is sent before closing."
        ),
        "category": "qualification",
        "nodes": [
            {"id": "email_1", "type": "EMAIL",  "label": "Intro email",
             "subject": "Quick question about {{company}}",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "I have a quick question about your current setup at "
                 "{{company}}. I'll give you a call tomorrow — hope that's OK!"
                 "\n\nBest,\nThe Team"
             )},
            {"id": "wait_1",  "type": "WAIT",   "label": "Wait 1 day",
             "duration": 1, "unit": "days"},
            {"id": "call_1",  "type": "CALL",   "label": "Qualification call"},
            {"id": "cond_1",  "type": "CONDITION", "label": "Call connected?",
             "condition_type": "CALL_COMPLETED", "source_node": "call_1"},
            {"id": "stop_1",  "type": "STOP",   "label": "Qualified"},
            {"id": "email_2", "type": "EMAIL",  "label": "Missed-call email",
             "subject": "Sorry I missed you",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "I tried to reach you today but missed you. "
                 "Feel free to reply with a good time to connect.\n\n"
                 "Best,\nThe Team"
             )},
            {"id": "stop_2",  "type": "STOP",   "label": "Done"},
        ],
        "edges": [
            {"id": "e1", "source": "email_1", "target": "wait_1"},
            {"id": "e2", "source": "wait_1",  "target": "call_1"},
            {"id": "e3", "source": "call_1",  "target": "cond_1"},
            {"id": "e4", "source": "cond_1",  "target": "stop_1",
             "condition": "TRUE"},
            {"id": "e5", "source": "cond_1",  "target": "email_2",
             "condition": "FALSE"},
            {"id": "e6", "source": "email_2", "target": "stop_2"},
        ],
    },
    {
        "id": "00000000-0006-0000-0000-000000000006",
        "name": "Email Reply → Call Follow-Up",
        "description": (
            "Sends an email and waits 5 minutes. If the recipient replies "
            "within the window, an immediate call is placed to the configured "
            "phone number. If no reply arrives, the workflow stops."
        ),
        "category": "email-reply-call",
        "nodes": [
            {"id": "email_1",  "type": "EMAIL",     "label": "Send email",
             "subject": "Quick question, {{firstName}}",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "I wanted to reach out with a quick question about "
                 "{{company}}. Could you reply to this email at your "
                 "earliest convenience?\n\n"
                 "Best,\nThe Team"
             )},
            {"id": "wait_1",   "type": "WAIT",      "label": "Wait 5 minutes",
             "duration": 5, "unit": "minutes"},
            {"id": "cond_1",   "type": "CONDITION", "label": "Replied within 5 min?",
             "condition_type": "EMAIL_REPLIED", "source_node": "email_1",
             "window_minutes": 5},
            {"id": "call_1",   "type": "CALL",      "label": "Call follow-up",
             "to_number": "+917541006707"},
            {"id": "stop_1",   "type": "STOP",      "label": "Call placed"},
            {"id": "stop_2",   "type": "STOP",      "label": "No reply — stopped"},
        ],
        "edges": [
            {"id": "e1", "source": "email_1", "target": "wait_1"},
            {"id": "e2", "source": "wait_1",  "target": "cond_1"},
            {"id": "e3", "source": "cond_1",  "target": "call_1",
             "condition": "TRUE"},
            {"id": "e4", "source": "cond_1",  "target": "stop_2",
             "condition": "FALSE"},
            {"id": "e5", "source": "call_1",  "target": "stop_1"},
        ],
    },
    {
        "id": "00000000-0005-0000-0000-000000000005",
        "name": "Demo Booking",
        "description": (
            "Invites a lead to a demo via email, then follows up with a call "
            "one day later. Booked leads are stopped immediately; unbooked "
            "leads receive a final email after two more days."
        ),
        "category": "demo-booking",
        "nodes": [
            {"id": "email_1", "type": "EMAIL",  "label": "Demo invite",
             "subject": "{{firstName}}, want to see what we've built?",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "I'd love to show you a quick demo of what we've built for "
                 "teams like yours at {{company}}. Takes just 20 minutes.\n\n"
                 "I'll follow up with a call — would that be OK?\n\n"
                 "Best,\nThe Team"
             )},
            {"id": "wait_1",  "type": "WAIT",   "label": "Wait 1 day",
             "duration": 1, "unit": "days"},
            {"id": "call_1",  "type": "CALL",   "label": "Book demo call"},
            {"id": "cond_1",  "type": "CONDITION", "label": "Demo booked?",
             "condition_type": "CALL_COMPLETED", "source_node": "call_1"},
            {"id": "stop_1",  "type": "STOP",   "label": "Demo booked"},
            {"id": "wait_2",  "type": "WAIT",   "label": "Wait 2 days",
             "duration": 2, "unit": "days"},
            {"id": "email_2", "type": "EMAIL",  "label": "Final follow-up",
             "subject": "Last chance — {{firstName}}",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "This is my last outreach. If you'd ever like to see a demo "
                 "just reply to this email.\n\nBest,\nThe Team"
             )},
            {"id": "stop_2",  "type": "STOP",   "label": "Done"},
        ],
        "edges": [
            {"id": "e1", "source": "email_1", "target": "wait_1"},
            {"id": "e2", "source": "wait_1",  "target": "call_1"},
            {"id": "e3", "source": "call_1",  "target": "cond_1"},
            {"id": "e4", "source": "cond_1",  "target": "stop_1",
             "condition": "TRUE"},
            {"id": "e5", "source": "cond_1",  "target": "wait_2",
             "condition": "FALSE"},
            {"id": "e6", "source": "wait_2",  "target": "email_2"},
            {"id": "e7", "source": "email_2", "target": "stop_2"},
        ],
    },
]


class WorkflowTemplateService:

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    @staticmethod
    def create_template(
        db: Session,
        *,
        org_id: uuid.UUID,
        name: str,
        description: str | None = None,
        category: str | None = None,
        nodes: list,
        edges: list,
    ) -> WorkflowTemplate:
        """Create a new org-owned template after validating the graph.

        Raises :class:`ValueError` when the graph fails validation.
        """
        errors, _ = WorkflowService.validate_graph_detailed(nodes, edges)
        if errors:
            raise ValueError(errors[0])

        template = WorkflowTemplate(
            organization_id=org_id,
            name=name,
            description=description,
            category=category,
            is_system=False,
            nodes=nodes,
            edges=edges,
        )
        WorkflowTemplateRepository.create(db, template)
        log.info(
            "template.created",
            template_id=str(template.id),
            org_id=str(org_id),
            name=name,
        )
        return template

    @staticmethod
    def get_template(
        db: Session,
        template_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> WorkflowTemplate | None:
        """Return template *template_id* if visible to *org_id*."""
        return WorkflowTemplateRepository.get(db, template_id, org_id)

    @staticmethod
    def list_templates(
        db: Session,
        org_id: uuid.UUID,
        *,
        category: str | None = None,
    ) -> list[WorkflowTemplate]:
        """Return all templates visible to *org_id* (system + org-owned)."""
        return WorkflowTemplateRepository.list(
            db, org_id, category=category, include_system=True
        )

    @staticmethod
    def clone_template(
        db: Session,
        template_id: uuid.UUID,
        org_id: uuid.UUID,
        *,
        name: str | None = None,
    ) -> WorkflowTemplate:
        """Clone *template_id* into an org-owned copy.

        Raises :class:`LookupError` when *template_id* is not found or not
        accessible to *org_id*.
        """
        source = WorkflowTemplateRepository.get(db, template_id, org_id)
        if source is None:
            raise LookupError(f"template {template_id} not found")

        clone = WorkflowTemplateRepository.clone(
            db, source, org_id=org_id, name=name
        )
        log.info(
            "template.cloned",
            source_id=str(source.id),
            clone_id=str(clone.id),
            org_id=str(org_id),
            name=clone.name,
        )
        return clone

    # ------------------------------------------------------------------ #
    # Seeding
    # ------------------------------------------------------------------ #

    @staticmethod
    def seed_system_templates(db: Session) -> int:
        """Insert any missing system templates.  Returns the number inserted.

        Idempotent — skips templates whose UUIDs already exist.
        """
        inserted = 0
        for defn in SYSTEM_TEMPLATES:
            tid = uuid.UUID(defn["id"])
            existing = WorkflowTemplateRepository.get(db, tid, org_id=None)
            if existing is not None:
                continue

            template = WorkflowTemplate(
                id=tid,
                organization_id=None,
                name=defn["name"],
                description=defn.get("description"),
                category=defn.get("category"),
                is_system=True,
                nodes=defn["nodes"],
                edges=defn["edges"],
            )
            WorkflowTemplateRepository.create(db, template)
            inserted += 1

        if inserted:
            db.commit()
            log.info("template.seed_complete", inserted=inserted)
        return inserted
