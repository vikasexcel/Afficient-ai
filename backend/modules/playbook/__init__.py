"""Playbook module — editable conversation prompts + qualification logic.

A playbook bundles four things together so admins can ship a new agent
behaviour without code changes:

* A **persona** + an optional free-form **system prompt** override that
  feeds into :func:`modules.ai.prompts.render_system_prompt`.
* An **opening line** the agent says when the call connects.
* A **qualification framework** (``BANT`` / ``MEDDICC`` / ``CUSTOM``)
  with editable per-field cue regexes + weights, consumed by
  :class:`modules.ai.qualification.QualificationTracker`.
* A bag of **default context variables** (company, product, value_prop,
  ...) merged into the system prompt as ``{placeholders}``.

Versioning: editing a published playbook bumps ``version`` and writes an
immutable snapshot to ``playbook_versions`` so a finished call always
knows *exactly* which prompts/cues were in force. ``ai_calls`` /
``telephony_calls`` / ``campaigns`` carry a ``playbook_id`` foreign key.
"""
