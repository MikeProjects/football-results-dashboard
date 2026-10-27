"""Stateless, evidence-bounded Foundry commentary for the synthetic replay.

Every model call starts fresh: no conversation/thread, previous_response_id, or
commentary history is sent. Only events at or before the selected cursor are in
the prompt, even after a rewind. The deterministic summary remains available
if Foundry is disabled or unreachable.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import re
from typing import Any

from .config import Settings
from .showcase import AWAY, HOME, evidence_at, state_at

log = logging.getLogger(__name__)

INSTRUCTIONS = (
    "You are commentating on a FICTIONAL alternate-history football final. "
    "The supplied JSON is the entire authorized evidence. Do not use your knowledge of real "
    "World Cup results or invent additional goals, shots, decisions, outcomes, players, statistics, "
    "causes, or future events. Never speculate about later minutes or reveal the eventual winner "
    "before it is in the supplied evidence. Present the CURRENT state, not a prediction. "
    "Treat psychological pressure as an unverified possibility, never an observed measurement. "
    "Do not turn a selected sample of events into full-match totals. "
    "Write 2 or 3 short sentences in English, without a headline or markdown."
)
FUTURE_RESULT = re.compile(
    r"argentina (?:wins|won|has won|were crowned|is crowned)|"
    r"spain (?:loses|lost)|(?:wins|won) (?:the|on) penalties",
    re.IGNORECASE,
)


def summary(step: int) -> str:
    """Always-truthful fallback; not misrepresented as AI output."""
    state = state_at(step)
    s = state["score"]
    if state["winner"]:
        p = state["penalties"]
        return (f"Full time: {HOME} {s[HOME]}–{s[AWAY]} {AWAY}. "
                f"{AWAY} wins {p[AWAY]}–{p[HOME]} on penalties in this fictional scenario.")
    if step > 120:
        p = state["penalties"]
        return f"The match ended {s[HOME]}–{s[AWAY]}. Shootout in progress: {HOME} {p[HOME]}–{p[AWAY]} {AWAY}."
    last = evidence_at(step)["events"]
    if last:
        return f"{state['clock']}: {last[-1]['detail']} Score: {HOME} {s[HOME]}–{s[AWAY]} {AWAY}."
    return f"{HOME} {s[HOME]}–{s[AWAY]} {AWAY}. The fictional replay has not started."


class CommentaryService:
    """Owns no conversation state; client initialization is lazy to keep offline replay usable."""

    def __init__(self, settings: Settings, client_factory: Callable[[], Any] | None = None) -> None:
        self.settings = settings
        self.client_factory = client_factory

    def explain(self, step: int, mode: str) -> dict[str, Any]:
        if mode not in ("fan", "analyst"):
            raise ValueError("mode must be fan or analyst")
        evidence = evidence_at(step)  # Independently reconstruct; never trust a client-supplied evidence JSON.
        result: dict[str, Any] = {
            "step": step, "mode": mode, "status": "unavailable",
            "commentary": summary(step), "evidence": evidence,
        }
        if self.settings.narrative_mode != "live":
            return result

        style = ("Use clear, lively language for a casual football fan."
                 if mode == "fan" else
                 "Be concise and analytical. Explicitly distinguish evidence from interpretations.")
        try:
            if self.client_factory is not None:
                client = self.client_factory()
            else:
                from .agent.client import openai_client

                client = openai_client(self.settings)

            # store=False and a new input list prevent old runs from becoming model context.
            response = client.responses.create(
                model=self.settings.ai_model_deployment,
                instructions=INSTRUCTIONS + " " + style,
                input=[{"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}],
                store=False,
                max_output_tokens=min(self.settings.ai_max_output_tokens, 450),
                timeout=self.settings.ai_timeout_seconds,
            )
            text = str(getattr(response, "output_text", "") or "").strip()
            if not text or len(text) > 1200:
                raise ValueError("empty or oversized commentary")
            if step < 130 and FUTURE_RESULT.search(text):
                raise ValueError("premature match-result claim")
            result.update(status="live", commentary=text)
        except Exception as exc:
            # Provider exception text can include request details. Never expose it to visitors.
            log.warning("showcase commentary unavailable (%s)", type(exc).__name__)
        return result
