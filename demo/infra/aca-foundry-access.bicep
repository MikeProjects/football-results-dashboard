// Deploy only in the EXISTING Foundry resource group.
// This modifies no Foundry account or model: it grants ACA insights its user role.
targetScope = 'resourceGroup'

param foundryAccountName string
param insightsPrincipalId string

var foundryUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')

resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' existing = {
  name: foundryAccountName
}

resource insightsFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, insightsPrincipalId, foundryUserRoleId)
  scope: foundry
  properties: {
    roleDefinitionId: foundryUserRoleId
    principalId: insightsPrincipalId
    principalType: 'ServicePrincipal'
  }
}
