# AGENTS Guide for `agentic-popup-shop`

This file defines the default operating rules for AI coding agents and contributors in this repository.

## Python tooling (mandatory)

- Always use `uv` for Python commands.
- Do not use `pip`, `poetry`, or `python -m pip` unless explicitly requested.
- Preferred commands:
  - `uv run ...`
  - `uv add ...`
  - `uv remove ...`
  - `uv sync`

If running from repo root (no root Python project), either:
- `Set-Location` into the target subproject first, then run `uv ...`, or
- use `uv run --project <subproject-path> ...`.

## Monorepo subprojects

Run commands in the subproject you are changing:

- `app/agents` — agent workflows + tests
- `app/api` — FastAPI API + tests
- `app/mcp` — MCP servers + tests
- `app/shared` — shared package
- `app/data` — data generation package

## Test commands

- Agents: `Set-Location app/agents; uv run --prerelease=allow pytest`
- API: `Set-Location app/api; uv run --prerelease=allow pytest`
- MCP: `Set-Location app/mcp; uv run --prerelease=allow pytest`

Prefer the smallest relevant test selection before running full suites.

## Agent Framework upgrades

- Keep Agent Framework versions consistent across affected subprojects.
- Run baseline tests before upgrades and post-upgrade tests after changes.
- Check official upgrade notes for breaking changes.

## MCP local validation

- Prefer existing VS Code tasks for starting/stopping MCP services when available.

## Change discipline

- Keep changes focused and minimal.
- Avoid unrelated refactors.
- Verify only affected subprojects unless broader validation is required.
