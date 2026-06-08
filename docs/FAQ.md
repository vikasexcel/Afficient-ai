# Aifficient — Frequently Asked Questions

**Version:** Phase 5C

---

## General

**Q: What is Aifficient?**  
A: Aifficient is a multi-tenant SaaS platform for AI-powered outbound sales campaigns. It automates lead outreach via email, LinkedIn, and real-time AI phone calls, guided by customisable playbook workflows.

**Q: What AI models does Aifficient use?**  
A: The conversation engine uses OpenAI GPT-4o for natural language. ElevenLabs provides text-to-speech, Deepgram handles speech-to-text, and LiveKit manages real-time voice rooms.

**Q: What telephony provider does Aifficient use?**  
A: Twilio for PSTN outbound calling. LiveKit's SIP gateway bridges the phone call into the AI agent's voice room.

**Q: Is the platform multi-tenant?**  
A: Yes. Each organisation (tenant) has completely isolated data. You cannot see another organisation's campaigns, leads, playbooks, or call data.

---

## Leads

**Q: What phone number formats are supported?**  
A: E.164 format is preferred (`+15551234567`). The platform normalises common formats automatically.

**Q: Can I import leads from a CSV?**  
A: Yes. Your CSV must include at minimum: `first_name`, `phone`. Optional columns: `last_name`, `email`, `company`, `job_title`, `tags`.

**Q: What is the maximum number of leads per list?**  
A: There is no hard limit. Pagination handles large lists. Performance is best under 50,000 leads per list; contact your admin for larger volumes.

**Q: Can the same lead appear in multiple lists?**  
A: Yes. A lead is a unique record; `lead_list_ids` is a many-to-many relationship.

**Q: What happens to a lead marked `do_not_call`?**  
A: The scheduler skips DNC leads and does not create executions for them. This status cannot be changed via the API by non-admin users.

**Q: Can I add tags to leads?**  
A: Yes. Each lead can have up to 50 tags, each up to 64 characters.

---

## Campaigns

**Q: What is the difference between a campaign and a workflow?**  
A: A campaign is the top-level entity that links a lead list to a playbook workflow and controls scheduling + pacing. A workflow (playbook) defines the sequence of actions (email, call, wait, etc.) taken per lead.

**Q: How many leads can a campaign have?**  
A: As many as are in the linked lead list. Pacing (`calls_per_hour`, `max_concurrent_calls`) controls how quickly they are processed.

**Q: Can I pause and resume a campaign?**  
A: Yes. Set status to `paused`. Executions in progress are not interrupted but no new ones are started. Set status back to `active` to resume.

**Q: Can I edit a campaign after it has launched?**  
A: You can update name, pacing, and business hours. Status transitions (`paused` ↔ `active`) are also allowed. Changing the playbook or lead list of an active campaign is not recommended — deactivate first.

**Q: What does "Completion Rate" mean in analytics?**  
A: It is `(completed executions / total executions) × 100`. A "completed" execution is one that reached a terminal outcome (qualified, meeting_booked, opted_out, do_not_call, or exhausted retries).

**Q: Why are some leads never dialled?**  
A: Common reasons: business hours restriction (campaign only dials 9am–5pm in the configured timezone), lead is `do_not_call`, Celery worker is offline, `CAMPAIGN_TELEPHONY_DIALING_ENABLED=false`.

---

## Workflows (Playbooks)

**Q: Can I have branching logic?**  
A: Yes. Use the **CONDITION** node to branch based on field values (e.g., did the lead open the email?). One branch for `true`, one for `false`.

**Q: What variables can I use in email/call scripts?**  
A: `{{first_name}}`, `{{last_name}}`, `{{email}}`, `{{phone}}`, `{{company}}`, `{{job_title}}`. Any `extra_data` field on the lead can also be referenced as `{{extra_data.field_name}}`.

**Q: Is there a maximum number of nodes in a workflow?**  
A: There is no enforced limit, but workflows with more than ~20 nodes may be difficult to manage in the builder. Split complex flows into multiple playbooks if needed.

**Q: Can I duplicate a playbook?**  
A: Not yet via the UI. As a workaround, use the API: `GET /api/v1/playbooks/{id}` to fetch the nodes/edges, then `POST /api/v1/playbooks` with a new name and the same nodes/edges.

**Q: What are Playbook Versions?**  
A: Every time you save a playbook, a version snapshot is created. This lets you roll back to a previous configuration and audit the history.

---

## Calls & AI

**Q: Can the AI agent be customised?**  
A: Yes. The AI persona, call script, qualification framework (BANT/MEDDICC), and conversation style are configured in the playbook's CALL node.

**Q: Can the AI handle objections?**  
A: The playbook system supports objection-handling branches. Configure **CONDITION** nodes that check `qualification_status` or `objection_raised` to route the conversation differently based on what the lead says.

**Q: What does "barge-in" mean?**  
A: Barge-in (interruption) lets the lead cut the AI agent off mid-sentence. When the lead speaks, the agent stops and listens. This is enabled by default for browser calls and optionally for PSTN (`PHONE_CALL_BARGE_IN_ENABLED`).

**Q: Where can I see call transcripts?**  
A: In the **Transcripts** page. Click any row to see the full conversation, qualification summary, and BANT score.

**Q: How long are call transcripts kept?**  
A: Indefinitely in the database. Redis-cached live call state is cleared after `AI_MEMORY_TTL_SECONDS` (default: 6 hours after the last activity).

**Q: What is the qualification framework?**  
A: BANT (Budget, Authority, Need, Timeline) is the default. The AI scores the lead on each dimension during the call and records the result in the call summary. MEDDICC is also supported — set `AI_QUALIFICATION_FRAMEWORK=MEDDICC`.

---

## Security & Access

**Q: Who can see my campaigns?**  
A: Only users in your organisation. All data is strictly scoped by `organization_id`.

**Q: What roles are available?**  
A: `owner`, `admin`, `agent`, `member`. See `docs/ADMIN_GUIDE.md` for permissions.

**Q: Can an admin from another company see my data?**  
A: No. Multi-tenant isolation is enforced at the database query level — every API endpoint filters by the caller's `organization_id`.

**Q: Are API keys / secrets visible to users?**  
A: No. API keys are stored server-side only. The frontend never exposes them.

**Q: How are sessions handled?**  
A: JSON Web Tokens (JWT). Access tokens expire after `JWT_EXPIRE_MINUTES` (default: 30 minutes). Refresh tokens extend the session automatically.

---

## Billing & Limits

**Q: Is there a limit on API calls?**  
A: Yes — rate limiting is enforced per user. See `docs/ADMIN_GUIDE.md §7` for the default limits and how to adjust them.

**Q: How much does a Twilio call cost?**  
A: Twilio billing is separate from Aifficient. Check your Twilio account dashboard for per-minute rates in your region.

---

## Troubleshooting

**Q: My campaign shows 0 executions — what's wrong?**  
A: Check: (1) Celery worker is running, (2) `CAMPAIGN_TELEPHONY_DIALING_ENABLED=true`, (3) campaign status is `active` (not `paused`/`draft`), (4) business hours are not blocking the current time.

**Q: I got a 429 Too Many Requests error.**  
A: You've hit a rate limit. Wait 60 seconds and retry. If you're a developer running load tests, set `RATE_LIMIT_ENABLED=false` in your test environment.

**Q: The frontend shows "Something went wrong".**  
A: This is the React ErrorBoundary catching an unexpected UI error. Click "Try again" to recover the current page, or "Reload page" for a full restart. Check the browser console for details.

**Q: I can't log in — "Invalid credentials".**  
A: Check your email and password. Passwords are case-sensitive. If you've forgotten your password, ask your admin to reset it or use the password reset flow.

**Q: The health check returns 503.**  
A: The readiness probe detected an issue with PostgreSQL, Redis, or the scheduler. Check `docs/TROUBLESHOOTING.md` for diagnosis steps.
