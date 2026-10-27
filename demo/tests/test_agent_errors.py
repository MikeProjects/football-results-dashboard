"""Provider failures preserve diagnostics and fallback without exporting response content."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_settings
from fake_responses import FakeClient
from football_insights.agent import loop
from football_insights.telemetry import JsonFormatter


class ProviderError(Exception):
    def __init__(self, message: str, body: object, code: object = None, status_code: object = 401):
        super().__init__(message)
        self.body = body
        self.code = code
        self.status_code = status_code


@pytest.mark.parametrize("wrapped", [False, True])
def test_provider_failures_do_not_log_messages(
    wrapped: bool, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    secrets = ["sk-review-only", "private-question-fragment", "secret-connection-value"]
    message = (f"Incorrect API key provided: {secrets[0]}; rejected input '{secrets[1]}'; "
               f"AccountKey='{secrets[2]}'")
    error = {"code": "invalid_api_key", "message": message}
    exc = ProviderError(message, {"error": error} if wrapped else error)
    client = FakeClient([exc])
    config = make_settings(ai_narrative_mode="live", narrative_cache_dir=tmp_path / "narratives")
    agent = loop.InsightsAgent(config, lambda *_: pytest.fail("No tools expected"), lambda: client)
    result = agent.answer("How many matches?")
    logs = [r for r in caplog.records if r.name == "football_insights.agent" and r.levelname == "WARNING"]
    assert len(logs) == 1
    formatted = JsonFormatter("insights", "Test").format(logs[0])
    assert all(secret not in formatted + result.model_dump_json() for secret in secrets)
    assert result.narrative_status == "unavailable"
    payload = json.loads(formatted)
    assert payload["error"] == "ProviderError"
    assert payload["http_status"] == 401
    assert payload["provider_code"] == "invalid_api_key"
    assert "provider_message" not in payload


@pytest.mark.parametrize("body", [None, [], "unexpected body", {"error": "unexpected shape"}])
def test_malformed_provider_body_keeps_unavailable_fallback(body: object, tmp_path: Path) -> None:
    client = FakeClient([ProviderError("unavailable", body)])
    config = make_settings(ai_narrative_mode="live", narrative_cache_dir=tmp_path / "narratives")
    agent = loop.InsightsAgent(config, lambda *_: pytest.fail("No tools expected"), lambda: client)
    assert agent.answer("How many matches?").narrative_status == "unavailable"


@pytest.mark.parametrize("body", [{"code": "content_filter"}, {"error": {"code": "content_filter"}}])
def test_structured_content_filter_remains_distinct(body: object, tmp_path: Path) -> None:
    client = FakeClient([ProviderError("blocked", body, status_code=400)])
    config = make_settings(ai_narrative_mode="live", narrative_cache_dir=tmp_path / "narratives")
    agent = loop.InsightsAgent(config, lambda *_: pytest.fail("No tools expected"), lambda: client)
    assert agent.answer("How many matches?").narrative_status == "filtered"


@pytest.mark.parametrize("status", [True, "401", 123456])
def test_unrecognized_metadata_is_not_exported(status: object) -> None:
    # Even a code that matches an identifier regex can carry secret text.
    exc = ProviderError("secret message", {"error": {"code": "sk-private-value"}}, status_code=status)
    assert loop._safe_error_details(exc) == {"error": "ProviderError"}


def test_sdk_code_attribute_is_supported() -> None:
    exc = ProviderError("message omitted", None, code="DeploymentNotFound", status_code=404)
    assert loop._safe_error_details(exc) == {
        "error": "ProviderError", "http_status": 404, "provider_code": "DeploymentNotFound",
    }


@pytest.mark.parametrize("code", ["sk-private-value", "unknown_provider_code", {"unexpected": "value"}])
def test_unrecognized_provider_codes_keep_other_diagnostics(code: object) -> None:
    exc = ProviderError("message omitted", {"code": code})
    assert loop._safe_error_details(exc) == {"error": "ProviderError", "http_status": 401}
