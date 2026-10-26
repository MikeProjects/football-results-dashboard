using './aca-isolated-base.bicep'

// All values are supplied by demo/scripts/aca-only.ps1, not committed credentials.
param location = readEnvironmentVariable('AZURE_LOCATION')
param projectTag = readEnvironmentVariable('PROJECT_TAG', 'football-insights')
param registryName = readEnvironmentVariable('ACR_NAME')
param storageAccountName = readEnvironmentVariable('STORAGE_ACCOUNT_NAME')
param logAnalyticsName = readEnvironmentVariable('LOG_ANALYTICS_NAME')
param appInsightsName = readEnvironmentVariable('APPINSIGHTS_NAME')
param acaWebIdentityName = readEnvironmentVariable('ACA_WEB_IDENTITY_NAME')
param acaInsightsIdentityName = readEnvironmentVariable('ACA_INSIGHTS_IDENTITY_NAME')
param acaIngestIdentityName = readEnvironmentVariable('ACA_INGEST_IDENTITY_NAME')
param operatorPrincipalId = readEnvironmentVariable('OPERATOR_PRINCIPAL_ID')
param foundryProjectEndpoint = readEnvironmentVariable('FOUNDRY_PROJECT_ENDPOINT')
