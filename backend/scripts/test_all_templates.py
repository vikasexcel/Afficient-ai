#!/usr/bin/env python3
"""
Test all workflow templates (except LinkedIn) end-to-end.

Usage:
    PYTHONPATH=/home/ubuntu/Afficient-ai/backend python scripts/test_all_templates.py

* Telephony is disabled for the test — CALL nodes use the LLM planning stub.
* WAIT nodes are skipped.
* EMAIL nodes send real emails to kumaranurad604@gmail.com.
* EMAIL_REPLIED condition checks IMAP for real replies.
* All DB changes are rolled back after each template run.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone

# ── Colours ──────────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"

def step_icon(status: str) -> str:
    return {
        "completed":       c(GREEN,  "✓"),
        "condition_true":  c(GREEN,  "→ TRUE "),
        "condition_false": c(YELLOW, "→ FALSE"),
        "skipped":         c(DIM,    "⊘ skip "),
        "failed":          c(RED,    "✗ fail "),
        "running":         c(CYAN,   "⟳      "),
        "stopped":         c(YELLOW, "■ stop "),
    }.get(status, c(DIM, "?      "))

# ── Config ───────────────────────────────────────────────────────────────────
TEST_EMAIL = "kumaranurad604@gmail.com"
TEST_PHONE = "+917541006707"
SKIP_WAIT  = True
SKIP_NAMES = {"LinkedIn Outreach"}

# ── Patch settings BEFORE any import that reads them ─────────────────────────
from config.settings import settings        # noqa: E402
settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED = False   # force LLM stub for CALL

# ── Node runner ──────────────────────────────────────────────────────────────
async def run_template(template: dict, db) -> dict:
    from sqlalchemy            import text as sql_text
    from modules.campaign.workflow_model   import Workflow
    from modules.campaign.execution_model  import Execution
    from modules.campaign.workflow_service import WorkflowService
    from modules.campaign.node_handlers.email_handler     import EmailNodeHandler
    from modules.campaign.node_handlers.call_handler      import CallNodeHandler
    from modules.campaign.node_handlers.wait_handler      import WaitNodeHandler
    from modules.campaign.node_handlers.condition_handler import ConditionNodeHandler
    from modules.campaign.node_handlers.stop_handler      import StopNodeHandler

    # Find a campaign that has no active workflow (avoids unique constraint).
    row = db.execute(sql_text("""
        SELECT c.id FROM campaigns c
        WHERE NOT EXISTS (
            SELECT 1 FROM workflows w
            WHERE w.campaign_id = c.id AND w.state = 'active'
        ) LIMIT 1
    """)).fetchone()
    if row is None:
        # Fall back: use any campaign but insert with 'draft' state
        row = db.execute(sql_text("SELECT id FROM campaigns LIMIT 1")).fetchone()
        if row is None:
            return {"result": "failed", "logs": [], "error": "No campaigns in DB"}
    cid = row[0]

    # Insert workflow + execution rows (will be rolled back after the run).
    wf = Workflow(id=uuid.uuid4(), campaign_id=cid,
                  state="draft",           # avoid uq_workflows_campaign_active
                  nodes=list(template["nodes"]),
                  edges=list(template["edges"]))
    db.add(wf)
    db.flush()

    exe = Execution(
        id=uuid.uuid4(), workflow_id=wf.id,
        status="running", attempt_number=1,
        node_outputs={},
        context={
            "lead": {
                "email":      TEST_EMAIL,
                "phone":      TEST_PHONE,
                "first_name": "Kumar",
                "last_name":  "Anurad",
                "name":       "Kumar Anurad",
                "company":    "Test Co",
                "job_title":  "Tester",
            },
            "campaign_id": str(cid),
        },
    )
    db.add(exe)
    db.flush()

    handlers = {
        "EMAIL":     EmailNodeHandler(),
        "CALL":      CallNodeHandler(),
        "WAIT":      WaitNodeHandler(),
        "CONDITION": ConditionNodeHandler(),
        "STOP":      StopNodeHandler(),
    }

    logs: list[dict] = []
    result = "completed"
    step   = 0

    def push_log(node, status, message, output=None):
        nonlocal step
        step += 1
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = dict(step=step, node_id=node.get("id",""),
                     node_type=node.get("type",""),
                     node_label=node.get("label") or node.get("type",""),
                     status=status, message=message,
                     output=output, timestamp=ts)
        logs.append(entry)
        return entry

    def print_log(entry, output=None):
        icon  = step_icon(entry["status"])
        label = c(BOLD, entry["node_label"][:28])
        print(f"  {entry['step']:>2}. {icon}  {label:<33}  {c(DIM, entry['timestamp'])}")
        print(f"        {entry['message']}")
        out = output or entry.get("output") or {}
        keys = ("sent","sent_at","to","error","outcome","replied",
                "within_window","replied_at","condition_type",
                "condition_result","skipped","plan")
        for k in keys:
            if k in out and out[k] is not None:
                print(f"        {c(DIM,'·')} {k}: {c(CYAN, str(out[k])[:90])}")

    try:
        current = WorkflowService.get_entry_node(wf)
    except ValueError as e:
        db.rollback()
        return {"result": "failed", "logs": logs, "error": str(e)}

    visited: set[str] = set()

    while current and len(visited) < 30:
        nid   = current.get("id","")
        ntype = (current.get("type") or "").upper()

        if nid in visited:
            e = push_log(current, "failed", "Cycle detected — aborting")
            print_log(e)
            result = "failed"; break
        visited.add(nid)

        handler = handlers.get(ntype)
        if handler is None:
            e = push_log(current, "failed", f"Unknown node type '{ntype}'")
            print_log(e)
            result = "failed"; break

        # ── STOP ─────────────────────────────────────────────────────────
        if ntype == "STOP":
            e = push_log(current, "stopped", f"Reached STOP — workflow done")
            print_log(e)
            result = "stopped"; break

        # ── WAIT (skip) ───────────────────────────────────────────────────
        if ntype == "WAIT" and SKIP_WAIT:
            dur, unit = current.get("duration","?"), current.get("unit","minutes")
            e = push_log(current, "skipped",
                         f"Wait skipped in test mode  [production: {dur} {unit}]")
            print_log(e)
            exe.node_outputs = {**(exe.node_outputs or {}),
                                nid: {"skipped": True}}
            nexts = WorkflowService.get_next_nodes(wf, nid)
            current = nexts[0] if nexts else None
            continue

        # ── Phone override for CALL ───────────────────────────────────────
        if ntype == "CALL":
            node_run = dict(current)
            if not node_run.get("to_number"):
                node_run["to_number"] = TEST_PHONE
        else:
            node_run = current

        e = push_log(current, "running", f"Executing {ntype}…")
        print_log(e)

        try:
            nr = await handler.execute(db, exe, node_run)
        except Exception as exc:
            e["status"]  = "failed"
            e["message"] = f"Exception: {exc}"
            print_log(e)
            result = "failed"; break

        # Store output back
        if nr.output:
            exe.node_outputs = {**(exe.node_outputs or {}), nid: nr.output}

        # Build human-readable status
        if ntype == "EMAIL":
            sent = (nr.output or {}).get("sent", False)
            e["status"]  = "completed" if sent else "failed"
            e["message"] = (f"Email sent to {TEST_EMAIL}"
                            if sent
                            else f"Email FAILED: {(nr.output or {}).get('error','?')}")
        elif ntype == "CALL":
            phone = node_run.get("to_number") or TEST_PHONE
            if nr.outcome == "failed":
                e["status"]  = "failed"
                e["message"] = f"Call FAILED: {(nr.output or {}).get('error','?')}"
            elif nr.advance:
                e["status"]  = "completed"
                e["message"] = f"Call initiated to {phone}  [LLM stub — telephony disabled in test]"
            else:
                e["status"]  = "running"
                e["message"] = f"Call placed to {phone}  [awaiting Twilio webhook]"
        elif ntype == "CONDITION":
            if nr.outcome == "failed":
                e["status"]  = "failed"
                e["message"] = f"CONDITION FAILED: {(nr.output or {}).get('error','?')}"
            else:
                cr    = (nr.output or {}).get("condition_result")
                ctype = (nr.output or {}).get("condition_type","")
                e["status"]  = "condition_true" if cr else "condition_false"
                branch = "TRUE  → call branch" if cr else "FALSE → stop branch"
                e["message"] = f"'{ctype}' evaluated → {branch}"
        else:
            e["status"]  = nr.outcome or "completed"
            e["message"] = f"{ntype} outcome: {nr.outcome}"

        e["output"] = nr.output
        print_log(e)

        if not nr.advance:
            result = "completed" if e["status"] != "failed" else "failed"
            break

        # Advance
        if nr.next_node_id:
            nmap = {n["id"]: n for n in wf.nodes}
            current = nmap.get(nr.next_node_id)
        else:
            nexts = WorkflowService.get_next_nodes(wf, nid)
            current = nexts[0] if nexts else None

    # Roll back all inserts (workflow, execution, activity rows, etc.)
    db.rollback()
    return {"result": result, "logs": logs}


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    from modules.campaign.template_service import SYSTEM_TEMPLATES
    from database.dependencies import get_db

    templates = [t for t in SYSTEM_TEMPLATES if t["name"] not in SKIP_NAMES]

    print(c(BOLD + CYAN, "\n╔══════════════════════════════════════════════════════╗"))
    print(c(BOLD + CYAN,   "║       Workflow Template End-to-End Test Suite        ║"))
    print(c(BOLD + CYAN,   "╚══════════════════════════════════════════════════════╝"))
    print(f"  Email   : {c(CYAN, TEST_EMAIL)}")
    print(f"  Phone   : {c(CYAN, TEST_PHONE)}")
    print(f"  Waits   : skipped (test mode)")
    print(f"  Dialing : LLM stub (telephony disabled for test)")
    print(f"  IMAP    : {'configured ✓' if settings.IMAP_HOST else 'NOT configured'}")
    print(f"  Tests   : {len(templates)} templates\n")

    summary = []
    db = next(get_db())

    try:
        for idx, tmpl in enumerate(templates, 1):
            name     = tmpl["name"]
            category = tmpl.get("category","")
            sep = "─" * 56

            print(c(BOLD, f"\n┌{sep}┐"))
            print(c(BOLD, f"│  {idx}. {name:<52}│"))
            print(c(BOLD, f"│     category: {category:<46}│"))
            print(c(BOLD, f"└{sep}┘"))

            t0  = datetime.now(timezone.utc)
            run = await run_template(tmpl, db)
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()

            result = run["result"]
            rc = {"completed": GREEN, "stopped": YELLOW, "failed": RED}.get(result, DIM)
            print(f"\n  Result : {c(BOLD + rc, result.upper())}   ({elapsed:.1f}s)")
            summary.append({"name": name, "result": result,
                             "steps": len(run["logs"]), "elapsed": elapsed})
            print()
    finally:
        db.close()

    # ── Summary table ─────────────────────────────────────────────────────────
    sep = "─" * 62
    print(c(BOLD + CYAN, f"\n┌{sep}┐"))
    print(c(BOLD + CYAN,  f"│  {'SUMMARY':<60}│"))
    print(c(BOLD + CYAN,  f"├{sep}┤"))
    print(f"│  {'Template':<36} {'Result':<12} {'Steps':>5}  {'Time':>6}  │")
    print(f"├{sep}┤")

    all_ok = True
    for s in summary:
        rc  = {"completed": GREEN, "stopped": YELLOW, "failed": RED}.get(s["result"], DIM)
        res = c(rc, s["result"].upper())
        nm  = s["name"][:35]
        print(f"│  {nm:<36} {res:<21} {s['steps']:>5}  {s['elapsed']:>5.1f}s  │")
        if s["result"] == "failed":
            all_ok = False

    print(c(BOLD + CYAN, f"└{sep}┘"))
    status_str = c(GREEN + BOLD, "ALL TESTS PASSED ✓") if all_ok else c(RED + BOLD, "SOME TESTS FAILED ✗")
    print(f"\n  Overall: {status_str}\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
