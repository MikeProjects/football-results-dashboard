"""Stateless, evidence-bounded Foundry commentary for the synthetic replay.

Every model call starts fresh: no conversation/thread, previous_response_id, or
commentary history is sent. Only events at or before the selected cursor are in
the prompt, even after a rewind. The deterministic summary remains available
if Foundry is disabled or unreachable.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from .config import Settings
from .showcase import AWAY, HOME, evidence_at, state_at

log = logging.getLogger(__name__)

INSTRUCTIONS = (
    "You are commentating on a FICTIONAL alternate-history football final. "
    "The provided plain-English match briefing is the entire authorized evidence. "
    "It contains only selected incidents known by the current replay time. "
    "Do not use your knowledge of real "
    "World Cup results or invent additional goals, shots, decisions, outcomes, players, statistics, "
    "causes, or future events. Never speculate about later minutes or reveal the eventual winner "
    "before it is in the supplied evidence. Present the CURRENT state, not a prediction. "
    "Treat psychological pressure as an unverified possibility, never an observed measurement. "
    "Do not turn a selected sample of events into full-match totals. "
    "Speak to football viewers, not as a developer describing a data source. "
    "Translate private evidence into natural football language: use 'recorded shots', "
    "'saves', or 'Spain's third penalty', never raw field names or event codes. "
    "Do not refer to logs, JSON, schemas, payloads, prompts, raw data fields, "
    "event codes or internal identifiers, even if they appear in source material. "
    "Write 2 or 3 short sentences in English, without a headline or markdown."
)


class _CommentaryRejected(ValueError):
    """A locally generated rejection code safe for structured logs."""


FUTURE_RESULT = re.compile(
    r"argentina (?:wins|won|has won|were crowned|is crowned)|"
    r"spain (?:loses|lost)|(?:wins|won) (?:the|on) penalties",
    re.IGNORECASE,
)

# Avoid exposing technical evidence metadata in audience-facing commentary.
# Word boundaries preserve normal football terms such as "recorded shots".
INTERNAL_LANGUAGE = re.compile(
    r"\b(?:logs?|json|schemas?|payloads?|prompts?|event\s+ids?)\b|"
    r"\b[ep]\d{1,3}\b|"
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b",
    re.IGNORECASE,
)


def model_briefing(evidence: dict[str, Any]) -> str:
    """Give Foundry natural football facts, not technical keys or event identifiers.

    The evidence is already cutoff-bounded by evidence_at(step). Preserve its
    selected-event limitation and omit any winner before the final step.
    """
    score = evidence["match_score"]
    shots = evidence["recorded_shots"]
    saves = evidence["recorded_saves"]
    disallowed = evidence["disallowed_goals"]
    lines = [
        "Fictional alternate-history football final: Spain versus Argentina.",
        "Only selected fictional incidents are recorded, not a complete match account.",
        f"Current replay time: {evidence['clock']}.",
        f"Match score: Spain {score[HOME]}–{score[AWAY]} Argentina.",
        f"Recorded shots in this sample: Spain {shots[HOME]}, Argentina {shots[AWAY]}.",
        f"Recorded goalkeeper saves in this sample: Spain {saves[HOME]}, Argentina {saves[AWAY]}.",
        f"Disallowed goals in this sample: Spain {disallowed[HOME]}, Argentina {disallowed[AWAY]}.",
    ]
    if evidence["cutoff_step"] > 120:
        penalties = evidence["penalty_score"]
        lines.append(f"Penalty shootout so far: Spain {penalties[HOME]}–{penalties[AWAY]} Argentina.")
    if evidence["winner"]:
        lines.append(f"Confirmed winner: {evidence['winner']}.")
    lines.append("Selected incidents known by this replay time, in chronological order:")
    penalty_number = 0
    for incident in evidence["events"]:
        if incident["kind"] == "penalty":
            penalty_number += 1
            when = f"Penalty kick {penalty_number}/10"
        else:
            when = incident["clock"]
        team = f"{incident['team']}: " if incident["team"] else ""
        lines.append(f"- {when} — {team}{incident['detail']}")
    lines.append("Do not infer unrecorded incidents, predict later results, or present "
                 "psychological pressure or tactical causation as measured facts.")
    return "\n".join(lines)


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
    events = evidence_at(step)["events"]
    if events:
        last = events[-1]
        if state["clock"] == last["clock"]:
            incident = f"{last['clock']}: {last['detail']}"
        else:
            # Between events, the replay cursor advances but the previous incident
            # must retain its original time; never present it as a new occurrence.
            incident = (f"At {state['clock']}, no new recorded incident. "
                        f"Last recorded event at {last['clock']}: {last['detail']}")
        return f"{incident} Score: {HOME} {s[HOME]}–{s[AWAY]} {AWAY}."
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
                 "Be concise and analytical in natural football language. Distinguish "
                 "recorded incidents from uncertain interpretations without using technical jargon.")
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
                input=[{"role": "user", "content": model_briefing(evidence)}],
                store=False,
                # The model may spend output tokens on internal reasoning. Align the
                # budget and reasoning effort with the existing, working agent path.
                max_output_tokens=self.settings.ai_max_output_tokens,
                reasoning={"effort": self.settings.ai_reasoning_effort},
                timeout=self.settings.ai_timeout_seconds,
            )
            # Partial output can contain plausible prose, but is not a completed
            # explanation. Never label or cache a truncated Foundry response as live.
            incomplete = getattr(response, "incomplete_details", None)
            if incomplete is not None:
                if getattr(incomplete, "reason", None) == "max_output_tokens":
                    raise _CommentaryRejected("output_token_limit")
                raise _CommentaryRejected("incomplete_model_response")
            if getattr(response, "status", None) != "completed":
                raise _CommentaryRejected("non_completed_model_response")
            text = str(getattr(response, "output_text", "") or "").strip()
            if not text:
                raise _CommentaryRejected("empty_model_output")
            if len(text) > 1200:
                raise _CommentaryRejected("oversized_model_output")
            if step < 130 and FUTURE_RESULT.search(text):
                raise _CommentaryRejected("premature_match_result")
            if INTERNAL_LANGUAGE.search(text):
                raise _CommentaryRejected("internal_terminology")
            result.update(status="live", commentary=text)
        except _CommentaryRejected as exc:
            # These messages are fixed local codes, never untrusted provider text.
            log.warning("showcase commentary rejected (%s) mode=%s", str(exc), mode)
        except Exception as exc:
            # Provider exception text can include request details. Never expose it to visitors.
            log.warning("showcase commentary unavailable (%s) mode=%s", type(exc).__name__, mode)
        return result
