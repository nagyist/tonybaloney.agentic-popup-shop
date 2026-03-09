# Copilot Instructions for `agentic-popup-shop`

These instructions apply to the **entire repository**.

## Package/tooling policy (mandatory)

- **Always use `uv` for Python dependency management and execution.**
- Do **not** use `pip`, `poetry`, or `python -m pip` unless explicitly requested.
- Prefer:
  - `uv run ...` for running commands
  - `uv add ...` for adding dependencies
  - `uv remove ...` for removing dependencies
  - `uv sync` when dependency state needs alignment
- If running from repo root where there is no root Python project, use either:
  - `Set-Location` into the target subproject first, then `uv ...`, or
  - `uv run --project <subproject-path> ...`.

## Monorepo subprojects

This repo contains multiple Python subprojects. Run commands in the correct folder:

- `app/agents` → agent workflows and agent tests
- `app/api` → FastAPI API service and API tests
- `app/mcp` → MCP servers and MCP tests
- `app/shared` → shared package
- `app/data` → data generation package

When making changes, scope installs/tests/commands to the specific subproject impacted.

## Test commands

Use `uv` commands scoped to each subproject:

- Agents tests: `Set-Location app/agents; uv run --prerelease=allow pytest`
- API tests: `Set-Location app/api; uv run --prerelease=allow pytest`
- MCP tests: `Set-Location app/mcp; uv run --prerelease=allow pytest`

If only one module is changed, run the smallest relevant test first.

## Agent Framework upgrade context

This repo may track pre-release Agent Framework packages.

- Prefer consistent version pinning across affected subprojects.
- Before changing Agent Framework versions, run baseline tests; then run post-change tests.
- Consult official upgrade notes for breaking changes when upgrading major/pre-release versions.

## MCP local servers

If MCP services are needed for local validation, prefer VS Code tasks already defined in the workspace (instead of ad-hoc shell scripts) when available.

## Change discipline

- Keep changes focused and minimal.
- Avoid unrelated refactors.
- Update only affected subprojects and verify with scoped tests.
