targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention.')
param environmentName string

@minLength(1)
@description('Primary location for all resources.')
param location string

@description('Chatkit domain key for the application. Get from openai.com')
param chatkitDomainKey string = ''

// Used by azd for upsert/create calls
param webAppExists bool = false
param apiAppExists bool = false
param supplierMcpAppExists bool = false
param financeMcpAppExists bool = false

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
    publicNetworkAccess: 'Enabled'
    containerAppsEnvironmentName: 'ame-${resourceToken}'
    containerRegistryName: 'acr${resourceToken}'
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

module financeMcp 'br/public:avm/ptn/azd/container-app-upsert:0.2.0' = {
  name: 'finance-mcp-container-app'
  scope: rg
  params: {
    name: 'finance-mcp-${resourceToken}'
    tags: union(tags, { 'azd-service-name': 'finance-mcp' })
    location: location
    containerAppsEnvironmentName: containerApps.outputs.environmentName
    containerRegistryName: containerApps.outputs.registryName
    ingressEnabled: true
    identityType: 'SystemAssigned'
    exists: financeMcpAppExists
    containerName: 'main'
    containerMinReplicas: 1
    env:[
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: monitoring.outputs.applicationInsightsConnectionString
      }
      {
        name: 'PORT'
        value: '80'
      }
    ]
  }
}

module supplierMcp 'br/public:avm/ptn/azd/container-app-upsert:0.2.0' = {
  name: 'supplier-mcp-container-app'
  scope: rg
  params: {
    name: 'supplier-mcp-${resourceToken}'
    tags: union(tags, { 'azd-service-name': 'supplier-mcp' })
    location: location
    containerAppsEnvironmentName: containerApps.outputs.environmentName
    containerRegistryName: containerApps.outputs.registryName
    ingressEnabled: true
    identityType: 'SystemAssigned'
    exists: supplierMcpAppExists
    containerName: 'main'
    containerMinReplicas: 1
    env:[
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: monitoring.outputs.applicationInsightsConnectionString
      }
      {
        name: 'PORT'
        value: '80'
      }
    ]
  }
}

module aiFoundry 'br/public:avm/ptn/ai-ml/ai-foundry:0.6.0' = {
  scope: rg
  name: 'ai-foundry'
  params: {
    baseName: substring(resourceToken, 0, 12)
    aiModelDeployments: [
      {
        model: {
          format: 'OpenAI'
          name: 'gpt-4.1-mini'
          version: '2025-04-14'
        }
        name: 'gpt-4.1-mini'
        sku: {
          capacity: 1
          name: 'Standard'
        }
      }
    ]
  }
}

module apiIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.3' = {
  name: 'apiidentity'
  scope: rg
  params: {
    name: 'idapi-${resourceToken}'
    location: location
  }
}

module api 'br/public:avm/ptn/azd/container-app-upsert:0.2.0' = {
  name: 'api-container-app'
  scope: rg
  params: {
    name: 'api-${resourceToken}'
    tags: union(tags, { 'azd-service-name': 'api' })
    location: location
    containerAppsEnvironmentName: containerApps.outputs.environmentName
    containerRegistryName: containerApps.outputs.registryName
    ingressEnabled: true
    identityType: 'UserAssigned'
    identityName: apiIdentity.name
    userAssignedIdentityResourceId: apiIdentity.outputs.resourceId
    identityPrincipalId: apiIdentity.outputs.principalId
    exists: apiAppExists
    containerName: 'main'
    containerMinReplicas: 1
    targetPort: 8000
    env:[
      {
        name: 'AZURE_CLIENT_ID'
        value: apiIdentity.outputs.clientId
      }
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: monitoring.outputs.applicationInsightsConnectionString
      }
      {
        name: 'FINANCE_MCP_HTTP'
        value: financeMcp.outputs.uri
      }
      {
        name: 'SUPPLIER_MCP_HTTP'
        value: supplierMcp.outputs.uri
      }
      {
        name: 'AZURE_AI_PROJECT_ENDPOINT'
        value: 'https://${aiFoundry.outputs.aiServicesName}.services.ai.azure.com/api/projects/${aiFoundry.outputs.aiProjectName}'
      }
      {
        name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME'
        value: 'gpt-4.1-mini'
      }
    ]
  }
}

// Role assignment for this app to access the foundry account
module roleAssignment 'br/public:avm/res/authorization/role-assignment/rg-scope:0.1.1' = {
  scope: rg
  params: {
    principalId: apiIdentity.outputs.principalId
    roleDefinitionIdOrName: '/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d' // Azure AI User
    principalType: 'ServicePrincipal'
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
    env:[
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: monitoring.outputs.applicationInsightsConnectionString
      }
      {
        name: 'VITE_CHATKIT_DOMAIN_KEY'
        value: chatkitDomainKey
      }
      {
        name: 'API_HOST'
        value: replace(api.outputs.uri, 'https://', '')
      }
    ]
  }
}

output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.applicationInsightsConnectionString
output APPLICATIONINSIGHTS_NAME string = monitoring.outputs.applicationInsightsName
output AZURE_CONTAINER_ENVIRONMENT_NAME string = containerApps.outputs.environmentName
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerApps.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = containerApps.outputs.registryName
// output AZURE_KEY_VAULT_ENDPOINT string = keyVault.outputs.uri
// output AZURE_KEY_VAULT_NAME string = keyVault.outputs.name
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
// output API_BASE_URL string = useAPIM ? apimApi.outputs.serviceApiUri : api.outputs.uri
output REACT_APP_WEB_BASE_URL string = web.outputs.uri
// output SERVICE_API_NAME string = api.outputs.name
output SERVICE_WEB_NAME string = web.outputs.name
// output USE_APIM bool = useAPIM
// output SERVICE_API_ENDPOINTS array = useAPIM ? [ apimApi.outputs.serviceApiUri, api.outputs.uri ] : []
