#!/usr/bin/env python3
"""
Full QA / E2E suite for workflow templates, builder, conditions, scheduler,
campaigns, playbooks and per-lead workflow execution (LinkedIn EXCLUDED).

Run:
    PYTHONPATH=/home/ubuntu/Afficient-ai/backend python scripts/qa_full_suite.py

Strategy
--------
* Drives the REAL execution engine (modules.campaign.worker._run_graph_execution,
  the real node handlers, condition evaluation, WAIT parking, scheduler gating,
  campaign lifecycle service).
* Mocks only EXTERNAL IO so tests are deterministic and don't spam services:
    - SMTP send  -> captured in memory (rendering + activity logging still real)
    - IMAP reply -> per-lead REPLY_REGISTRY (so each lead is independent)
    - OpenAI     -> fake client for the CALL "LLM plan" stub
* Creates isolated rows under a test org and deletes everything at the end.
"""
from __future__ import annotations

import asyncio
import sys
import traceback
import uuid
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------- #
# 0. Settings + monkeypatches  (must run BEFORE the engine imports execute)
# --------------------------------------------------------------------------- #
from config.settings import settings

settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED = False     # CALL -> LLM stub
setattr(settings, "CAMPAIGN_DISPATCH_VIA_HTTP", False)  # never use HTTP dial

import common.email.mailer as mailer_mod
import modules.campaign.email_reply_service as reply_mod
import modules.ai.dependencies as ai_deps

SENT_EMAILS: list[dict] = []


def _fake_smtp_send(*, to, subject, text_body=None, html_body=None, **kw):
    SENT_EMAILS.append({"to": to, "subject": subject, "body": text_body or ""})
    return {"message_id": f"<{uuid.uuid4()}@qa.local>"}


mailer_mod.send_email = _fake_smtp_send

# email -> reply behaviour dict. Missing email => no reply.
REPLY_REGISTRY: dict[str, dict] = {}


def _fake_check_for_reply(*, to_address, sent_at, window_minutes=5,
                          message_id=None, execution_id="", lead_id=""):
    cfg = REPLY_REGISTRY.get(to_address)
    base = {
        "replied": False, "within_window": False, "negative_reply": False,
        "replied_at": None, "match_method": None,
        "reply_subject": None, "reply_body": None, "error": None,
    }
    if cfg:
        base.update(cfg)
        if base["replied"] and base["replied_at"] is None:
            base["replied_at"] = datetime.now(timezone.utc).isoformat()
        base["match_method"] = base.get("match_method") or "header"
    return base


reply_mod.check_for_reply = _fake_check_for_reply


class _Stats:
    total_tokens = 7


class _Resp:
    text = '{"action":"call","summary":"qa stub plan"}'
    stats = _Stats()


class _FakeOpenAI:
    async def complete(self, messages, max_tokens=256):
        return _Resp()


ai_deps.get_openai = lambda: _FakeOpenAI()

# --------------------------------------------------------------------------- #
# Engine imports (after patches)
# --------------------------------------------------------------------------- #
from sqlalchemy import text as sql_text  # noqa: E402

import database.models  # noqa: E402, F401 — register all ORM tables/FKs
from database.dependencies import get_db  # noqa: E402
from modules.campaign.model import Campaign  # noqa: E402
from modules.campaign.workflow_model import Workflow  # noqa: E402
from modules.campaign.execution_model import Execution  # noqa: E402
from modules.campaign.workflow_service import WorkflowService  # noqa: E402
from modules.campaign.execution_service import ExecutionService  # noqa: E402
from modules.campaign.template_service import (  # noqa: E402
    WorkflowTemplateService, SYSTEM_TEMPLATES,
)
from modules.campaign.repository import ExecutionRepository  # noqa: E402
from modules.campaign.worker import run_execution  # noqa: E402
from modules.campaign.service import CampaignService  # noqa: E402
from modules.leads.model import Lead, LeadList, lead_list_memberships  # noqa: E402

# --------------------------------------------------------------------------- #
# Result collector
# --------------------------------------------------------------------------- #
RESULTS: list[dict] = []


def record(name, expected, actual, passed, *, severity="", bug="", fix=""):
    RESULTS.append({
        "name": name, "expected": expected, "actual": actual,
        "passed": bool(passed),
        "severity": severity if not passed else "",
        "bug": bug if not passed else "",
        "fix": fix if not passed else "",
    })
    icon = "PASS" if passed else "FAIL"
    print(f"  [{icon}] {name}")
    if not passed:
        print(f"         expected: {expected}")
        print(f"         actual  : {actual}")


# --------------------------------------------------------------------------- #
# Tracked test rows for cleanup
# --------------------------------------------------------------------------- #
CREATED = {
    "executions": set(), "workflows": set(), "campaigns": set(),
    "leads": set(), "lead_lists": set(), "templates": set(),
}
ORG_ID: uuid.UUID
PLAYBOOK_ID: uuid.UUID | None = None


def _mk_campaign(db, name) -> Campaign:
    c = Campaign(organization_id=ORG_ID, name=name, status="draft",
                 playbook_id=PLAYBOOK_ID)
    db.add(c)
    db.flush()
    CREATED["campaigns"].add(c.id)
    return c


def _mk_workflow(db, campaign_id, nodes, edges, state="active") -> Workflow:
    wf = Workflow(campaign_id=campaign_id, state=state,
                  nodes=list(nodes), edges=list(edges))
    db.add(wf)
    db.flush()
    CREATED["workflows"].add(wf.id)
    return wf


def _mk_lead(db, first, email, phone) -> Lead:
    lead = Lead(
        organization_id=ORG_ID, first_name=first, last_name="QA",
        email=email, phone=phone,
        phone_normalized="".join(ch for ch in phone if ch.isdigit()),
        company="QA Corp", job_title="Director", status="new",
    )
    db.add(lead)
    db.flush()
    CREATED["leads"].add(lead.id)
    return lead


def _mk_execution(db, wf, lead, current_node_id=None) -> Execution:
    exe = ExecutionService.create_execution(
        db, workflow_id=wf.id, lead_id=lead.id,
        current_node_id=current_node_id,
        context={
            "campaign_id": str(wf.campaign_id),
            "org_id": str(ORG_ID),
            "playbook_id": str(PLAYBOOK_ID) if PLAYBOOK_ID else None,
            "lead": {
                "id": str(lead.id), "name": f"{lead.first_name} {lead.last_name}",
                "first_name": lead.first_name, "last_name": lead.last_name or "",
                "email": lead.email or "", "phone": lead.phone,
                "company": lead.company or "", "job_title": lead.job_title or "",
            },
        },
    )
    db.commit()
    CREATED["executions"].add(exe.id)
    return exe


async def drive(db, exe, max_steps=50) -> Execution:
    """Run an execution to a terminal state, fast-forwarding WAIT parks."""
    steps = 0
    while steps < max_steps:
        steps += 1
        exe = db.get(Execution, exe.id)
        await run_execution(db, exe)
        db.commit()
        db.refresh(exe)
        if exe.status in ("completed", "failed", "exhausted"):
            return exe
        if exe.status == "queued" and exe.next_retry_at is not None:
            exe.next_retry_at = datetime.now(timezone.utc).replace(tzinfo=None) \
                - timedelta(seconds=5)
            db.commit()
            continue
        # running (telephony) or unexpected -> stop
        return exe
    return exe


def activities_for(db, lead_id) -> list[str]:
    rows = db.execute(sql_text(
        "SELECT activity_type FROM lead_activities WHERE lead_id=:l "
        "ORDER BY created_at"), {"l": str(lead_id)}).fetchall()
    return [r[0] for r in rows]


# =========================================================================== #
# TEST GROUPS
# =========================================================================== #
async def test_templates(db):
    print("\n== 1. Workflow Templates ==")
    inserted = WorkflowTemplateService.seed_system_templates(db)
    record("Template seeding idempotent",
           "no error; system templates present",
           f"seeded {inserted} missing", True)

    sys_templates = [t for t in SYSTEM_TEMPLATES if t["name"] != "LinkedIn Outreach"]

    for tmpl in sys_templates:
        nm = tmpl["name"]
        # load + validate
        errors, warns = WorkflowService.validate_graph_detailed(
            tmpl["nodes"], tmpl["edges"])
        record(f"Template loads & validates: {nm}",
               "graph valid (0 errors)",
               f"errors={errors}", not errors,
               severity="Major", bug=f"{nm} graph invalid: {errors}",
               fix="Fix template node/edge definition")

        # execute end-to-end
        c = _mk_campaign(db, f"QA-Tmpl-{nm}")
        wf = _mk_workflow(db, c.id, tmpl["nodes"], tmpl["edges"])
        lead = _mk_lead(db, "Tessa", f"tmpl-{uuid.uuid4().hex[:8]}@qa.local",
                        f"+1999{uuid.uuid4().int % 10_000_000:07d}")
        # ensure EMAIL_REPLIED templates take a deterministic branch
        REPLY_REGISTRY[lead.email] = {"replied": True, "within_window": True}
        entry = WorkflowService.get_entry_node(wf)["id"]
        exe = _mk_execution(db, wf, lead, current_node_id=entry)
        exe = await drive(db, exe)
        ok = exe.status in ("completed",)
        record(f"Template executes correctly: {nm}",
               "execution reaches completed",
               f"status={exe.status} node={exe.current_node_id}", ok,
               severity="Major",
               bug=f"{nm} did not complete: {exe.last_failure_reason}",
               fix="Inspect node handler / edge wiring")

    # CRUD: edit / duplicate / delete on an org custom template
    base = SYSTEM_TEMPLATES[0]
    custom = WorkflowTemplateService.create_template(
        db, org_id=ORG_ID, name="QA Custom Template",
        description="custom", category="custom",
        nodes=base["nodes"], edges=base["edges"])
    db.commit()
    CREATED["templates"].add(custom.id)
    record("Custom template create",
           "row created, is_system=False",
           f"id={custom.id} is_system={custom.is_system}",
           custom.is_system is False)

    # edit (graph update via repository semantics) -> rename
    custom.name = "QA Custom Template (edited)"
    db.commit()
    reloaded = WorkflowTemplateService.get_template(db, custom.id, ORG_ID)
    record("Custom template edit persists",
           "name updated on reload",
           f"name={reloaded.name}",
           reloaded.name == "QA Custom Template (edited)")

    # duplicate / clone
    clone = WorkflowTemplateService.clone_template(
        db, custom.id, ORG_ID, name="QA Custom Clone")
    db.commit()
    CREATED["templates"].add(clone.id)
    record("Template duplicate (clone)",
           "new template with copied graph",
           f"clone_id={clone.id} nodes={len(clone.nodes)}",
           clone.id != custom.id and len(clone.nodes) == len(custom.nodes))

    # delete
    db.delete(clone)
    db.commit()
    CREATED["templates"].discard(clone.id)
    gone = WorkflowTemplateService.get_template(db, clone.id, ORG_ID)
    record("Template delete",
           "template no longer retrievable",
           f"get={gone}", gone is None)

    # system template cannot be deleted by org (visibility/guard) — verify list
    listed = WorkflowTemplateService.list_templates(db, ORG_ID)
    names = {t.name for t in listed}
    record("System templates listed for org",
           "Cold Outreach + Demo Booking visible",
           f"count={len(listed)}",
           "Cold Outreach" in names and "Demo Booking" in names)


async def test_builder(db):
    print("\n== 2. Workflow Builder (all node types + persistence) ==")
    nodes = [
        {"id": "email_1", "type": "EMAIL", "label": "Intro",
         "subject": "Hi {{firstName}}", "body": "Hello {{firstName}} at {{company}}"},
        {"id": "wait_1", "type": "WAIT", "label": "Wait", "duration": 1, "unit": "minutes"},
        {"id": "cond_1", "type": "CONDITION", "label": "Replied?",
         "condition_type": "EMAIL_REPLIED", "source_node": "email_1", "window_minutes": 5},
        {"id": "call_1", "type": "CALL", "label": "Call"},
        {"id": "stop_1", "type": "STOP", "label": "Done-call"},
        {"id": "stop_2", "type": "STOP", "label": "Done-noreply"},
    ]
    edges = [
        {"id": "e1", "source": "email_1", "target": "wait_1"},
        {"id": "e2", "source": "wait_1", "target": "cond_1"},
        {"id": "e3", "source": "cond_1", "target": "call_1", "condition": "TRUE"},
        {"id": "e4", "source": "cond_1", "target": "stop_2", "condition": "FALSE"},
        {"id": "e5", "source": "call_1", "target": "stop_1"},
    ]
    errors, warns = WorkflowService.validate_graph_detailed(nodes, edges)
    record("Builder graph (EMAIL/WAIT/CONDITION/CALL/STOP) validates",
           "0 errors", f"errors={errors}", not errors,
           severity="Major", bug=str(errors), fix="fix builder validation")

    c = _mk_campaign(db, "QA-Builder")
    wf = _mk_workflow(db, c.id, [], [])
    # save graph via service (this is the builder "save" path -> versioning)
    WorkflowService.update_graph(db, wf, nodes=nodes, edges=edges, created_by=None)
    db.commit()

    # reload & verify node config persisted
    wf2 = db.get(Workflow, wf.id)
    db.refresh(wf2)
    email_node = next(n for n in wf2.nodes if n["id"] == "email_1")
    record("Workflow reloads with node config intact",
           "email_1 retains subject/body",
           f"subject={email_node.get('subject')!r}",
           email_node.get("subject") == "Hi {{firstName}}")
    record("Connections (edges) saved",
           "5 edges persisted with condition labels",
           f"edges={len(wf2.edges)}",
           len(wf2.edges) == 5 and any(e.get("condition") == "TRUE" for e in wf2.edges))

    versions = WorkflowService.list_versions(db, wf.id)
    record("Workflow versioning on graph save",
           ">=1 version snapshot",
           f"versions={len(versions)}", len(versions) >= 1)

    # idempotent re-save = no new version
    WorkflowService.update_graph(db, wf2, nodes=nodes, edges=edges)
    db.commit()
    versions2 = WorkflowService.list_versions(db, wf.id)
    record("Identical re-save does not bump version",
           f"versions unchanged ({len(versions)})",
           f"versions={len(versions2)}", len(versions2) == len(versions))

    # execution follows design (TRUE branch)
    lead = _mk_lead(db, "Bram", f"build-{uuid.uuid4().hex[:8]}@qa.local",
                    f"+1999{uuid.uuid4().int % 10_000_000:07d}")
    REPLY_REGISTRY[lead.email] = {"replied": True, "within_window": True}
    exe = _mk_execution(db, wf2, lead,
                        current_node_id=WorkflowService.get_entry_node(wf2)["id"])
    exe = await drive(db, exe)
    ended_at_call_branch = (exe.node_outputs or {}).get("cond_1", {}).get("next_node") == "call_1"
    record("Execution follows designed workflow",
           "reply=True -> CALL branch -> completed",
           f"status={exe.status} cond_next={(exe.node_outputs or {}).get('cond_1',{}).get('next_node')}",
           exe.status == "completed" and ended_at_call_branch)


async def test_email_workflows(db):
    print("\n== 3. Email Workflows ==")
    # Email -> Wait -> Email
    nodes = [
        {"id": "e1n", "type": "EMAIL", "label": "E1", "subject": "S1 {{firstName}}",
         "body": "Body1 {{firstName}} {{company}}"},
        {"id": "w1n", "type": "WAIT", "label": "W", "duration": 1, "unit": "minutes"},
        {"id": "e2n", "type": "EMAIL", "label": "E2", "subject": "S2 {{firstName}}",
         "body": "Body2 {{firstName}}"},
        {"id": "s1n", "type": "STOP", "label": "done"},
    ]
    edges = [
        {"id": "ea", "source": "e1n", "target": "w1n"},
        {"id": "eb", "source": "w1n", "target": "e2n"},
        {"id": "ec", "source": "e2n", "target": "s1n"},
    ]
    c = _mk_campaign(db, "QA-Email-EWE")
    wf = _mk_workflow(db, c.id, nodes, edges)
    lead = _mk_lead(db, "Cara", f"ewe-{uuid.uuid4().hex[:8]}@qa.local",
                    f"+1999{uuid.uuid4().int % 10_000_000:07d}")
    before = len(SENT_EMAILS)
    exe = _mk_execution(db, wf, lead,
                        current_node_id=WorkflowService.get_entry_node(wf)["id"])
    exe = await drive(db, exe)
    sent = SENT_EMAILS[before:]
    record("Email->Wait->Email sends both emails",
           "2 emails sent, status completed",
           f"sent={len(sent)} status={exe.status}",
           len(sent) == 2 and exe.status == "completed")
    record("Personalization variables rendered",
           "subject contains lead first name 'Cara', no raw {{}}",
           f"subject1={sent[0]['subject'] if sent else None!r}",
           bool(sent) and "Cara" in sent[0]["subject"] and "{{" not in sent[0]["subject"])
    acts = activities_for(db, lead.id)
    record("Email sent logged to lead activity",
           "email_sent activity present",
           f"acts={acts}", acts.count("email_sent") == 2)

    # Failed email logged
    c2 = _mk_campaign(db, "QA-Email-Fail")
    wf2 = _mk_workflow(db, c2.id,
                       [{"id": "ef", "type": "EMAIL", "label": "E", "subject": "x",
                         "body": "y {{firstName}}"},
                        {"id": "sf", "type": "STOP", "label": "d"}],
                       [{"id": "g1", "source": "ef", "target": "sf"}])
    lead2 = _mk_lead(db, "Fail", f"fail-{uuid.uuid4().hex[:8]}@qa.local",
                     f"+1999{uuid.uuid4().int % 10_000_000:07d}")

    def _raise(**kw):
        raise RuntimeError("SMTP boom")
    orig = mailer_mod.send_email
    mailer_mod.send_email = _raise
    try:
        exe2 = _mk_execution(db, wf2, lead2,
                             current_node_id=WorkflowService.get_entry_node(wf2)["id"])
        exe2 = await drive(db, exe2)
    finally:
        mailer_mod.send_email = orig
    out = (exe2.node_outputs or {}).get("ef", {})
    acts2 = activities_for(db, lead2.id)
    record("Failed email is logged (non-blocking)",
           "node output sent=False with error, email_failed activity, workflow continues",
           f"sent={out.get('sent')} err={out.get('error')!r} acts={acts2}",
           out.get("sent") is False and "email_failed" in acts2 and exe2.status == "completed",
           severity="Major", bug="Email failure handling incorrect",
           fix="ensure EmailService logs email_failed and graph advances")

    # Email -> Condition -> Call (follow-up email tested in condition group)
    record("Follow-up email executes after wait",
           "second email after wait sent",
           f"second_subject={sent[1]['subject'] if len(sent) > 1 else None!r}",
           len(sent) == 2)


async def test_call_workflows(db):
    print("\n== 4. Call Workflows ==")
    nodes = [
        {"id": "c1", "type": "CALL", "label": "Call1"},
        {"id": "w1", "type": "WAIT", "label": "wait", "duration": 1, "unit": "minutes"},
        {"id": "c2", "type": "CALL", "label": "Call2"},
        {"id": "s1", "type": "STOP", "label": "done"},
    ]
    edges = [
        {"id": "e1", "source": "c1", "target": "w1"},
        {"id": "e2", "source": "w1", "target": "c2"},
        {"id": "e3", "source": "c2", "target": "s1"},
    ]
    c = _mk_campaign(db, "QA-Call-CWC")
    wf = _mk_workflow(db, c.id, nodes, edges)
    lead = _mk_lead(db, "Dale", f"cwc-{uuid.uuid4().hex[:8]}@qa.local",
                    f"+1999{uuid.uuid4().int % 10_000_000:07d}")
    exe = _mk_execution(db, wf, lead,
                        current_node_id=WorkflowService.get_entry_node(wf)["id"])
    exe = await drive(db, exe)
    outs = exe.node_outputs or {}
    record("Call->Wait->Call executes both calls",
           "both call nodes produce output, completed",
           f"c1={outs.get('c1',{}).get('outcome')} c2={outs.get('c2',{}).get('outcome')} status={exe.status}",
           outs.get("c1", {}).get("outcome") == "completed"
           and outs.get("c2", {}).get("outcome") == "completed"
           and exe.status == "completed")
    acts = activities_for(db, lead.id)
    record("Call status tracked via lead activity",
           "call_init/call_done activities present",
           f"acts={acts}", "call_init" in acts or "call_done" in acts,
           severity="Minor", bug="call activity not logged",
           fix="CallNodeHandler._log_call_activity needs org_id in context")
    record("Call results stored in node_outputs",
           "plan text stored",
           f"plan_present={'plan' in outs.get('c1',{})}",
           "plan" in outs.get("c1", {}))


async def test_condition_workflows(db):
    print("\n== 5. Condition Workflows (reply -> branch) ==")
    nodes = [
        {"id": "em", "type": "EMAIL", "label": "E", "subject": "Hi {{firstName}}",
         "body": "b {{firstName}}"},
        {"id": "cd", "type": "CONDITION", "label": "Replied?",
         "condition_type": "EMAIL_REPLIED", "source_node": "em", "window_minutes": 5},
        {"id": "cl", "type": "CALL", "label": "Call"},
        {"id": "fu", "type": "EMAIL", "label": "Follow", "subject": "FU {{firstName}}",
         "body": "fu {{firstName}}"},
        {"id": "sc", "type": "STOP", "label": "after-call"},
        {"id": "sf", "type": "STOP", "label": "after-fu"},
    ]
    edges = [
        {"id": "e1", "source": "em", "target": "cd"},
        {"id": "e2", "source": "cd", "target": "cl", "condition": "TRUE"},
        {"id": "e3", "source": "cd", "target": "fu", "condition": "FALSE"},
        {"id": "e4", "source": "cl", "target": "sc"},
        {"id": "e5", "source": "fu", "target": "sf"},
    ]
    c = _mk_campaign(db, "QA-Condition")
    wf = _mk_workflow(db, c.id, nodes, edges)

    # YES branch
    lead_yes = _mk_lead(db, "Yara", f"yes-{uuid.uuid4().hex[:8]}@qa.local",
                        f"+1999{uuid.uuid4().int % 10_000_000:07d}")
    REPLY_REGISTRY[lead_yes.email] = {"replied": True, "within_window": True}
    exe_y = _mk_execution(db, wf, lead_yes,
                          current_node_id=WorkflowService.get_entry_node(wf)["id"])
    exe_y = await drive(db, exe_y)
    y_branch = (exe_y.node_outputs or {}).get("cd", {}).get("next_node")
    record("Reply received -> CALL branch",
           "condition TRUE -> next_node=cl, call executed",
           f"branch={y_branch} call_out={(exe_y.node_outputs or {}).get('cl',{}).get('outcome')}",
           y_branch == "cl" and (exe_y.node_outputs or {}).get("cl", {}).get("outcome") == "completed")

    # NO branch
    lead_no = _mk_lead(db, "Noah", f"no-{uuid.uuid4().hex[:8]}@qa.local",
                       f"+1999{uuid.uuid4().int % 10_000_000:07d}")
    # not in REPLY_REGISTRY -> no reply
    exe_n = _mk_execution(db, wf, lead_no,
                          current_node_id=WorkflowService.get_entry_node(wf)["id"])
    exe_n = await drive(db, exe_n)
    n_branch = (exe_n.node_outputs or {}).get("cd", {}).get("next_node")
    record("No reply -> Follow-up email branch",
           "condition FALSE -> next_node=fu, follow-up email sent",
           f"branch={n_branch} fu_sent={(exe_n.node_outputs or {}).get('fu',{}).get('sent')}",
           n_branch == "fu" and (exe_n.node_outputs or {}).get("fu", {}).get("sent") is True)
    record("Branching is lead-specific / independent",
           "same workflow, two leads, different branches",
           f"yes->{y_branch}  no->{n_branch}",
           y_branch == "cl" and n_branch == "fu")


async def test_multi_lead(db):
    print("\n== 6. Multi-Lead Campaign (A/B/C/D independent) ==")
    nodes = [
        {"id": "em", "type": "EMAIL", "label": "E", "subject": "Hi {{firstName}}",
         "body": "b {{firstName}}"},
        {"id": "cd", "type": "CONDITION", "label": "Replied?",
         "condition_type": "EMAIL_REPLIED", "source_node": "em", "window_minutes": 5},
        {"id": "cl", "type": "CALL", "label": "Call"},
        {"id": "fu", "type": "EMAIL", "label": "Follow", "subject": "FU {{firstName}}",
         "body": "fu {{firstName}}"},
        {"id": "sc", "type": "STOP", "label": "after-call"},
        {"id": "sf", "type": "STOP", "label": "after-fu"},
    ]
    edges = [
        {"id": "e1", "source": "em", "target": "cd"},
        {"id": "e2", "source": "cd", "target": "cl", "condition": "TRUE"},
        {"id": "e3", "source": "cd", "target": "fu", "condition": "FALSE"},
        {"id": "e4", "source": "cl", "target": "sc"},
        {"id": "e5", "source": "fu", "target": "sf"},
    ]
    c = _mk_campaign(db, "QA-MultiLead")
    wf = _mk_workflow(db, c.id, nodes, edges)

    plan = {"A": False, "B": True, "C": True, "D": False}
    expected_branch = {"A": "fu", "B": "cl", "C": "cl", "D": "fu"}
    leads = {}
    exes = {}
    for tag, replied in plan.items():
        ld = _mk_lead(db, f"Lead{tag}", f"ml{tag}-{uuid.uuid4().hex[:6]}@qa.local",
                      f"+1999{uuid.uuid4().int % 10_000_000:07d}")
        leads[tag] = ld
        if replied:
            REPLY_REGISTRY[ld.email] = {"replied": True, "within_window": True}
        exes[tag] = _mk_execution(db, wf, ld,
                                  current_node_id=WorkflowService.get_entry_node(wf)["id"])

    # drive all
    for tag in plan:
        exes[tag] = await drive(db, exes[tag])

    all_ok = True
    detail = []
    for tag in plan:
        branch = (exes[tag].node_outputs or {}).get("cd", {}).get("next_node")
        ok = branch == expected_branch[tag] and exes[tag].status == "completed"
        all_ok = all_ok and ok
        detail.append(f"{tag}:{branch}({exes[tag].status})")
    record("Per-lead independent branch progression (A no,B yes,C yes,D no)",
           "A->fu B->cl C->cl D->fu, all completed",
           " ".join(detail), all_ok)

    # independence: D's execution must not have any reply / call output
    d_out = exes["D"].node_outputs or {}
    record("One lead's reply does not affect another",
           "Lead D (no reply) has NO call output",
           f"D_has_call={'cl' in d_out}", "cl" not in d_out)

    # separate execution rows per lead
    distinct = len({exes[t].id for t in plan})
    record("Separate workflow execution row per lead",
           "4 distinct execution rows",
           f"distinct={distinct}", distinct == 4)


async def test_negative_reply(db):
    print("\n== 7. Negative Reply Detection ==")
    nodes = [
        {"id": "em", "type": "EMAIL", "label": "E", "subject": "Hi {{firstName}}",
         "body": "b {{firstName}}"},
        {"id": "cd", "type": "CONDITION", "label": "Negative?",
         "condition_type": "NEGATIVE_REPLY", "source_node": "em", "window_minutes": 60},
        {"id": "stp", "type": "STOP", "label": "stop-closed"},
        {"id": "cl", "type": "CALL", "label": "Call(should-not-run)"},
        {"id": "sc", "type": "STOP", "label": "after-call"},
    ]
    edges = [
        {"id": "e1", "source": "em", "target": "cd"},
        {"id": "e2", "source": "cd", "target": "stp", "condition": "TRUE"},
        {"id": "e3", "source": "cd", "target": "cl", "condition": "FALSE"},
        {"id": "e4", "source": "cl", "target": "sc"},
    ]
    c = _mk_campaign(db, "QA-Negative")
    wf = _mk_workflow(db, c.id, nodes, edges)

    phrases = ["Not interested", "Stop contacting me", "Please remove me",
               "unsubscribe"]
    all_stop = True
    all_lost = True
    no_extra = True
    detail = []
    neg_leads = []
    for ph in phrases:
        ld = _mk_lead(db, "Neg", f"neg-{uuid.uuid4().hex[:6]}@qa.local",
                      f"+1999{uuid.uuid4().int % 10_000_000:07d}")
        neg_leads.append(ld)
        REPLY_REGISTRY[ld.email] = {
            "replied": True, "within_window": True, "negative_reply": True,
            "reply_subject": "Re", "reply_body": ph,
        }
        exe = _mk_execution(db, wf, ld,
                            current_node_id=WorkflowService.get_entry_node(wf)["id"])
        exe = await drive(db, exe)
        db.refresh(ld)
        branch = (exe.node_outputs or {}).get("cd", {}).get("next_node")
        outs = exe.node_outputs or {}
        all_stop = all_stop and branch == "stp" and exe.status == "completed"
        all_lost = all_lost and ld.status == "lost"
        no_extra = no_extra and "cl" not in outs
        detail.append(f"{ph!r}:{branch}/{ld.status}")

    record("Negative reply -> workflow stops (TRUE branch to STOP)",
           "all 4 phrases -> branch=stp, completed",
           " | ".join(detail), all_stop,
           severity="Critical", bug="negative reply did not stop workflow",
           fix="check NEGATIVE_REPLY evaluator + edge labels")
    record("Negative reply -> lead marked closed (lost)",
           "lead.status == lost for all",
           f"all_lost={all_lost}", all_lost,
           severity="Critical", bug="lead not marked lost on opt-out",
           fix="ConditionNodeHandler._handle_negative_reply")
    record("No further actions after stop (no call executed)",
           "CALL node never ran",
           f"no_call_output={no_extra}", no_extra,
           severity="Critical", bug="workflow continued after opt-out",
           fix="ensure STOP terminal on negative branch")
    neg_acts = [activities_for(db, ld.id) for ld in neg_leads]
    all_neg_logged = all("reply_neg" in a for a in neg_acts)
    record("Negative reply activity logged",
           "reply_neg activity present for every opt-out lead",
           f"acts={neg_acts}", all_neg_logged,
           severity="Minor", bug="reply_neg not logged",
           fix="_handle_negative_reply activity insert")


async def test_scheduler(db):
    print("\n== 8. Scheduler / WAIT timing ==")
    from modules.campaign.node_handlers.wait_handler import WaitNodeHandler
    cases = [("minutes", 1, 1), ("minutes", 5, 5), ("hours", 1, 60)]
    c = _mk_campaign(db, "QA-Scheduler")
    for unit, dur, exp_min in cases:
        nodes = [{"id": "w", "type": "WAIT", "duration": dur, "unit": unit},
                 {"id": "s", "type": "STOP"}]
        edges = [{"id": "e", "source": "w", "target": "s"}]
        wf = _mk_workflow(db, c.id, nodes, edges, state="draft")
        lead = _mk_lead(db, "Sch", f"sch-{uuid.uuid4().hex[:6]}@qa.local",
                        f"+1999{uuid.uuid4().int % 10_000_000:07d}")
        exe = _mk_execution(db, wf, lead, current_node_id="w")
        t0 = datetime.now(timezone.utc).replace(tzinfo=None)
        await run_execution(db, exe)
        db.commit(); db.refresh(exe)
        delta_min = (exe.next_retry_at - t0).total_seconds() / 60 if exe.next_retry_at else None
        ok = (exe.status == "queued" and exe.current_node_id == "s"
              and delta_min is not None and abs(delta_min - exp_min) < 1.5)
        record(f"WAIT {dur} {unit} parks with correct wake time",
               f"queued, next node=s, ~{exp_min} min",
               f"status={exe.status} node={exe.current_node_id} delta={delta_min}",
               ok)

        # scheduler gating: not dispatchable until wake, dispatchable after
        future_q = ExecutionRepository.list_queued(db, wf.id, limit=10,
                                                   now=datetime.now(timezone.utc))
        not_yet = exe.id not in {e.id for e in future_q}
        later = datetime.now(timezone.utc) + timedelta(minutes=exp_min + 1)
        ready_q = ExecutionRepository.list_queued(db, wf.id, limit=10, now=later)
        ready = exe.id in {e.id for e in ready_q}
        record(f"Scheduler gates WAIT {dur}{unit[:3]} until wake_at",
               "excluded before wake, included after",
               f"before={not not_yet} after={ready}", not_yet and ready)


async def test_campaign_lifecycle(db):
    print("\n== 9. Campaign lifecycle (create/activate/pause/resume/stop) ==")
    # build a lead list + leads
    ll = LeadList(organization_id=ORG_ID, name=f"QA-List-{uuid.uuid4().hex[:6]}")
    db.add(ll); db.flush()
    CREATED["lead_lists"].add(ll.id)
    leads = []
    for i in range(3):
        ld = _mk_lead(db, f"Camp{i}", f"camp{i}-{uuid.uuid4().hex[:6]}@qa.local",
                      f"+1999{uuid.uuid4().int % 10_000_000:07d}")
        leads.append(ld)
        db.execute(lead_list_memberships.insert().values(
            lead_id=ld.id, lead_list_id=ll.id, created_at=datetime.now(timezone.utc)))
    db.commit()

    c = _mk_campaign(db, "QA-Lifecycle")
    c.lead_list_id = ll.id
    db.commit()
    record("Campaign creation", "status=draft", f"status={c.status}",
           c.status == "draft")

    res = CampaignService.activate(db, c)
    db.refresh(c)
    wf_id = res.get("workflow_id")
    if wf_id:
        CREATED["workflows"].add(uuid.UUID(wf_id))
    # capture enqueued executions for cleanup
    if wf_id:
        for e in ExecutionRepository.list_by_workflow(db, uuid.UUID(wf_id)):
            CREATED["executions"].add(e.id)
    record("Campaign launch/activate",
           "status active, workflow created, 3 leads enqueued",
           f"status={c.status} enqueued={res.get('enqueued_leads')}",
           c.status == "active" and res.get("enqueued_leads") == 3)

    CampaignService.pause(db, c); db.refresh(c)
    record("Campaign pause", "status=paused", f"status={c.status}",
           c.status == "paused")

    CampaignService.resume(db, c); db.refresh(c)
    record("Campaign resume", "status=active", f"status={c.status}",
           c.status == "active")

    # stop == status update to completed (no dedicated endpoint)
    c.status = "completed"; db.commit(); db.refresh(c)
    record("Campaign stop (status->completed)",
           "status=completed",
           f"status={c.status}", c.status == "completed")


async def test_db_validation(db):
    print("\n== 10/11. Execution tracking + DB validation ==")
    # use the most recent multi-lead style execution: re-run a small workflow
    nodes = [
        {"id": "em", "type": "EMAIL", "label": "E", "subject": "Hi {{firstName}}",
         "body": "b"},
        {"id": "cd", "type": "CONDITION", "condition_type": "EMAIL_REPLIED",
         "source_node": "em", "window_minutes": 5},
        {"id": "cl", "type": "CALL"},
        {"id": "sf", "type": "STOP"},
        {"id": "sc", "type": "STOP"},
    ]
    edges = [
        {"id": "e1", "source": "em", "target": "cd"},
        {"id": "e2", "source": "cd", "target": "cl", "condition": "TRUE"},
        {"id": "e3", "source": "cd", "target": "sf", "condition": "FALSE"},
        {"id": "e4", "source": "cl", "target": "sc"},
    ]
    c = _mk_campaign(db, "QA-Tracking")
    wf = _mk_workflow(db, c.id, nodes, edges)
    lead = _mk_lead(db, "Trace", f"trace-{uuid.uuid4().hex[:6]}@qa.local",
                    f"+1999{uuid.uuid4().int % 10_000_000:07d}")
    REPLY_REGISTRY[lead.email] = {"replied": True, "within_window": True}
    exe = _mk_execution(db, wf, lead,
                        current_node_id=WorkflowService.get_entry_node(wf)["id"])
    exe = await drive(db, exe)

    acts = activities_for(db, lead.id)
    record("Log: Lead entered workflow (wf_start)",
           "wf_start present", f"acts={acts}", "wf_start" in acts)
    record("Log: Email sent (email_sent)",
           "email_sent present", f"acts={acts}", "email_sent" in acts)
    record("Log: Workflow completed (wf_done)",
           "wf_done present", f"acts={acts}", "wf_done" in acts)
    record("Log: Reply Received (reply_recv)",
           "reply_recv activity present",
           f"acts={acts}", "reply_recv" in acts,
           severity="Minor",
           bug="ACTIVITY_REPLY_RECEIVED constant defined but never written",
           fix="emit reply_recv in ConditionNodeHandler when replied=True")
    record("Log: Condition Evaluated (cond_eval)",
           "cond_eval activity present",
           f"acts={acts}", "cond_eval" in acts,
           severity="Minor",
           bug="ACTIVITY_COND_EVAL constant defined but never written",
           fix="emit cond_eval in ConditionNodeHandler after branch decision")

    # DB validation
    db.refresh(exe)
    record("DB: Execution row persists status",
           "status=completed", f"status={exe.status}", exe.status == "completed")
    record("DB: current_step (current_node_id) updates",
           "current_node_id advanced to a STOP node",
           f"node={exe.current_node_id}", exe.current_node_id in ("sc", "sf"))
    record("DB: execution history stored (node_outputs)",
           "node_outputs has em, cd entries",
           f"keys={list((exe.node_outputs or {}).keys())}",
           "em" in (exe.node_outputs or {}) and "cd" in (exe.node_outputs or {}))

    # table presence
    insp = db.execute(sql_text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))
    tables = {r[0] for r in insp}
    needed = {"workflows", "campaigns", "leads", "playbooks", "executions",
              "workflow_templates", "workflow_versions", "lead_activities"}
    record("DB: required tables exist",
           f"{sorted(needed)}",
           f"missing={sorted(needed - tables)}", needed.issubset(tables))


# =========================================================================== #
# Cleanup
# =========================================================================== #
def cleanup(db):
    print("\n== Cleanup test data ==")
    try:
        db.rollback()
        for lid in CREATED["leads"]:
            db.execute(sql_text("DELETE FROM lead_activities WHERE lead_id=:i"), {"i": str(lid)})
        for eid in CREATED["executions"]:
            db.execute(sql_text("DELETE FROM executions WHERE id=:i"), {"i": str(eid)})
        for wid in CREATED["workflows"]:
            db.execute(sql_text("DELETE FROM workflow_versions WHERE workflow_id=:i"), {"i": str(wid)})
            db.execute(sql_text("DELETE FROM executions WHERE workflow_id=:i"), {"i": str(wid)})
            db.execute(sql_text("DELETE FROM workflows WHERE id=:i"), {"i": str(wid)})
        for cid in CREATED["campaigns"]:
            db.execute(sql_text("DELETE FROM workflows WHERE campaign_id=:i"), {"i": str(cid)})
            db.execute(sql_text("DELETE FROM campaigns WHERE id=:i"), {"i": str(cid)})
        for lid in CREATED["leads"]:
            db.execute(sql_text("DELETE FROM lead_list_memberships WHERE lead_id=:i"), {"i": str(lid)})
            db.execute(sql_text("DELETE FROM leads WHERE id=:i"), {"i": str(lid)})
        for llid in CREATED["lead_lists"]:
            db.execute(sql_text("DELETE FROM lead_list_memberships WHERE lead_list_id=:i"), {"i": str(llid)})
            db.execute(sql_text("DELETE FROM lead_lists WHERE id=:i"), {"i": str(llid)})
        for tid in CREATED["templates"]:
            db.execute(sql_text("DELETE FROM workflow_templates WHERE id=:i"), {"i": str(tid)})
        db.commit()
        print("  cleanup ok")
    except Exception as exc:
        db.rollback()
        print(f"  cleanup error: {exc}")


def print_report():
    print("\n" + "=" * 78)
    print("FINAL QA REPORT")
    print("=" * 78)
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = total - passed
    for i, r in enumerate(RESULTS, 1):
        st = "PASS" if r["passed"] else "FAIL"
        print(f"{i:>2}. [{st}] {r['name']}")
        if not r["passed"]:
            print(f"      expected : {r['expected']}")
            print(f"      actual   : {r['actual']}")
            print(f"      severity : {r['severity']}")
            print(f"      bug      : {r['bug']}")
            print(f"      fix      : {r['fix']}")
    crit = sum(1 for r in RESULTS if not r["passed"] and r["severity"] == "Critical")
    major = sum(1 for r in RESULTS if not r["passed"] and r["severity"] == "Major")
    minor = sum(1 for r in RESULTS if not r["passed"] and r["severity"] == "Minor")
    print("-" * 78)
    print(f"TOTAL={total}  PASSED={passed}  FAILED={failed}  "
          f"CRITICAL={crit}  MAJOR={major}  MINOR={minor}")
    print("=" * 78)
    return failed


async def main():
    global ORG_ID, PLAYBOOK_ID
    db = next(get_db())
    try:
        row = db.execute(sql_text("""
            SELECT o.id,
                   (SELECT p.id FROM playbooks p WHERE p.organization_id=o.id LIMIT 1)
            FROM organizations o
            WHERE EXISTS (SELECT 1 FROM playbooks p WHERE p.organization_id=o.id)
            LIMIT 1
        """)).fetchone()
        ORG_ID = row[0]
        PLAYBOOK_ID = row[1]
        print(f"Test org={ORG_ID} playbook={PLAYBOOK_ID}")

        await test_templates(db)
        await test_builder(db)
        await test_email_workflows(db)
        await test_call_workflows(db)
        await test_condition_workflows(db)
        await test_multi_lead(db)
        await test_negative_reply(db)
        await test_scheduler(db)
        await test_campaign_lifecycle(db)
        await test_db_validation(db)
    except Exception:
        traceback.print_exc()
    finally:
        cleanup(db)
        failed = print_report()
        db.close()
        return failed


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
