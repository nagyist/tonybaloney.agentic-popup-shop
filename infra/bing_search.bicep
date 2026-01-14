param account_name string = 'aiservicesy4si'
param bingSearchName string = 'bingsearch-${account_name}'


resource account_name_resource 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: account_name
  scope: resourceGroup()
}

// TODO: The Bing Account resources isn't published yet.
#disable-next-line BCP081
resource bingSearch 'Microsoft.Bing/accounts@2020-06-10' = {
  name: bingSearchName
  location: 'global'
  sku: {
    name: 'G1'
  }
  kind: 'Bing.Grounding'
}

resource bing_search_account_connection 'Microsoft.CognitiveServices/accounts/connections@2025-04-01-preview' = {
  name: '${account_name}-bingsearchconnection'
  parent: account_name_resource
  properties: {
    category: 'ApiKey'
    target: 'https://api.bing.microsoft.com/'
    authType: 'ApiKey'
    credentials: {
      key: '${bingSearch.listKeys().key1}'
    }
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      Location: bingSearch.location
      ResourceId: bingSearch.id
    }
  }
}
