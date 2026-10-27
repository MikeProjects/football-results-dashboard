# ACA-only deployment with existing Foundry (isolated resource group)

This is the intentionally **ACA-only** alternative to [DEPLOYMENT.md](DEPLOYMENT.md). It uses the current
Foundry model deployment and does not create or update an AKS cluster, Foundry account, Foundry project,
model deployment, or model quota. It creates only the required infrastructure for Azure Container Apps
in its **own resource group**, plus one explicit managed-identity role assignment on the existing
Foundry account.

**Do not run `demo azure-foundation`, `demo azure-platform`, `demo smoke`, `demo preflight`,
`demo switch-model`, `demo reset`, or `demo teardown` for this path.** Those commands were
designed for the original two-platform setup. In particular, `demo teardown` deletes the entire
configured resource group. Use `aca-only.ps1` for this test.

## Boundaries

| Where | Changes |
| --- | --- |
| Existing Foundry resource group | One `Foundry User` role assignment for ACA's insights identity **only**. No changes to Foundry models, quota, or account. |
| Dedicated ACA resource group | Container Registry Basic, Storage (raw + curated), Log Analytics, workspace-based Application Insights, three ACA user-assigned identities with least-privilege roles, ACA environment, two apps, and ingest job. |
| Local Windows | Docker builds, short-lived environment configuration, and a dedicated, ignored `.local/deploy/aca-only-digests.json` artifact. Legacy `digests.json` (v1 rollback baseline) and `digests-v2.json` are not used by this workflow. |

The existing `demo/infra/aca.bicep` remains the application template.
`demo/infra/aca-isolated-base.bicep` creates shared infrastructure;
`demo/infra/aca-foundry-access.bicep` scopes the cross-resource-group Foundry role assignment.

## 0. Verify local Git and configure the session

Use PowerShell 7 in the repository root. Avoid resetting or discarding local edits when updating.

```powershell
git switch work/initial
git status --short
git pull --ff-only origin work/initial
```

The existing `.env` may already provide these settings. Confirm or add them **locally**;
do not commit `.env` or credentials:

```dotenv
AZURE_SUBSCRIPTION_ID=<your subscription ID>
AZURE_RESOURCE_GROUP=<existing Foundry resource group>
FOUNDRY_RESOURCE_GROUP=<existing Foundry resource group>
FOUNDRY_RESOURCE_NAME=<existing Foundry account name>
FOUNDRY_PROJECT_NAME=<existing project name>
FOUNDRY_PROJECT_ENDPOINT=<existing project endpoint>
AI_MODEL_DEPLOYMENT=gpt-5-mini-1
AI_ALLOWED_DEPLOYMENTS=gpt-5-mini-1
AZURE_LOCATION=westus3
ACA_RESOURCE_GROUP=rg-football-aca-test
EVENT_DATE=YYYY-MM-DD
TEARDOWN_DATE=YYYY-MM-DD
```

Replace both `YYYY-MM-DD` placeholders with actual dates before deploying the
billable foundation: `EVENT_DATE` is the event date, and `TEARDOWN_DATE` is the
planned resource cleanup date. Both are required by `aca.bicepparam` without
defaults, so leaving them empty makes `plan-aca` fail during parameter compilation.
These values are resource tags only; `TEARDOWN_DATE` does **not** schedule or
automatically perform resource removal. Follow the manual cleanup steps in section 7.

The script's ACA-only default group is `rg-football-aca-test`. It derives unused
registry/storage names from the subscription ID; override `ACR_NAME` and
`STORAGE_ACCOUNT_NAME` in the local `.env` if the generated names are already taken.
Any configured `ACA_*`, monitoring, and identity names take precedence over defaults.

`FOUNDRY_RESOURCE_GROUP` selects the existing Foundry group. If it is blank, the
script requires `AZURE_RESOURCE_GROUP` as a fallback. Setting
`FOUNDRY_RESOURCE_GROUP` explicitly is sufficient for this ACA-only selection;
the original two-platform commands still require `AZURE_RESOURCE_GROUP`.
`ACA_RESOURCE_GROUP` selects the separate application group and must differ from
the selected Foundry group.

If `check` reports `Set AZURE_RESOURCE_GROUP in .env`, neither Foundry group
selection was populated in the script's environment. Set `FOUNDRY_RESOURCE_GROUP`
in the repository-root `.env`, then rerun `check`. Copying or editing
`.env.example` alone does not configure the script. Existing shell environment
values take precedence over `.env`; clear or correct stale shell values before
retrying.

The template intentionally leaves resource names and endpoints blank. Obtain
the account and project names from your existing Foundry configuration; the
endpoint must match `https://<resource>.services.ai.azure.com/api/projects/<project>`.
Matching this URL structure does not confirm that the resources exist or that
your identity can access them. The next step checks the account and model
deployment in Azure; it does not verify the project's existence or invoke it.

The script runs in the current PowerShell process and temporarily points
`AZURE_RESOURCE_GROUP` to the isolated ACA group. It restores the caller's environment
in a `finally` block, including when a command fails. This covers existing values and
variables introduced by `.env`, defaults, and deployment outputs. The `.env` file is not rewritten.

## 1. Read-only checks

```powershell
.\demo\scripts\aca-only.ps1 check

# Compile all the Bicep files locally without creating deployment JSON files:
az bicep build --file demo/infra/aca-isolated-base.bicep --stdout | Out-Null
az bicep build --file demo/infra/aca-foundry-access.bicep --stdout | Out-Null
az bicep build --file demo/infra/aca.bicep --stdout | Out-Null
```

The `check` command verifies that the existing account and selected model deployment
exist; it does not call the model. Stop and fix any error before progressing.

## 2. Create an empty ACA group and preview billable resources

An empty resource group itself is not billed. The next command is a **cloud configuration change**,
but creates no Container Apps, VMs, registry, or storage yet.

```powershell
.\demo\scripts\aca-only.ps1 init-group
.\demo\scripts\aca-only.ps1 plan-base
```

`plan-base` performs Azure Resource Manager **what-if**. Inspect every resource listed
for creation. It should show no Foundry account, project, deployment, quota, or AKS cluster.
Do not deploy until this preview is understood and approved.

## 3. Create ACA-only foundation (starts potential Azure charges)

```powershell
.\demo\scripts\aca-only.ps1 deploy-base
```

This creates ACR, blob storage and containers, monitoring, and three ACA identities plus
their roles in the new ACA group. It does **not** deploy any new model.

Review the scoped role assignment before applying it to the existing Foundry account:

```powershell
.\demo\scripts\aca-only.ps1 plan-foundry-access
.\demo\scripts\aca-only.ps1 grant-foundry-access
```

What-if should show one role assignment to the existing Foundry account, not changes to
the account itself. Azure RBAC propagation can take several minutes.

## 4. Upload existing data and build/push images

```powershell
.\demo\scripts\aca-only.ps1 upload-data
.\demo\scripts\aca-only.ps1 build-push
```

Only CSVs under the two locally downloaded dataset folders are uploaded to the private
`raw` container. The build/push operation produces three container images (`web`,
`insights`, `ingest`) and records their immutable digests in
`.local/deploy/aca-only-digests.json`. The ACA-only `build-push`, `plan-aca`,
`deploy-aca`, and `smoke` commands use this dedicated file, rather than
overwriting or reading the legacy `.local/deploy/digests.json` rollback baseline
or `digests-v2.json` rollout file. If the ACA-only file is missing, these
commands fail instead of falling back to legacy image digests.

**Existing local checkouts:** Earlier ACA-only builds may have written their
digests to `digests.json`. This fix does not automatically recover any older
rollback baseline overwritten by that behavior. Do **not** blindly copy
`digests.json` to the new ACA-only filename: first independently verify the
registry, tag and digest values belong to the dedicated ACA deployment, or
rebuild/push intentionally when appropriate. Do not deploy or roll back using
uncertain digest metadata.

## 5. Restrict public access, review, deploy ACA

Set an allow-list for your current public IPv4 address. The request to api.ipify.org
is used only to learn your outward-facing IP; VPN routing can cause Azure to see another.

```powershell
$publicIp = (Invoke-RestMethod -Uri 'https://api.ipify.org').Trim()
$env:ALLOWED_CIDRS = "$publicIp/32"

.\demo\scripts\aca-only.ps1 plan-aca
.\demo\scripts\aca-only.ps1 deploy-aca
```

Both ACA what-if passes are previewed. Deployment uses the existing two-pass ACA process:
create environment and ingest job, run ingest, then create internal `insights` and external
`web`. The services use managed identities and the same `gpt-5-mini-1` model as local.

The allow-list restricts the **web endpoint** to the supplied IP(s); do not remove it
without an explicit reason.

## 6. ACA-only validation

```powershell
.\demo\scripts\aca-only.ps1 smoke
.\demo\scripts\aca-only.ps1 load-test
```

The isolated smoke checks health, readiness, data, image digest, data version, and that
the insights endpoint is not reachable publicly. The load test uses deterministic
pages at 5 RPS for 30 seconds, without Foundry model calls. Use the printed ACA HTTPS
URL to ask **one** live football question and verify narrative, grounding and evidence.
A live question incurs model charges; repeat the 102-case evaluation only if needed.

The existing `demo smoke`, `demo parity`, and deployed AKS/ACA parity pytest
are intentionally **not used** here, because they expect both platforms.

## 7. Cost control and safe removal

A resource group is an ownership boundary, not an automatic budget or spending cap.
ACR Basic and any always-on ACA replicas can accrue charges while idle. After taking
the needed evidence, verify which resources are in the **dedicated ACA group**:

```powershell
az resource list -g rg-football-aca-test -o table
```

To remove only the ACA test infrastructure, use Azure Portal **Resource groups** and
select the dedicated ACA group; carefully inspect its complete contents before confirming
deletion. **Never delete the Foundry resource group.** The Foundry User role assignment
on the existing Foundry account is independent; revoke it separately after the ACA
test if access is no longer needed.

This workflow does not automatically tear down resources; budget notifications are not
a hard spending cap. Use Azure Cost Management to monitor actual charges.
