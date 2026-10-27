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
from football_insights.showcase_commentary import CommentaryService, summary


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
            return SimpleNamespace(output_text="The keeper makes another important save.")

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
    later, earlier = [json.loads(c["input"][0]["content"]) for c in calls]
    assert later["winner"] == AWAY
    assert earlier["winner"] is None
    assert "P10" not in {e["id"] for e in earlier["events"]}
    assert "P10" in {e["id"] for e in later["events"]}


def test_unsupported_future_result_is_hidden() -> None:
    class FutureResponses:
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(output_text="Argentina wins on penalties.")

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
    ],
)
def test_commentary_rejections_are_diagnosable_without_leaking_text(
    output_text: str, incomplete_reason: str | None, expected_rejection: str, caplog
) -> None:  # type: ignore[no-untyped-def]
    class FakeResponses:
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            details = SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None
            return SimpleNamespace(output_text=output_text, incomplete_details=details)

    settings = SimpleNamespace(narrative_mode="live", ai_model_deployment="test",
                               ai_max_output_tokens=1200, ai_reasoning_effort="low",
                               ai_timeout_seconds=10.0)
    service = CommentaryService(settings, client_factory=lambda: SimpleNamespace(responses=FakeResponses()))
    result = service.explain(106, "fan")
    assert result["status"] == "unavailable"
    assert result["commentary"] == summary(106)
    assert f"showcase commentary rejected ({expected_rejection})" in caplog.text
    assert output_text[:50] not in caplog.text if output_text else True


def test_disabled_ai_uses_honestly_labeled_summary() -> None:
    settings = SimpleNamespace(narrative_mode="off")
    result = CommentaryService(settings).explain(130, "analyst")
    assert result["status"] == "unavailable"
    assert "4" in result["commentary"]
    with pytest.raises(ValueError):
        CommentaryService(settings).explain(45, "invalid")
