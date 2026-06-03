# Playbook → Phone Dialer — verification report

*Last updated after dialer integration pass.*

## Call flow

```
DialerForm (Calls.tsx)
  → GET /playbooks?active_only=true     (dropdown list, auto-refresh)
  → GET /playbooks/{id}?for_dialer=true (full config + PLAYBOOK_SELECTED log)
  → POST /telephony/calls { playbook_id, to_number, lead_name? }
  → TelephonyService.initiate_outbound
       PLAYBOOK_SELECTED → resolve_for_call → PLAYBOOK_LOADED → PLAYBOOK_APPLIED
       VOICE_APPLIED → CallAgentRunner → ConversationOrchestrator
  → AIService.start_call (Redis meta + qualification from playbook)
  → TTS uses playbook voice_id (fallback: ELEVENLABS_VOICE_ID)
```

## Verification checklist

| Question | Answer |
|----------|--------|
| Is `playbook_id` passed to the backend? | **Yes** — `POST /telephony/calls` body |
| Is the playbook loaded before the call starts? | **Yes** — UI loads via `for_dialer`; telephony calls `resolve_for_call` before spawning the agent |
| Which fields are applied? | persona, voice, opening_line, framework, fields, branches, disqualifiers, default_context, system_prompt, default_objective |
| Which fields were ignored (fixed)? | Dialer opening override; `system_prompt` missing from meta (fixed); draft playbooks in dropdown (fixed — active only) |

## Field mapping

| UI / requirement | Playbook source | Applied at |
|------------------|-----------------|------------|
| Agent name | `default_context.agent_name` or persona mapping | `build_call_extra_context` → prompts |
| Voice | `voice_id` | Runner → orchestrator TTS |
| Company intro | `default_context.company` (etc.) | `render_system_prompt` |
| Goal of call | `default_objective` | prompts |
| Opening line | `opening_line` | Orchestrator opener |
| Framework | `framework` | Qualification + prompts |
| Things to discover | `fields` | QualificationTracker |
| Smart branching | `branches` | `_apply_playbook_branches` |
| Objection / conversation / success rules | `default_context` keys | prompts |
| Custom system prompt | `system_prompt` | `to_meta()` + `render_system_prompt` |

## Logging

| Event | When |
|-------|------|
| `PLAYBOOK_SELECTED` | Dialer GET `for_dialer=true`; telephony/AI when call starts with `playbook_id` |
| `PLAYBOOK_LOADED` | After `resolve_for_call` |
| `PLAYBOOK_APPLIED` | After merging playbook into call context |
| `VOICE_APPLIED` | Resolved voice (`playbook` or `env_default`) |
| `CALL_STARTED_WITH_PLAYBOOK` | Agent runner registered |

All include `playbook_id`, `playbook_name` (when known), `voice_id` (resolved).

## Voice priority

1. `playbook.voice_id`
2. `ELEVENLABS_VOICE_ID` from `.env`

## UI behavior

- Dropdown lists **published (active)** playbooks only; refreshes every 20s + on tab focus.
- Selecting a playbook loads full config and shows its **name** prominently.
- Place call blocked until playbook loads; errors if none selected or load fails.
