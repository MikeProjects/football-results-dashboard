"""Non-live tests must not load a developer's .env from the working directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from football_insights.config import Settings, get_settings


def test_non_live_settings_ignore_dotenv_in_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "FOUNDRY_PROJECT_ENDPOINT=https://example.invalid/api/projects/unexpected\n"
        "AI_NARRATIVE_MODE=live\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.foundry_project_endpoint == ""
    assert settings.narrative_mode == "off"


def test_explicit_env_file_still_loads_when_requested(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "FOUNDRY_PROJECT_ENDPOINT=https://example.invalid/api/projects/explicit\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=dotenv)
    assert settings.foundry_project_endpoint == "https://example.invalid/api/projects/explicit"
    assert settings.narrative_mode == "live"
