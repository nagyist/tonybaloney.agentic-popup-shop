# Agentic Popup shop

This is a multi-service application designed to showcase integration of agents into an existing application.

- Simple chat agents with a ChatKit interface
- A multi-agent workflow
- Integration of MCP servers into agents
- Using tracing to monitor multi-agent workflows

## Requirements

The easiest way to fulfill the requirements is to launch this as a Code Space or DevContainer, then you can skip this section.

IF you aren't using DevContainers, you will need to install:

- .NET 10 SDK
- Python 3.13
- uv 
- Node.JS 20

### Windows Setup

```console
winget install Microsoft.DotNet.SDK.10
winget install Python.Python.3.13
winget install --id=astral-sh.uv  -e
winget install OpenJS.NodeJS.22
Invoke-Expression "& { $(Invoke-RestMethod https://aspire.dev/install.ps1) }"
```

Close the terminal and reopen it so that PATH changes take effect. Clone the repo then you're ready to go.

## Starting the app

1. Copy .env.example to .env and fill in the required environment variables.
2. Run `aspire run` to start Aspire dashboard
3. Open the Aspire dashboard (see console output for URL) to start/stop modules and view logs.

## Using the app

Once aspire and the services have started, open the URL for the frontend site (`http://localhost:28000/` by default) to navigate the store.

## Deployment

To deploy, use the Azure Developer CLI.

```
azd init --template ./
azd up
```

### Adding ChatKit Domain Key

This is required for the user chat agent.To generate a key you need a developer account with [OpenAI](https://platform.openai.com/signup).

Then you need to register a key and the domain, at [Configure Domain Allow List](https://platform.openai.com/settings/organization/security/domain-allowlist).

Once you have done this, provision again with the key:

```
azd env set CHATKIT_DOMAIN_KEY=
azd up
```