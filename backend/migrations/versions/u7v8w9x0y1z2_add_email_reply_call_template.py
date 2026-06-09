"""Add 'Email Reply → Call Follow-Up' system template.

Revision ID: u7v8w9x0y1z2
Revises: t6u7v8w9x0y1
Create Date: 2026-06-09

Changes
-------
* Inserts the 6th built-in system template: "Email Reply → Call Follow-Up".
  This template emails a recipient, waits 5 minutes, checks for a reply via
  IMAP, and places a call when a reply is detected within the window.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "u7v8w9x0y1z2"
down_revision: str = "t6u7v8w9x0y1"
branch_labels = None
depends_on = None

_TEMPLATE_ID = "00000000-0006-0000-0000-000000000006"

_NODES = [
    {"id": "email_1",  "type": "EMAIL",     "label": "Send email",
     "subject": "Quick question, {{firstName}}",
     "body": (
         "Hi {{firstName}},\n\n"
         "I wanted to reach out with a quick question about "
         "{{company}}. Could you reply to this email at your "
         "earliest convenience?\n\nBest,\nThe Team"
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
]

_EDGES = [
    {"id": "e1", "source": "email_1", "target": "wait_1"},
    {"id": "e2", "source": "wait_1",  "target": "cond_1"},
    {"id": "e3", "source": "cond_1",  "target": "call_1",  "condition": "TRUE"},
    {"id": "e4", "source": "cond_1",  "target": "stop_2",  "condition": "FALSE"},
    {"id": "e5", "source": "call_1",  "target": "stop_1"},
]


def upgrade() -> None:
    now = datetime.now(timezone.utc).isoformat()
    op.execute(
        sa.text(
            """
            INSERT INTO workflow_templates
                (id, organization_id, name, description, category, is_system,
                 nodes, edges, created_at, updated_at)
            VALUES
                (:id, NULL, :name, :description, :category, TRUE,
                 CAST(:nodes AS jsonb), CAST(:edges AS jsonb), :now, :now)
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            id=_TEMPLATE_ID,
            name="Email Reply → Call Follow-Up",
            description=(
                "Sends an email and waits 5 minutes. If the recipient replies "
                "within the window, an immediate call is placed to the configured "
                "phone number. If no reply arrives, the workflow stops."
            ),
            category="email-reply-call",
            nodes=json.dumps(_NODES),
            edges=json.dumps(_EDGES),
            now=now,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM workflow_templates WHERE id = :id"
        ).bindparams(id=_TEMPLATE_ID)
    )
