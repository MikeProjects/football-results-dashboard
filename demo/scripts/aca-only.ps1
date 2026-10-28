<# 
.SYNOPSIS
  Isolated ACA-only deployment for Football Insights.
.DESCRIPTION
  Runs in a separate ACA resource group and reuses the Foundry account in the
  existing resource group. No AKS resources or new Foundry models are deployed.
  Run 'check' first, then follow docs/ACA-ONLY.md.
#>
[CmdletBinding()]
param([Parameter(Position = 0)][string]$Command = 'check')
$ErrorActionPreference = 'Stop'
# Capture before _common.ps1 imports .env and changes Python settings.
# All workflow environment changes are temporary, including on failure.
$acaEnvironmentBefore = [Environment]::GetEnvironmentVariables('Process')
try {
    . (Join-Path $PSScriptRoot '_common.ps1')
    . (Join-Path $PSScriptRoot 'azure.ps1')

    function Set-DefaultEnv([string]$Name, [string]$Value) {
        if (-not [Environment]::GetEnvironmentVariable($Name)) {
            [Environment]::SetEnvironmentVariable($Name, $Value)
        }
    }
    function Invoke-LocalAz([string[]]$Arguments) {
        & az @Arguments
        if ($LASTEXITCODE -ne 0) { throw "az command failed: az $($Arguments -join ' ')" }
    }
    function Assert-GroupExists([string]$Name) {
        if ((az group exists --name $Name) -ne 'true') {
            throw "Resource group $Name does not exist. Run '.\demo\scripts\aca-only.ps1 init-group' first."
        }
    }
    function Assert-AllowedCidr {
        $value = [Environment]::GetEnvironmentVariable('ALLOWED_CIDRS')
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw 'ALLOWED_CIDRS must contain your public IPv4/CIDR before deploying a public web app (e.g., 203.0.113.7/32).'
        }
        foreach ($cidr in $value.Split(',')) {
            $parts = $cidr.Trim().Split('/')
            $ip = $null
            if ($parts.Count -ne 2 -or -not [Net.IPAddress]::TryParse($parts[0], [ref]$ip) -or
                $ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
                $parts[1] -notmatch '^(\d|[12]\d|3[0-2])$') {
                throw "Invalid IPv4 CIDR in ALLOWED_CIDRS: $cidr"
            }
        }
    }
    function Test-FoundrySelection {
        $name = Get-RequiredEnv 'FOUNDRY_RESOURCE_NAME'
        $project = Get-RequiredEnv 'FOUNDRY_PROJECT_NAME'
        $endpoint = Get-RequiredEnv 'FOUNDRY_PROJECT_ENDPOINT'
        $deployment = Get-RequiredEnv 'AI_MODEL_DEPLOYMENT'
        $allowed = (Get-RequiredEnv 'AI_ALLOWED_DEPLOYMENTS').Split(',') | ForEach-Object { $_.Trim() }
        $expected = "https://$name.services.ai.azure.com/api/projects/$project"
        if ($endpoint.TrimEnd('/') -ne $expected) {
            throw "FOUNDRY_PROJECT_ENDPOINT must match the existing Foundry resource/project ($expected)."
        }
        if ($deployment -notin $allowed) {
            throw "AI_MODEL_DEPLOYMENT=$deployment is absent from AI_ALLOWED_DEPLOYMENTS."
        }
        Write-Host "Checking existing Foundry account and model (read-only)..."
        Invoke-LocalAz @('cognitiveservices', 'account', 'show', '-g', $script:FoundryGroup,
            '-n', $name, '--query', '{name:name,kind:kind,location:location}', '-o', 'table')
        Invoke-LocalAz @('cognitiveservices', 'account', 'deployment', 'show', '-g', $script:FoundryGroup,
            '-n', $name, '--deployment-name', $deployment,
            '--query', '{name:name,model:properties.model.name,capacity:sku.capacity}', '-o', 'table')
    }

    # _common.ps1 has already loaded existing .env, without overwriting shell values.
    # Before redirecting AZURE_RESOURCE_GROUP, save the existing Foundry RG.
    $script:FoundryGroup = if ($env:FOUNDRY_RESOURCE_GROUP) {
        $env:FOUNDRY_RESOURCE_GROUP
    } else {
        Get-RequiredEnv 'AZURE_RESOURCE_GROUP'
    }
    Set-DefaultEnv 'ACA_RESOURCE_GROUP' 'rg-football-aca-test'
    $script:AcaGroup = Get-RequiredEnv 'ACA_RESOURCE_GROUP'
    if ($script:AcaGroup -ieq $script:FoundryGroup) {
        throw 'ACA_RESOURCE_GROUP must differ from FOUNDRY_RESOURCE_GROUP. Protect the existing Foundry resource group.'
    }
    Set-DefaultEnv 'AZURE_LOCATION' 'westus3'
    Set-DefaultEnv 'PROJECT_TAG' 'football-insights'
    # Hackathon judging continues through November 10, 2026 (Pacific).
    # Retain the ACA-only environment until at least November 12 for verification.
    # This is a resource tag only; it does not schedule automatic teardown.
    # The old local .env can still say 2026-10-27, so a default alone is unsafe.
    $minimumTeardownDate = [datetime]::ParseExact('2026-11-12', 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    $configuredTeardownDate = [Environment]::GetEnvironmentVariable('TEARDOWN_DATE')
    if ([string]::IsNullOrWhiteSpace($configuredTeardownDate)) {
        $env:TEARDOWN_DATE = '2026-11-12'
    } else {
        $parsedTeardownDate = [datetime]::MinValue
        if (-not [datetime]::TryParseExact($configuredTeardownDate, 'yyyy-MM-dd',
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::None, [ref]$parsedTeardownDate)) {
            throw 'TEARDOWN_DATE must use YYYY-MM-DD format.'
        }
        if ($parsedTeardownDate -lt $minimumTeardownDate) {
            Write-Warning "ACA-only TEARDOWN_DATE=$configuredTeardownDate is before 2026-11-12. Using 2026-11-12 for this run; update your ignored .env."
            $env:TEARDOWN_DATE = '2026-11-12'
        }
    }
    Write-Host "ACA-only planned teardown-date tag: $env:TEARDOWN_DATE (manual cleanup only)"
    if (-not $env:AZURE_SUBSCRIPTION_ID) {
        $env:AZURE_SUBSCRIPTION_ID = (az account show --query id -o tsv)
    }
    $subscriptionId = Get-RequiredEnv 'AZURE_SUBSCRIPTION_ID'
    $suffix = ($subscriptionId -replace '[^a-zA-Z0-9]', '').ToLowerInvariant()
    if ($suffix.Length -lt 8) { throw 'Invalid AZURE_SUBSCRIPTION_ID.' }
    $suffix = $suffix.Substring(0, 8)
    Set-DefaultEnv 'ACR_NAME' "frdacr$suffix"
    Set-DefaultEnv 'STORAGE_ACCOUNT_NAME' "frdst$suffix"
    Set-DefaultEnv 'LOG_ANALYTICS_NAME' 'log-football-aca'
    Set-DefaultEnv 'APPINSIGHTS_NAME' 'appi-football-aca'
    Set-DefaultEnv 'ACA_ENVIRONMENT_NAME' 'aca-football-demo'
    Set-DefaultEnv 'ACA_WEB_APP_NAME' 'football-web'
    Set-DefaultEnv 'ACA_INSIGHTS_APP_NAME' 'football-insights'
    Set-DefaultEnv 'ACA_INGEST_JOB_NAME' 'football-ingest'
    Set-DefaultEnv 'ACA_WEB_IDENTITY_NAME' 'id-football-aca-web'
    Set-DefaultEnv 'ACA_INSIGHTS_IDENTITY_NAME' 'id-football-aca-insights'
    Set-DefaultEnv 'ACA_INGEST_IDENTITY_NAME' 'id-football-aca-ingest'

    # Temporarily select ACA for shared helpers; finally restores the caller's environment.
    $env:AZURE_RESOURCE_GROUP = $script:AcaGroup
    $env:ACA_ONLY_MODE = 'true'
    # Resolve smoke and load-test targets from the isolated ACA group, never a legacy URL override.
    Remove-Item Env:ACA_WEB_URL -ErrorAction SilentlyContinue

    function Invoke-BasePreview {
        Assert-GroupExists $script:AcaGroup
        Invoke-AzChecked deployment group what-if -g $script:AcaGroup -n 'football-aca-base-preview' `
            --template-file (Get-InfraPath 'aca-isolated-base.bicep') `
            --parameters (Get-InfraPath 'aca-isolated-base.bicepparam')
    }
    function Invoke-FoundryAccess([bool]$Preview) {
        $base = Get-DeploymentOutputs 'football-aca-base'
        $principal = $base.acaInsightsPrincipalId.value
        $template = Get-InfraPath 'aca-foundry-access.bicep'
        $parameters = @("foundryAccountName=$($env:FOUNDRY_RESOURCE_NAME)", "insightsPrincipalId=$principal")
        if ($Preview) {
            Invoke-AzChecked deployment group what-if -g $script:FoundryGroup -n 'football-aca-foundry-access-preview' `
                --template-file $template --parameters @parameters
        } else {
            Invoke-AzChecked deployment group create -g $script:FoundryGroup -n 'football-aca-foundry-access' `
                --template-file $template --parameters @parameters --output none
            Write-Host 'ACA insights identity has Foundry User access. No Foundry model was changed.'
        }
    }
    function Invoke-AcaPreview {
        Import-DeploymentOutputs
        [void](Import-Digests)
        Assert-AllowedCidr
        $old = $env:ACA_DEPLOY_APPS
        try {
            foreach ($flag in @('false', 'true')) {
                $env:ACA_DEPLOY_APPS = $flag
                Write-Host "ACA deployment what-if: ACA_DEPLOY_APPS=$flag"
                Invoke-AzChecked deployment group what-if -g $script:AcaGroup -n "football-aca-preview-$flag" `
                    --template-file (Get-InfraPath 'aca.bicep') --parameters (Get-InfraPath 'aca.bicepparam')
            }
        } finally {
            if ($null -eq $old) { Remove-Item Env:ACA_DEPLOY_APPS -ErrorAction SilentlyContinue }
            else { $env:ACA_DEPLOY_APPS = $old }
        }
    }
    function Invoke-AcaSmokeOnly {
        $digests = Import-Digests
        $url = Get-AcaWebUrl
        $version = Test-Endpoint 'ACA' $url $digests
        if (-not $version) { throw 'Could not determine the curated data version from the ACA page.' }
        $fqdn = az containerapp show -g $script:AcaGroup -n (Get-RequiredEnv 'ACA_INSIGHTS_APP_NAME') `
            --query 'properties.configuration.ingress.fqdn' -o tsv
        if ($LASTEXITCODE -ne 0 -or $fqdn -notmatch '\.internal\.') {
            throw 'ACA insights ingress is not configured as internal.'
        }
        try {
            $status = [int](Invoke-WebRequest -Uri "https://$fqdn/healthz" -TimeoutSec 10 -SkipHttpErrorCheck).StatusCode
        } catch { $status = 0 }
        if ($status -eq 200) { throw 'ACA insights health endpoint is publicly reachable; expected 404 or no connection.' }
        Write-Host "ACA-only smoke PASS: health, readiness, data, digest, data version ($version), internal insights isolation."
        Write-Host "Web: $url"
        Write-Host 'Manually ask one live question in the browser to check the Foundry path.'
    }

    Set-DemoSubscription
    switch ($Command) {
        'check' {
            Write-Host "Subscription: $subscriptionId"
            Write-Host "Foundry RG (preserved): $script:FoundryGroup"
            Write-Host "ACA RG (isolated): $script:AcaGroup"
            Write-Host "Region: $env:AZURE_LOCATION"
            Write-Host "Registry: $env:ACR_NAME  Storage: $env:STORAGE_ACCOUNT_NAME"
            Write-Host "Model: $env:AI_MODEL_DEPLOYMENT"
            Test-FoundrySelection
            $exists = az group exists -n $script:AcaGroup
            Write-Host "ACA resource group exists: $exists"
            if ($exists -eq 'true') {
                az resource list -g $script:AcaGroup --query '[].{name:name,type:type}' -o table
            }
        }
        'init-group' {
            Test-FoundrySelection
            if ((az group exists -n $script:AcaGroup) -eq 'true') {
                Write-Host "ACA group already exists: $script:AcaGroup (unchanged)"
            } else {
                Invoke-AzChecked group create -n $script:AcaGroup -l $env:AZURE_LOCATION `
                    --tags "project=$env:PROJECT_TAG" 'purpose=aca-only-test' --output none
                Write-Host "Created empty ACA resource group: $script:AcaGroup"
            }
        }
        'plan-base' { Test-FoundrySelection; Invoke-BasePreview }
        'deploy-base' {
            Test-FoundrySelection
            Assert-GroupExists $script:AcaGroup
            Invoke-GroupDeployment 'football-aca-base' 'aca-isolated-base.bicep' 'aca-isolated-base.bicepparam'
            Write-Host 'ACA-only registry, storage, monitoring, and identities ready.'
        }
        'plan-foundry-access' { Invoke-FoundryAccess $true }
        'grant-foundry-access' { Invoke-FoundryAccess $false }
        'upload-data' { Invoke-UploadData }
        'build-push' { Invoke-BuildPush }
        'plan-aca' { Invoke-AcaPreview }
        'deploy-aca' { Assert-AllowedCidr; Invoke-AcaDeploy }
        'smoke' { Invoke-AcaSmokeOnly }
        'load-test' { Invoke-LoadTest -Platform 'aca' -Rps 5 -Seconds 30 }
        default {
            Write-Host 'Usage: .\demo\scripts\aca-only.ps1 <command>'
            Write-Host '  check, init-group, plan-base, deploy-base, plan-foundry-access, grant-foundry-access,'
            Write-Host '  upload-data, build-push, plan-aca, deploy-aca, smoke, load-test'
            throw "Unknown ACA-only command: $Command"
        }
    }
} finally {
    foreach ($name in [Environment]::GetEnvironmentVariables('Process').Keys) {
        if (-not $acaEnvironmentBefore.Contains($name)) {
            Remove-Item -LiteralPath "Env:$name"
        }
    }
    foreach ($name in $acaEnvironmentBefore.Keys) {
        [Environment]::SetEnvironmentVariable($name, $acaEnvironmentBefore[$name], 'Process')
    }
}
