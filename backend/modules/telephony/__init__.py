"""Twilio PSTN telephony integration.

End-to-end outbound calling: originate a Twilio call, create a LiveKit
room per call, join the AI agent automatically, route audio via LiveKit
(SIP trunk), and reconcile lifecycle via Twilio status webhooks. All
state is persisted in ``telephony_calls`` / ``telephony_events``.
"""
