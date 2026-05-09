# AIManager — Project Overview

Python monolith: FastAPI platform (`src/main.py`) + Telegram bot (`run_bot.py`).
Five pluggable apps share a common agent + memory infrastructure.

## Entry Points
- `src/main.py` — FastAPI server (port 8000), mounts all five apps
- `run_bot.py` — Telegram bot (uses the same agent/memory infrastructure)

## App Layer (`src/apps/`)
Five independent apps. **Apps must never import from each other.**

| App | Route prefix | Purpose |
|-----|-------------|---------|
| chat | `/apps/chat` | Conversational interface + session management |
| explorer | `/apps/explorer` | Knowledge graph visualization & system status |
| credits | `/apps/credits` | LLM quota management |
| financial_manager | `/apps/financial-manager` | Finance workflows (stub) |
| routine_scheduler | `/apps/routine-scheduler` | Scheduling/automation (stub) |

## The Three Shared Singletons
Everything flows through these — nothing else should be imported from core internals.

| Singleton | Import path | What it does |
|-----------|------------|--------------|
| `settings` | `src.core.config` | All config (env vars, API keys, DB URIs) |
| `memory_manager` | `src.memory.manager` | ChromaDB + Neo4j facade |
| `agent_service` | `src.agent_platform.public.agent_service` | Agent gateway for apps |

## The Golden Rule for Apps
**Apps import from:**
- `src.agent_platform.public.contracts` — `AgentRunRequest`, `AgentRunResult`
- `src.agent_platform.public.agent_service` — `agent_service`
- `src.memory.manager` — `memory_manager` (public methods only, no `.neo4j.*` or `.chroma.*`)
- `src.core.config` — `settings`

**Apps do NOT import from:**
- `src.core.router`, `src.core.agent`, `src.core.context`, `src.core.limiter`
- Other apps (`src.apps.*`)
- `memory_manager.neo4j.*` or `memory_manager.chroma.*` — always use the public methods

## Project Structure
```
src/
  apps/              # Five pluggable feature apps (see src/apps/*/CLAUDE.md)
  agent_platform/
    public/          # Public gateway — contracts + agent_service (see CLAUDE.md inside)
    tools/           # Agent tools: beliefs, graph, memory, tasks (see CLAUDE.md inside)
  core/              # LLM routing, config, rate limiting — INTERNAL, see src/core/CLAUDE.md
  memory/            # ChromaDB + Neo4j stores — INTERNAL, see src/memory/CLAUDE.md
  platform/          # FastAPI factory + app registry
  bot/               # Telegram bot
  frontend/          # Static UI assets
```

## Running
```bash
python src/main.py    # Web platform
python run_bot.py     # Telegram bot
pytest tests/         # Test suite
```
