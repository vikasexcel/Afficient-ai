"""Phase 3B — create workflow_templates table and seed system templates

Revision ID: q3r4s5t6u7v8
Revises: p1q2r3s4t5u6
Create Date: 2026-06-06

Changes
-------
* Creates ``workflow_templates`` table with all columns defined in
  :class:`~modules.campaign.template_model.WorkflowTemplate`.
* Inserts the 5 built-in system templates (Cold Outreach, Follow-Up Sequence,
  LinkedIn Outreach, Qualification, Demo Booking).  System templates have
  ``is_system=true`` and ``organization_id=NULL``; they are visible to all
  organisations and cannot be mutated via the API.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "q3r4s5t6u7v8"
down_revision: str = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Seed data — kept inline so the migration is self-contained and doesn't
# couple to service-layer imports (which may change across schema versions).
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SYSTEM_TEMPLATES = [
    # ── 1. Cold Outreach ────────────────────────────────────────────
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
    # ── 2. Follow-Up Sequence ───────────────────────────────────────
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
                 "Open to a quick chat?\n\n"
                 "Best,\nThe Team"
             )},
            {"id": "wait_1",  "type": "WAIT",  "label": "Wait 48 h",
             "duration": 48, "unit": "hours"},
            {"id": "email_2", "type": "EMAIL", "label": "Follow-up email",
             "subject": "Re: Reaching out — {{company}}",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "Just following up in case my earlier message got buried. "
                 "Happy to share some ideas that have worked for similar "
                 "companies like {{company}}.\n\n"
                 "Best,\nThe Team"
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
    # ── 3. LinkedIn Outreach ────────────────────────────────────────
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
    # ── 4. Qualification ────────────────────────────────────────────
    {
        "id": "00000000-0004-0000-0000-000000000004",
        "name": "Qualification",
        "description": (
            "Emails a lead, waits one day, then places a qualification call. "
            "If the call connects, the lead is marked qualified (STOP). "
            "If the call fails, a missed-call email is sent before closing."
        ),
        "category": "qualification",
        "nodes": [
            {"id": "email_1", "type": "EMAIL",  "label": "Intro email",
             "subject": "Quick question about {{company}}",
             "body": (
                 "Hi {{firstName}},\n\n"
                 "I have a quick question about your current setup at "
                 "{{company}}. I'll give you a call tomorrow — hope that's OK!\n\n"
                 "Best,\nThe Team"
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
    # ── 5. Demo Booking ─────────────────────────────────────────────
    {
        "id": "00000000-0005-0000-0000-000000000005",
        "name": "Demo Booking",
        "description": (
            "Invites a lead to a demo via email, then follows up with a call "
            "one day later. If the call books the demo, the sequence ends. "
            "Otherwise a final follow-up email is sent after two more days."
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
                 "of what we offer at {{company}}, just reply to this email.\n\n"
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
            {"id": "e5", "source": "cond_1",  "target": "wait_2",
             "condition": "FALSE"},
            {"id": "e6", "source": "wait_2",  "target": "email_2"},
            {"id": "e7", "source": "email_2", "target": "stop_2"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "workflow_templates",
        sa.Column("id",              sa.UUID(),           nullable=False),
        sa.Column("organization_id", sa.UUID(),           nullable=True),
        sa.Column("name",            sa.String(255),      nullable=False),
        sa.Column("description",     sa.Text(),           nullable=True),
        sa.Column("category",        sa.String(64),       nullable=True),
        sa.Column("is_system",       sa.Boolean(),        nullable=False,
                  server_default="false"),
        sa.Column("nodes",           sa.JSON(),           nullable=False,
                  server_default="[]"),
        sa.Column("edges",           sa.JSON(),           nullable=False,
                  server_default="[]"),
        sa.Column("created_at",      sa.DateTime(),       nullable=False),
        sa.Column("updated_at",      sa.DateTime(),       nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workflow_templates_organization_id",
        "workflow_templates",
        ["organization_id"],
    )
    op.create_index(
        "ix_workflow_templates_category",
        "workflow_templates",
        ["category"],
    )
    op.create_index(
        "ix_workflow_templates_org_system",
        "workflow_templates",
        ["organization_id", "is_system"],
    )

    # Seed system templates.
    now = _now()
    tmpl_table = sa.table(
        "workflow_templates",
        sa.column("id",              sa.UUID()),
        sa.column("organization_id", sa.UUID()),
        sa.column("name",            sa.String()),
        sa.column("description",     sa.Text()),
        sa.column("category",        sa.String()),
        sa.column("is_system",       sa.Boolean()),
        sa.column("nodes",           sa.JSON()),
        sa.column("edges",           sa.JSON()),
        sa.column("created_at",      sa.DateTime()),
        sa.column("updated_at",      sa.DateTime()),
    )

    rows = []
    for t in _SYSTEM_TEMPLATES:
        rows.append(
            {
                "id":              t["id"],
                "organization_id": None,
                "name":            t["name"],
                "description":     t.get("description"),
                "category":        t.get("category"),
                "is_system":       True,
                "nodes":           t["nodes"],
                "edges":           t["edges"],
                "created_at":      now,
                "updated_at":      now,
            }
        )

    op.bulk_insert(tmpl_table, rows)


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index("ix_workflow_templates_org_system",      "workflow_templates")
    op.drop_index("ix_workflow_templates_category",         "workflow_templates")
    op.drop_index("ix_workflow_templates_organization_id",  "workflow_templates")
    op.drop_table("workflow_templates")
