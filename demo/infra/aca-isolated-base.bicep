// ACA-only shared infrastructure. Creates no Foundry resources and no AKS resources.
// Deploy only to a dedicated ACA resource group.
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param projectTag string = 'football-insights'
param registryName string
param storageAccountName string
param logAnalyticsName string
param appInsightsName string
param acaWebIdentityName string
param acaInsightsIdentityName string
param acaIngestIdentityName string
param operatorPrincipalId string
param foundryProjectEndpoint string

var tags = {
  project: projectTag
  purpose: 'aca-only-test'
}

var metricsPublisher = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
var blobReader = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
var blobContributor = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var acrPull = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    DisableLocalAuth: true
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-05-01-preview' = {
  name: registryName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
    networkRuleBypassOptions: 'AzureServices'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  name: 'default'
  parent: storage
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource rawContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  name: 'raw'
  parent: blobService
  properties: { publicAccess: 'None' }
}

resource curatedContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  name: 'curated'
  parent: blobService
  properties: { publicAccess: 'None' }
}

var identityNames = [
  acaWebIdentityName
  acaInsightsIdentityName
  acaIngestIdentityName
]

resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = [for name in identityNames: {
  name: name
  location: location
  tags: tags
}]

resource metricsAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, 3): {
  name: guid(appInsights.id, identityNames[i], metricsPublisher)
  scope: appInsights
  properties: {
    roleDefinitionId: metricsPublisher
    principalId: identities[i].properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource acrPullAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, 3): {
  name: guid(registry.id, identityNames[i], acrPull)
  scope: registry
  properties: {
    roleDefinitionId: acrPull
    principalId: identities[i].properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource insightsCuratedReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(curatedContainer.id, acaInsightsIdentityName, blobReader)
  scope: curatedContainer
  properties: {
    roleDefinitionId: blobReader
    principalId: identities[1].properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource ingestRawReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(rawContainer.id, acaIngestIdentityName, blobReader)
  scope: rawContainer
  properties: {
    roleDefinitionId: blobReader
    principalId: identities[2].properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource ingestCuratedWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(curatedContainer.id, acaIngestIdentityName, blobContributor)
  scope: curatedContainer
  properties: {
    roleDefinitionId: blobContributor
    principalId: identities[2].properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource operatorRawContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(rawContainer.id, operatorPrincipalId, blobContributor)
  scope: rawContainer
  properties: {
    roleDefinitionId: blobContributor
    principalId: operatorPrincipalId
    principalType: 'User'
  }
}

// These output names intentionally match the existing deployment scripts.
// No model deployment, capacity, or Foundry configuration is modified.
output foundryProjectEndpoint string = foundryProjectEndpoint
output applicationInsightsConnectionString string = appInsights.properties.ConnectionString
output registryLoginServer string = registry.properties.loginServer
output storageBlobEndpoint string = storage.properties.primaryEndpoints.blob
output acaInsightsPrincipalId string = identities[1].properties.principalId
output applicationInsightsId string = appInsights.id
output registryId string = registry.id
