"""Conversation state machine for the live voice pipeline.

The orchestrator tracks the call through a small, well-defined set of
states. Every transition is timestamped so we can derive useful latency
metrics (e.g. *user-final → AI-speaking*, or *speech-started →
TTS-silenced*) without sprinkling timers across the call path.

States
------
* ``LISTENING``      — agent is idle, microphone open, waiting for speech.
* ``USER_SPEAKING``  — we have a speech-started or partial transcript
  from the human; agent must stay silent until we see a final.
* ``PROCESSING``     — final transcript captured, GPT-4o being asked
  for the next reply (no audio playing yet).
* ``AI_SPEAKING``    — TTS is actively pushing audio to LiveKit.
* ``RECOVERY``       — an upstream call failed (LLM/STT/TTS/LiveKit);
  we're in a degraded path (retrying, speaking a fallback line, ...).
* ``ENDED``          — terminal. The orchestrator will exit next tick.

Transitions are funnelled through a single async method so they are
serialised and observable (listeners + bounded history).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Deque, Iterable


class ConversationState(str, Enum):
    LISTENING = "listening"
    USER_SPEAKING = "user_speaking"
    PROCESSING = "processing"
    AI_SPEAKING = "ai_speaking"
    RECOVERY = "recovery"
    ENDED = "ended"


@dataclass(frozen=True)
class StateTransition:
    """One immutable state edge — emitted to listeners and kept in history."""

    from_state: ConversationState
    to_state: ConversationState
    ts: float  # monotonic seconds
    reason: str = ""


# Listener signature — sync or async; the state machine awaits async ones.
Listener = Callable[[StateTransition], "Awaitable[None] | None"]


class SessionStateMachine:
    """Serialised state container with listener fan-out and bounded history.

    The state machine itself is *not* a policy engine — it does not
    forbid transitions. The orchestrator owns the policy and uses this
    class purely to *record* the current state, time it, and notify
    consumers (logging, metrics, optional Redis snapshot).
    """

    def __init__(
        self,
        *,
        initial: ConversationState = ConversationState.LISTENING,
        history_size: int = 256,
    ) -> None:
        self._state = initial
        self._entered_at = time.monotonic()
        self._lock = asyncio.Lock()
        self._history: Deque[StateTransition] = deque(maxlen=history_size)
        self._listeners: list[Listener] = []
        self._state_event = asyncio.Event()
        self._state_event.set()  # initial state already "available"

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def time_in_state_ms(self) -> int:
        return int((time.monotonic() - self._entered_at) * 1000)

    def history(self) -> Iterable[StateTransition]:
        return tuple(self._history)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    async def transition(
        self,
        new_state: ConversationState,
        *,
        reason: str = "",
        force: bool = False,
    ) -> StateTransition | None:
        """Move to ``new_state``. No-op if already there unless ``force``.

        Returns the recorded :class:`StateTransition` (or ``None`` on
        no-op). Listeners are invoked under the lock so they observe a
        consistent ordering with other transitions.
        """

        async with self._lock:
            if self._state == new_state and not force:
                return None
            prev = self._state
            now = time.monotonic()
            transition = StateTransition(
                from_state=prev,
                to_state=new_state,
                ts=now,
                reason=reason,
            )
            self._state = new_state
            self._entered_at = now
            self._history.append(transition)
            for listener in list(self._listeners):
                try:
                    result = listener(transition)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:  # noqa: BLE001 — listener mustn't break SM
                    # Listeners are best-effort; if one explodes we still
                    # complete the transition.
                    continue
            return transition

    async def wait_until(
        self,
        target: ConversationState | set[ConversationState],
        *,
        timeout: float | None = None,
    ) -> ConversationState:
        """Block until ``state in target``. Useful in tests."""

        targets = {target} if isinstance(target, ConversationState) else set(target)
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._state not in targets:
            remaining = (
                None if deadline is None else max(0.0, deadline - time.monotonic())
            )
            if remaining == 0.0:
                raise asyncio.TimeoutError(
                    f"timed out waiting for {targets}; currently {self._state}"
                )
            # Snapshot the entered_at so we wake on the next transition.
            entered = self._entered_at
            try:
                await asyncio.wait_for(
                    self._wait_for_change(entered), timeout=remaining
                )
            except asyncio.TimeoutError:
                raise
        return self._state

    async def _wait_for_change(self, entered: float) -> None:
        # Coarse poll — state machine is low-frequency (a few transitions
        # per second), so a 25 ms tick is fine and avoids the complexity
        # of per-state asyncio.Events.
        while self._entered_at == entered:
            await asyncio.sleep(0.025)


# ---------------------------------------------------------------------------
# Aggregate stats observable from outside the orchestrator
# ---------------------------------------------------------------------------


@dataclass
class StateStats:
    """Rolling per-call counters by state. Lives alongside OrchestratorStats."""

    time_per_state_ms: dict[ConversationState, int] = field(default_factory=dict)
    enters_per_state: dict[ConversationState, int] = field(default_factory=dict)

    def record(self, transition: StateTransition, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        # Attribute the time spent in ``from_state`` to that bucket.
        elapsed_ms = int((now - transition.ts) * 1000) if False else 0
        # NOTE: ``ts`` is when we *entered* to_state, so we don't actually
        # know how long we were in from_state without an extra lookup —
        # the state machine records that via ``time_in_state_ms`` *before*
        # transitioning. The orchestrator threads that value in below.
        del elapsed_ms  # unused; kept for future use
        self.enters_per_state[transition.to_state] = (
            self.enters_per_state.get(transition.to_state, 0) + 1
        )

    def add_time(self, state: ConversationState, ms: int) -> None:
        self.time_per_state_ms[state] = self.time_per_state_ms.get(state, 0) + ms

    def as_dict(self) -> dict:
        return {
            "time_per_state_ms": {
                k.value: v for k, v in self.time_per_state_ms.items()
            },
            "enters_per_state": {
                k.value: v for k, v in self.enters_per_state.items()
            },
        }
