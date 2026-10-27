"""ACA-only commands must leave a reusable operator terminal's environment intact."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_ROOT

PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is not installed")

HARNESS = r"""
$ErrorActionPreference = 'Stop'
$calls = [Collections.Generic.List[string]]::new()
function az {
    $global:LASTEXITCODE = 0
    $call = $args -join ' '
    $calls.Add($call)
    switch -Regex ($call) {
        '^account set ' { return }
        '^account show ' { 'Mock subscription'; return }
        '^ad signed-in-user show ' { '00000000-0000-0000-0000-000000000002'; return }
        '^cognitiveservices ' {
            if ($env:TEST_FAILURE -eq 'foundry') { $global:LASTEXITCODE = 1; return }
            'Mock account/model'; return
        }
        '^group exists ' { 'false'; return }
        '^deployment group show ' {
            @{
                foundryProjectEndpoint = @{value = 'https://fixture.services.ai.azure.com/api/projects/project'}
                applicationInsightsConnectionString = @{value = 'fixture-monitoring'}
                registryLoginServer = @{value = 'fixture.azurecr.io'}
                storageBlobEndpoint = @{value = 'https://fixture.blob.core.windows.net/'}
            } | ConvertTo-Json -Compress
            return
        }
        '^deployment group what-if ' {
            $calls.Add("deployApps=$env:ACA_DEPLOY_APPS;registry=$env:ACR_LOGIN_SERVER")
            return
        }
        default { throw "Unexpected mock Azure call: $call" }
    }
}
$before = [Environment]::GetEnvironmentVariables('Process')
$runs = @(foreach ($iteration in 1..2) {
    $errorText = $null
    try { & $env:TEST_ENTRYPOINT $env:TEST_COMMAND *> $null }
    catch { $errorText = $_.Exception.Message }
    $after = [Environment]::GetEnvironmentVariables('Process')
    @{
        error = $errorText
        changed = @($before.Keys | Where-Object { -not $after.Contains($_) -or $before[$_] -cne $after[$_] })
        added = @($after.Keys | Where-Object { -not $before.Contains($_) })
    }
})
@{ runs = $runs; calls = @($calls) } | ConvertTo-Json -Depth 4 -Compress
"""


@pytest.fixture
def operator_repo(tmp_path: Path) -> Path:
    root = tmp_path / "operator-repo"
    scripts = root / "demo" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("aca-only.ps1", "_common.ps1", "azure.ps1"):
        shutil.copy(REPO_ROOT / "demo" / "scripts" / name, scripts / name)
    (root / ".env").write_text(
        "AZURE_RESOURCE_GROUP=fixture-foundry\nPROJECT_TAG=fixture-project\nACA_TEST_DOTENV=fixture\n",
        encoding="utf-8",
    )
    deploy = root / ".local" / "deploy"
    deploy.mkdir(parents=True)
    (deploy / "digests.json").write_text(
        json.dumps({name: "sha256:" + "a" * 64 for name in ("web", "insights", "ingest")}), encoding="utf-8"
    )
    return root


def run_operator(root: Path, command: str = "check", **overrides: str) -> dict:
    # Copy only scripts into the fixture; remove real deployment settings from the child process.
    names = set(re.findall(r"^([A-Z_]+)=", (REPO_ROOT / ".env.example").read_text(), flags=re.MULTILINE))
    env = {key: value for key, value in os.environ.items() if key not in names}
    env.update({
        "TEST_ENTRYPOINT": str(root / "demo" / "scripts" / "aca-only.ps1"),
        "TEST_COMMAND": command,
        "TEST_FAILURE": "",
        "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
        "FOUNDRY_RESOURCE_GROUP": "explicit-foundry",
        "ACA_RESOURCE_GROUP": "fixture-aca",
        "ACA_ONLY_MODE": "false",
        "FOUNDRY_RESOURCE_NAME": "fixture",
        "FOUNDRY_PROJECT_NAME": "project",
        "FOUNDRY_PROJECT_ENDPOINT": "https://fixture.services.ai.azure.com/api/projects/project",
        "AI_MODEL_DEPLOYMENT": "fixture-model",
        "AI_ALLOWED_DEPLOYMENTS": "fixture-model",
        "ALLOWED_CIDRS": "203.0.113.7/32",
        "PROJECT_TAG": "caller-project",
        "PYTHONPATH": "caller-python-path",
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "caller-monitoring",
        "WEB_IMAGE_DIGEST": "caller-web",
        "ACA_DEPLOY_APPS": "caller-value",
        **overrides,
    })
    result = subprocess.run(
        [str(PWSH), "-NoProfile", "-NonInteractive", "-Command", HARNESS],
        env=env, cwd=root.parent, text=True, capture_output=True, check=True, timeout=30,
    )
    report = json.loads(result.stdout)
    assert len(report["runs"]) == 2
    for run in report["runs"]:
        assert run["changed"] == [], report
        assert run["added"] == [], report
    return report


@pytest.mark.parametrize("foundry_group, expected", [("explicit-foundry", "explicit-foundry"), ("", "fixture-foundry")])
def test_repeated_checks_restore_environment_and_foundry_selection(
    operator_repo: Path, foundry_group: str, expected: str,
) -> None:
    report = run_operator(
        operator_repo, FOUNDRY_RESOURCE_GROUP=foundry_group,
        AZURE_RESOURCE_GROUP="caller-default-group" if foundry_group else "",
    )
    assert all(run["error"] is None for run in report["runs"]), report
    checks = [call for call in report["calls"] if call.startswith("cognitiveservices account show")]
    assert len(checks) == 2, report
    assert all(f"-g {expected}" in call for call in checks), report


@pytest.mark.parametrize("overrides, error", [
    ({"ACA_RESOURCE_GROUP": "explicit-foundry"}, "must differ"),
    ({"TEST_FAILURE": "foundry"}, "az command failed"),
])
def test_failures_restore_environment(operator_repo: Path, overrides: dict[str, str], error: str) -> None:
    report = run_operator(operator_repo, **overrides)
    assert all(error in run["error"] for run in report["runs"]), report
    if "ACA_RESOURCE_GROUP" in overrides:
        assert report["calls"] == [], report


def test_preview_restores_deployment_outputs_and_two_phase_flag(operator_repo: Path) -> None:
    report = run_operator(operator_repo, "plan-aca")
    assert all(run["error"] is None for run in report["runs"]), report
    assert report["calls"].count("deployApps=false;registry=fixture.azurecr.io") == 2
    assert report["calls"].count("deployApps=true;registry=fixture.azurecr.io") == 2
