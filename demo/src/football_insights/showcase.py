"""Small, deterministic what-if match for the hackathon showcase.

The events below are *original synthetic fiction*, NOT FIFA/Opta event data.
Minute snapshots are derived at request time; no random generator or data import
is needed. All replay, score and evidence logic intentionally lives here so the
UI and AI can never disagree about the match facts.
"""

from __future__ import annotations

from typing import Any

SCENARIO_ID = "alternate-final-2026-v1"
HOME, AWAY = "Spain", "Argentina"
FINISH_MINUTE = 120


def _event(
    event_id: str, minute: int | None, phase: str, kind: str, team: str | None,
    title: str, detail: str, *, outcome: str = "", highlight: bool = False,
    clock: str = "", round_number: int | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id, "minute": minute, "phase": phase, "kind": kind, "team": team,
        "title": title, "detail": detail, "outcome": outcome, "highlight": highlight,
        "clock": clock or (f"{minute}′" if minute is not None else ""),
        "round": round_number,
    }


# Only selected illustrative incidents are recorded: NOT a complete event feed.
# Each penalty is its own event; the match score and shootout score stay separate.
EVENTS: tuple[dict[str, Any], ...] = (
    _event("E001", 0, "first_half", "whistle", None, "Kick-off", "The hypothetical final begins."),
    _event("E002", 9, "first_half", "shot", HOME, "Early attack",
           "Spain's first recorded shot is saved.", outcome="saved"),
    _event("E003", 16, "first_half", "shot", HOME, "Spain presses", "A Spanish effort goes wide.", outcome="wide"),
    _event("E004", 27, "first_half", "shot", HOME, "A chance", "Spain's attempt is blocked.", outcome="blocked"),
    _event("E005", 30, "first_half", "shot", HOME, "Another chance", "The goalkeeper makes a save.", outcome="saved"),
    _event("E006", 38, "first_half", "shot", HOME, "Still scoreless", "Spain shoots over the bar.", outcome="high"),
    _event("E007", 45, "first_half", "note", None, "Half-time: no breakthrough",
           "Spain has more recorded chances, but neither side scores.", highlight=True),
    _event("E008", 51, "second_half", "shot", AWAY, "Argentina counters",
           "Argentina's effort goes wide.", outcome="wide"),
    _event("E009", 52, "second_half", "shot", HOME, "Spain responds", "A Spanish shot is saved.", outcome="saved"),
    _event("E010", 62, "second_half", "shot", HOME, "Pressure continues",
           "A Spanish effort is blocked.", outcome="blocked"),
    _event("E011", 74, "second_half", "shot", HOME, "Close again", "Spain misses the target.", outcome="wide"),
    _event("E012", 77, "second_half", "shot", HOME, "Goalkeeper on form",
           "Argentina's goalkeeper saves.", outcome="saved"),
    _event("E013", 86, "second_half", "shot", HOME, "Late chance", "Spain's effort goes high.", outcome="high"),
    _event("E014", 93, "second_half", "card", AWAY, "A late yellow card",
           "An Argentine player is booked but stays on the field.", outcome="yellow",
           highlight=True, clock="90+3′"),
    _event("E015", 96, "extra_time", "disallowed_goal", HOME, "Goal disallowed",
           "Spain puts the ball in the net, but an attacking foul cancels the goal.", highlight=True),
    _event("E016", 104, "extra_time", "shot", HOME, "Extra-time chance", "Spain shoots wide.", outcome="wide"),
    _event("E017", 106, "extra_time", "shot", HOME, "The turning-point save",
           "Argentina's goalkeeper saves Spain's crucial shot. It stays 0–0.",
           outcome="saved", highlight=True),
    _event("E018", 112, "extra_time", "shot", HOME, "One more push", "Spain's shot is blocked.", outcome="blocked"),
    _event("E019", 119, "extra_time", "shot", AWAY, "Last-minute counter",
           "Argentina's late shot misses the goal.", outcome="wide"),
    _event("E020", 120, "extra_time", "whistle", None, "Penalty shootout",
           "Extra time ends scoreless; the trophy will be decided by penalties.", highlight=True),
    _event("P01", None, "shootout", "penalty", HOME, "Spain scores", "First penalty converted.",
           outcome="scored", round_number=1),
    _event("P02", None, "shootout", "penalty", AWAY, "Argentina scores", "First penalty converted.",
           outcome="scored", round_number=1),
    _event("P03", None, "shootout", "penalty", HOME, "Spain scores", "Second penalty converted.",
           outcome="scored", round_number=2),
    _event("P04", None, "shootout", "penalty", AWAY, "Argentina scores", "Second penalty converted.",
           outcome="scored", round_number=2),
    _event("P05", None, "shootout", "penalty", HOME, "Spain's shot saved",
           "Argentina's goalkeeper stops the third penalty.", outcome="saved", round_number=3,
           highlight=True),
    _event("P06", None, "shootout", "penalty", AWAY, "Argentina takes the lead",
           "Argentina converts its third penalty.", outcome="scored", round_number=3),
    _event("P07", None, "shootout", "penalty", HOME, "Spain keeps hope alive",
           "Spain converts its fourth penalty.", outcome="scored", round_number=4),
    _event("P08", None, "shootout", "penalty", AWAY, "Argentina misses",
           "The fourth Argentine penalty goes wide.", outcome="missed", round_number=4),
    _event("P09", None, "shootout", "penalty", HOME, "Spain hits the post",
           "Spain's fifth penalty hits the post.", outcome="missed", round_number=5),
    _event("P10", None, "shootout", "penalty", AWAY, "Argentina wins the shootout",
           "Argentina converts the decisive kick and wins 4–3 on penalties.",
           outcome="scored", round_number=5, highlight=True),
)

assert len({e["id"] for e in EVENTS}) == len(EVENTS)
assert all(e["team"] in (None, HOME, AWAY) for e in EVENTS)
assert all(e["minute"] is not None for e in EVENTS[:-10])
assert all(e["kind"] == "penalty" and e["minute"] is None for e in EVENTS[-10:])


def step_of(event: dict[str, Any]) -> int:
    """Minutes 0..120, then one extra cursor step for each shootout kick."""
    if event["minute"] is not None:
        return int(event["minute"])
    return FINISH_MINUTE + next(i for i, item in enumerate(EVENTS[-10:], 1) if item["id"] == event["id"])


LAST_STEP = FINISH_MINUTE + 10


def known_events(step: int) -> list[dict[str, Any]]:
    if not 0 <= step <= LAST_STEP:
        raise ValueError("replay step must be between 0 and 130")
    return [e for e in EVENTS if step_of(e) <= step]


def state_at(step: int) -> dict[str, Any]:
    """Rebuild state from facts, never from an LLM response or a UI score."""
    events = known_events(step)
    score = {HOME: 0, AWAY: 0}
    penalties = {HOME: 0, AWAY: 0}
    shots = {HOME: 0, AWAY: 0}
    saves = {HOME: 0, AWAY: 0}  # Saved shots BY the goalkeeper's team
    kicks: dict[str, list[bool]] = {HOME: [], AWAY: []}
    disallowed = {HOME: 0, AWAY: 0}
    for event in events:
        team, kind, outcome = event["team"], event["kind"], event["outcome"]
        if kind == "goal":
            score[team] += 1
        elif kind == "shot":
            shots[team] += 1
            if outcome == "saved":
                saves[AWAY if team == HOME else HOME] += 1
        elif kind == "disallowed_goal":
            disallowed[team] += 1  # A cancelled goal never updates the score.
        elif kind == "penalty":
            kicks[team].append(outcome == "scored")
            if outcome == "scored":
                penalties[team] += 1

    phase = ("shootout" if step > FINISH_MINUTE else "extra_time" if step > 93
             else "second_half" if step > 45 else "first_half")
    clock = f"{step}′" if step <= FINISH_MINUTE else f"Penalty kick {step - FINISH_MINUTE}/10"
    if events and events[-1]["minute"] == step:
        clock = events[-1]["clock"]
    winner = AWAY if step == LAST_STEP and penalties[AWAY] > penalties[HOME] else None
    return {
        "step": step, "phase": phase, "clock": clock,
        "score": score, "penalties": penalties, "shots_recorded": shots,
        "saves_recorded": saves, "disallowed_goals": disallowed,
        "kicks": kicks, "winner": winner,
        "current_event_id": events[-1]["id"] if events else None,
    }


def evidence_at(step: int) -> dict[str, Any]:
    """Only events with step <= cutoff are included: safe across fresh replays."""
    state = state_at(step)
    events = known_events(step)
    highlight = next((e for e in reversed(events) if e["highlight"]), None)
    return {
        "scenario_id": SCENARIO_ID, "synthetic": True,
        "disclosure": "Fictional what-if match, inspired by football history; not an official match record.",
        "cutoff_step": step, "clock": state["clock"], "phase": state["phase"],
        "match_score": state["score"], "penalty_score": state["penalties"],
        "recorded_shots": state["shots_recorded"],
        "recorded_saves": state["saves_recorded"],
        "disallowed_goals": state["disallowed_goals"],
        "winner": state["winner"],
        "moment": {"id": highlight["id"], "title": highlight["title"]} if highlight else None,
        "events": [{"id": e["id"], "clock": e["clock"], "team": e["team"],
                    "kind": e["kind"], "outcome": e["outcome"], "detail": e["detail"]}
                   for e in events],
        "limitations": [
            "These selected fictional moments are not a complete record of the match.",
            "Psychological pressure and tactical causation cannot be proven from these events.",
            "Do not predict or reveal events beyond this cutoff.",
        ],
    }


def replay_payload() -> dict[str, Any]:
    """UI can seek by minute; penalty steps remain individually addressable."""
    return {
        "scenario_id": SCENARIO_ID, "title": "Football Time Machine",
        "subtitle": "What if the 2026 final went to penalties?",
        "disclosure": "Fictional alternate-history simulation — NOT the real World Cup result.",
        "home": HOME, "away": AWAY, "last_step": LAST_STEP,
        "events": [{**e, "step": step_of(e)} for e in EVENTS],
        "snapshots": [state_at(step) for step in range(LAST_STEP + 1)],
    }
