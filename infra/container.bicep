@description('Unique environment name used for resource naming.')
param appName string

@description('Primary location for all resources.')
param location string

param containerRegistryName string
param containerAppsEnvironmentName string
param imageName string
param identityId string

param tags object

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' existing = {
  name: containerRegistryName
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2022-03-01' existing = {
  name: containerAppsEnvironmentName
}

module api 'br/public:avm/res/app/container-app:0.19.0' = {
  params: {
    name: appName
    ingressTargetPort: 80
    scaleSettings: {
      minReplicas: 1
      maxReplicas: 10
    }
    containers: [
      {
        name: 'main'
        image: imageName
        resources: {
          cpu: json('0.5')
          memory: '1.0Gi'
        }
      }
    ]
    managedIdentities: {
      systemAssigned: false
      userAssignedResourceIds: [identityId]
    }
    registries: [
      {
        server: containerRegistry.properties.loginServer
        identity: identityId
      }
    ]
    environmentResourceId: containerAppsEnvironment.id
    location: location
    tags: tags
  }
}

output apiUrl string = api.outputs.fqdn
