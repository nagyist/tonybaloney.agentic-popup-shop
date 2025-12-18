targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention.')
param environmentName string

@minLength(1)
@description('Primary location for all resources.')
param location string

// Used by azd for upsert/create calls
param webAppExists bool = false

param resourceGroupName string = ''

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
}

// Organize resources in a resource group
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: !empty(resourceGroupName) ? resourceGroupName : 'rg-${environmentName}'
  location: location
  tags: tags
}

// Monitor application with Azure Monitor
module monitoring 'br/public:avm/ptn/azd/monitoring:0.2.1' = {
  name: 'monitoring'
  scope: rg
  params: {
    applicationInsightsName: 'appi-${resourceToken}'
    logAnalyticsName: 'loga-${resourceToken}'
    applicationInsightsDashboardName: 'appi-dash-${resourceToken}'
    location: location
    tags: tags
  }
}

module containerApps 'br/public:avm/ptn/azd/container-apps-stack:0.3.0' = {
  name: 'container-apps'
  scope: rg
  params: {
    containerAppsEnvironmentName: 'ame-${resourceToken}'
    containerRegistryName: 'acr-${resourceToken}'
    logAnalyticsWorkspaceName: monitoring.outputs.logAnalyticsWorkspaceName
    appInsightsConnectionString: monitoring.outputs.applicationInsightsConnectionString
    acrSku: 'Basic'
    location: location
    acrAdminUserEnabled: true
    zoneRedundant: false
    tags: tags
  }
}

module webIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.3' = {
  name: 'webidentity'
  scope: rg
  params: {
    name: 'idweb-${resourceToken}'
    location: location
  }
}

module web 'br/public:avm/ptn/azd/container-app-upsert:0.2.0' = {
  name: 'web-container-app'
  scope: rg
  params: {
    name: 'web-${resourceToken}'
    tags: union(tags, { 'azd-service-name': 'web' })
    location: location
    containerAppsEnvironmentName: containerApps.outputs.environmentName
    containerRegistryName: containerApps.outputs.registryName
    ingressEnabled: true
    identityType: 'UserAssigned'
    exists: webAppExists
    containerName: 'main'
    identityName: webIdentity.name
    userAssignedIdentityResourceId: webIdentity.outputs.resourceId
    containerMinReplicas: 1
    identityPrincipalId: webIdentity.outputs.principalId
  }
}
