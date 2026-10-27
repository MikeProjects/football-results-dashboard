"""ACA-only build artifacts must not replace the legacy rollback baseline."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_ROOT

PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is not installed")

HARNESS = r"""
$ErrorActionPreference = 'Stop'
$script:Root = $env:TEST_REPO_ROOT
. (Join-Path $script:Root 'demo/scripts/azure.ps1')

# All Azure, Docker and image-tag operations are mocked; no cloud or registry is contacted.
$script:AzCalls = 0
$script:DockerCalls = 0
function Set-DemoSubscription { }
function Import-DeploymentOutputs { $env:ACR_LOGIN_SERVER = 'aca-fixture.azurecr.io' }
function Invoke-AzChecked { $script:AzCalls++ }
function Invoke-DockerChecked { $script:DockerCalls++ }
function Get-ImageTag { return 'fixture-tag' }
function docker {
    if ($args[0] -ne 'buildx' -or $args[1] -ne 'imagetools') { throw 'Unexpected Docker call' }
    $global:LASTEXITCODE = 0
    return ('"sha256:{0}"' -f ('b' * 64))
}

$deploy = Get-DeployDir
$v1Path = Join-Path $deploy 'digests.json'
$v2Path = Join-Path $deploy 'digests-v2.json'
$acaPath = Join-Path $deploy 'aca-only-digests.json'
$v1Before = Get-Content $v1Path -Raw
$v2Before = Get-Content $v2Path -Raw
$env:ACR_NAME = 'aca-fixture'
$env:ACA_ONLY_MODE = 'true'
Invoke-BuildPush *> $null
$aca = Import-Digests
$acaDigest = $env:WEB_IMAGE_DIGEST
$acaFileExists = Test-Path $acaPath
$legacyUnchanged = $v1Before -ceq (Get-Content $v1Path -Raw)
$v2Unchanged = $v2Before -ceq (Get-Content $v2Path -Raw)

$env:ACA_ONLY_MODE = 'false'
$legacy = Import-Digests
$v2 = Import-Digests 'v2'

$env:ACA_ONLY_MODE = 'true'
Remove-Item $acaPath
$missingError = $null
try { [void](Import-Digests) } catch { $missingError = $_.Exception.Message }
$invalidOutputError = $null
try { Invoke-BuildPush 'v2' *> $null } catch { $invalidOutputError = $_.Exception.Message }

@{
    acaFileExists = $acaFileExists
    acaRegistry = $aca.registry
    acaDigest = $acaDigest
    legacyUnchanged = $legacyUnchanged
    v2Unchanged = $v2Unchanged
    legacyRegistry = $legacy.registry
    v2Registry = $v2.registry
    missingError = $missingError
    invalidOutputError = $invalidOutputError
    azCalls = $script:AzCalls
    dockerCalls = $script:DockerCalls
} | ConvertTo-Json -Compress
"""


@pytest.fixture
def digest_report(tmp_path: Path) -> dict:
    """Execute shared PowerShell helpers with fake build and Azure functions."""
    root = tmp_path / "operator-repo"
    scripts = root / "demo" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(REPO_ROOT / "demo" / "scripts" / "azure.ps1", scripts / "azure.ps1")
    deploy = root / ".local" / "deploy"
    deploy.mkdir(parents=True)
    for filename, label in (("digests.json", "legacy-v1"), ("digests-v2.json", "legacy-v2")):
        (deploy / filename).write_text(
            json.dumps({"tag": label, "registry": f"{label}.azurecr.io",
                        **{target: "sha256:" + "a" * 64 for target in ("web", "insights", "ingest")}}),
            encoding="utf-8",
        )
    env = os.environ.copy()
    env["TEST_REPO_ROOT"] = str(root)
    # Prevent an operator-specific telemetry setting from breaking PowerShell startup.
    env["APPLICATIONINSIGHTS_CONNECTION_STRING"] = (
        "InstrumentationKey=11111111-1111-1111-1111-111111111111;"
        "IngestionEndpoint=https://example.invalid/"
    )
    result = subprocess.run(
        [str(PWSH), "-NoProfile", "-NonInteractive", "-Command", HARNESS],
        env=env, cwd=tmp_path, text=True, capture_output=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)


def test_aca_build_writes_separate_artifact_without_overwriting_legacy(digest_report: dict) -> None:
    assert digest_report["acaFileExists"] is True
    assert digest_report["legacyUnchanged"] is True
    assert digest_report["v2Unchanged"] is True
    assert digest_report["acaRegistry"] == "aca-fixture.azurecr.io"
    assert digest_report["acaDigest"] == "sha256:" + "b" * 64
    assert digest_report["azCalls"] == 1  # mocked ACR login
    assert digest_report["dockerCalls"] == 6  # mocked build + push for three images


def test_legacy_v1_and_v2_read_original_artifacts(digest_report: dict) -> None:
    assert digest_report["legacyRegistry"] == "legacy-v1.azurecr.io"
    assert digest_report["v2Registry"] == "legacy-v2.azurecr.io"


def test_aca_missing_artifact_fails_closed_without_legacy_fallback(digest_report: dict) -> None:
    assert "aca-only-digests.json" in digest_report["missingError"]
    assert "no fallback" in digest_report["missingError"]
    assert "do not support -Output" in digest_report["invalidOutputError"]
    assert digest_report["azCalls"] == 1  # invalid build option fails before any Azure operation
