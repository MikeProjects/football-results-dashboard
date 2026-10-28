"""Focused regression checks for the fictional time-machine scenario.

No real World Cup dataset, Azure credentials or model request is needed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from football_insights.showcase import (
    AWAY,
    EVENTS,
    HOME,
    LAST_STEP,
    evidence_at,
    known_events,
    replay_payload,
    state_at,
    step_of,
)
from football_insights.showcase_commentary import CommentaryService, INTERNAL_LANGUAGE, model_briefing, summary


def test_scenario_ids_and_order_are_deterministic() -> None:
    assert len(EVENTS) == 30
    assert len({e["id"] for e in EVENTS}) == len(EVENTS)
    assert [step_of(e) for e in EVENTS] == sorted(step_of(e) for e in EVENTS)
    assert replay_payload()["snapshots"] == [state_at(i) for i in range(LAST_STEP + 1)]


def test_replay_score_and_shootout_are_separate() -> None:
    assert state_at(96)["score"] == {HOME: 0, AWAY: 0}
    assert state_at(96)["disallowed_goals"][HOME] == 1
    assert state_at(106)["score"] == {HOME: 0, AWAY: 0}
    assert state_at(106)["saves_recorded"][AWAY] > state_at(105)["saves_recorded"][AWAY]
    assert state_at(120)["penalties"] == {HOME: 0, AWAY: 0}
    assert state_at(120)["winner"] is None
    finish = state_at(130)
    assert finish["score"] == {HOME: 0, AWAY: 0}
    assert finish["penalties"] == {HOME: 3, AWAY: 4}
    assert len(finish["kicks"][HOME]) == len(finish["kicks"][AWAY]) == 5
    assert finish["winner"] == AWAY


def test_rewind_rebuilds_the_state_without_future_events() -> None:
    assert state_at(130)["winner"] == AWAY
    early = state_at(50)
    assert early["penalties"] == {HOME: 0, AWAY: 0}
    assert early["winner"] is None
    assert "P10" not in {e["id"] for e in known_events(50)}
    assert "P10" not in json.dumps(evidence_at(106))
    assert "E017" not in json.dumps(evidence_at(45))
    assert "E017" in json.dumps(evidence_at(106))


@pytest.mark.parametrize("step", [-1, 131])
def test_invalid_cursor_rejected(step: int) -> None:
    with pytest.raises(ValueError):
        state_at(step)


def test_commentary_calls_are_independent_and_cannot_read_future() -> None:
    calls: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return SimpleNamespace(status="completed", output_text="The keeper makes another important save.")

    settings = SimpleNamespace(narrative_mode="live", ai_model_deployment="gpt-5-mini-1",
                               ai_max_output_tokens=1200, ai_reasoning_effort="low", ai_timeout_seconds=10.0)
    service = CommentaryService(settings, client_factory=lambda: SimpleNamespace(responses=FakeResponses()))
    assert service.explain(130, "fan")["status"] == "live"
    result = service.explain(106, "analyst")
    assert result["status"] == "live"
    assert result["evidence"]["winner"] is None
    assert len(calls) == 2
    assert all(c["store"] is False for c in calls)
    assert all(c["max_output_tokens"] == 1200 for c in calls)
    assert all(c["reasoning"] == {"effort": "low"} for c in calls)
    assert all("previous_response_id" not in c and "conversation" not in c for c in calls)
    later, earlier = [c["input"][0]["content"] for c in calls]
    assert "Confirmed winner: Argentina." in later
    assert "Confirmed winner:" not in earlier
    assert "Argentina wins the shootout" not in earlier
    assert "106′" in earlier
    assert "Penalty shootout so far: Spain 3–4 Argentina." in later
    # The LLM is given natural football commentary facts, not backend metadata.
    assert "P10" not in later and "E017" not in earlier
    assert "cutoff_step" not in earlier and "scenario_id" not in later


@pytest.mark.parametrize("step", [0, 45, 106, 120, 129, 130])
def test_model_briefing_avoids_internal_language_and_future_events(step: int) -> None:
    briefing = model_briefing(evidence_at(step))
    assert not INTERNAL_LANGUAGE.search(briefing)
    assert "E017" not in briefing and "P10" not in briefing
    assert "scenario_id" not in briefing and "cutoff_step" not in briefing
    assert "Match score: Spain 0–0 Argentina." in briefing
    assert "Only selected fictional incidents" in briefing
    if step < 130:
        assert "Confirmed winner:" not in briefing
        assert "Argentina converts the decisive kick" not in briefing
    else:
        assert "Confirmed winner: Argentina." in briefing
        assert "Argentina converts the decisive kick" in briefing
    if step <= 120:
        assert "Penalty shootout so far:" not in briefing
    else:
        assert "Penalty shootout so far:" in briefing


def test_unsupported_future_result_is_hidden() -> None:
    class FutureResponses:
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(status="completed", output_text="Argentina wins on penalties.")

    settings = SimpleNamespace(narrative_mode="live", ai_model_deployment="test",
                               ai_max_output_tokens=1200, ai_reasoning_effort="low", ai_timeout_seconds=10.0)
    service = CommentaryService(settings, client_factory=lambda: SimpleNamespace(responses=FutureResponses()))
    result = service.explain(45, "fan")
    assert result["status"] == "unavailable"
    assert result["commentary"] == summary(45)


@pytest.mark.parametrize(
    ("output_text", "incomplete_reason", "expected_rejection"),
    [
        ("", "max_output_tokens", "output_token_limit"),
        ("", None, "empty_model_output"),
        ("x" * 1201, None, "oversized_model_output"),
        ("Argentina wins on penalties.", None, "premature_match_result"),
        ("The supplied log says the keeper made five saves.", None, "internal_terminology"),
        ("According to the LOG, Spain missed a penalty.", None, "internal_terminology"),
        ("recorded_saves shows five stops by Argentina.", None, "internal_terminology"),
        ("Argentina converted penalties P02, P04 and P10.", None, "internal_terminology"),
        ("E017 was a turning point in extra time.", None, "internal_terminology"),
        ("The JSON payload identifies the winner.", None, "internal_terminology"),
        ("The event ID records Spain's missed penalty.", None, "internal_terminology"),
    ],
)
def test_commentary_rejections_are_diagnosable_without_leaking_text(
    output_text: str, incomplete_reason: str | None, expected_rejection: str, caplog
) -> None:  # type: ignore[no-untyped-def]
    class FakeResponses:
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            details = SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None
            return SimpleNamespace(status="completed", output_text=output_text, incomplete_details=details)

    settings = SimpleNamespace(narrative_mode="live", ai_model_deployment="test",
                               ai_max_output_tokens=1200, ai_reasoning_effort="low",
                               ai_timeout_seconds=10.0)
    service = CommentaryService(settings, client_factory=lambda: SimpleNamespace(responses=FakeResponses()))
    # Technical leakage was observed after the shootout, so exercise that cursor too.
    step = 130 if expected_rejection == "internal_terminology" else 106
    result = service.explain(step, "analyst")
    assert result["status"] == "unavailable"
    assert result["commentary"] == summary(step)
    assert f"showcase commentary rejected ({expected_rejection})" in caplog.text
    if output_text:
        assert output_text[:50] not in caplog.text


@pytest.mark.parametrize(
    ("response_status", "incomplete_reason", "expected_code"),
    [
        ("incomplete", "max_output_tokens", "output_token_limit"),
        ("incomplete", "content_filter", "incomplete_model_response"),
        ("completed", "max_output_tokens", "output_token_limit"),
        ("incomplete", None, "non_completed_model_response"),
        ("failed", None, "non_completed_model_response"),
        ("in_progress", None, "non_completed_model_response"),
    ],
)
def test_partial_text_is_never_accepted_as_live_commentary(
    response_status: str, incomplete_reason: str | None, expected_code: str, caplog
) -> None:  # type: ignore[no-untyped-def]
    """Even non-empty text is untrustworthy until the model finishes."""
    class PartialResponses:
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            details = SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None
            return SimpleNamespace(
                status=response_status,
                output_text="Spain keep pushing and Argentina respond",
                incomplete_details=details,
            )

    settings = SimpleNamespace(
        narrative_mode="live", ai_model_deployment="test",
        ai_max_output_tokens=1200, ai_reasoning_effort="low",
        ai_timeout_seconds=10.0,
    )
    service = CommentaryService(settings, client_factory=lambda: SimpleNamespace(responses=PartialResponses()))
    response = service.explain(106, "fan")
    assert response["status"] == "unavailable"
    assert response["commentary"] == summary(106)
    assert f"showcase commentary rejected ({expected_code})" in caplog.text
    assert "Spain keep pushing and Argentina respond" not in caplog.text


def test_natural_football_language_passes_validation_in_both_modes() -> None:
    """The guard must not mistake ordinary football terms for internal metadata."""
    text = ("Evidence: Spain have five recorded shots and Argentina have two saves. "
            "Interpretation: Spain created more chances, but the causes are uncertain.")
    calls: list[dict] = []

    class NaturalResponses:
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return SimpleNamespace(status="completed", output_text=text)

    settings = SimpleNamespace(narrative_mode="live", ai_model_deployment="test",
                               ai_max_output_tokens=1200, ai_reasoning_effort="low",
                               ai_timeout_seconds=10.0)
    service = CommentaryService(settings, client_factory=lambda: SimpleNamespace(responses=NaturalResponses()))
    for mode in ("fan", "analyst"):
        result = service.explain(45, mode)
        assert result["status"] == "live"
        assert result["commentary"] == text
    assert all("Speak to football viewers" in call["instructions"] for call in calls)
    assert calls[0]["instructions"] != calls[1]["instructions"]
    assert "event log" not in " ".join(evidence_at(45)["limitations"]).lower()


@pytest.mark.parametrize(
    ("step", "original_clock"),
    [(1, "0′"), (55, "52′"), (94, "90+3′"), (110, "106′")],
)
def test_fallback_does_not_relabel_last_incident(
    step: int, original_clock: str
) -> None:
    commentary = summary(step)
    assert f"At {step}′, no new recorded incident." in commentary
    assert f"Last recorded event at {original_clock}:" in commentary
    assert f"Score: {HOME} 0–0 {AWAY}." in commentary


def test_fallback_current_event_retains_actual_clock() -> None:
    assert summary(106).startswith("106′: Argentina's goalkeeper saves")
    assert summary(93).startswith("90+3′: An Argentine player is booked")
    assert summary(130).startswith("Full time:")


def test_disabled_ai_uses_honestly_labeled_summary() -> None:
    settings = SimpleNamespace(narrative_mode="off")
    result = CommentaryService(settings).explain(130, "analyst")
    assert result["status"] == "unavailable"
    assert "4" in result["commentary"]
    with pytest.raises(ValueError):
        CommentaryService(settings).explain(45, "invalid")
