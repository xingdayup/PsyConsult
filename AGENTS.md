# AGENTS.md

Quick reference for ZCode agents working in this repo. Detailed docs: `CLAUDE.md` (root), `front/clinical_cds/CLAUDE.md`, and `learn/01`–`15` (Chinese study guide).

## Project

精神科临床决策支持系统原型 (psychiatric clinical decision support prototype) — LangGraph multi-agent reasoning + FastAPI backend + Vue 3 frontend, streaming clinical advice over SSE.

## Layout

- `agent/` — LangGraph multi-agent core. `agents/` (orchestrator, diagnosis, treatment, drug_review), `core/workflow/` (StateGraph assembly + history compression, AgentState, `checkpointer.py` = AsyncRedisSaver factory), `core/memory/` (Milvus long-term clinical facts + LLM extraction), `core/graph/` (Neo4j KG), `tools/`, `config/settings.py`
- `app/` — FastAPI API layer. `app_main.py`, `router/chat.py` (`POST /api/chat`), `service/chat_service.py` (SSE, cache, memory), `infra/` (Milvus semantic cache, logging), `app_config/settings.py`, `test/`
- `front/clinical_cds/` — Vue 3 + TypeScript + Vite SPA (Element Plus, marked + DOMPurify)
- `docker/` — compose file for Redis, Milvus, Neo4j, MySQL
- `mock_data/` — clinical guidelines, ICD-11 criteria, drug data
- `learn/` — Chinese study guide (project walkthrough + interview prep)

## Commands

```bash
# Infrastructure
cd docker && docker compose up -d

# Python (use system Python 3.12; see gotchas below)
pip install -r agent/requirements.txt
python -m compileall -q agent app        # syntax check without executing
python -c "import app.app_main; print('ok')"   # import check
python -m pytest -q                      # tests: pytest.ini -> testpaths = app/test

# Backend (listens on 127.0.0.1:5000, SSE at POST /api/chat)
python -m uvicorn app.app_main:app --host 0.0.0.0 --port 5000 --reload

# Agent CLI
cd agent && python main.py [--query "..."]

# Frontend (in front/clinical_cds/)
npm run dev          # Vite dev server -> http://localhost:5173
npm run type-check   # vue-tsc --build
npm run build        # type-check + build (use as the frontend validation gate)
```

## Architecture boundaries

- Three layers: `agent/` (reasoning) ← `app/` (API/SSE) ← `front/` (UI). Keep reasoning logic in `agent/`; `app/` only handles HTTP, auth, caching, and streaming.
- `app_main.py` and `chat_service.py` insert `agent/` into `sys.path`, so the app layer imports agent modules directly (`from config import get_settings`, `from core.workflow.graph_manager import AgentGraphManager`).
- **Two separate Settings classes**, both reading `agent/.env` with different fields: `agent/config/settings.py` (`@lru_cache` `get_settings()`, used by agents) and `app/app_config/settings.py` (module-level singleton, used by FastAPI). Don't merge them casually.
- Agent graph flow: `START → history_compression` (checkpoint mode only) `→ orchestrator` routes to `differential_diagnosis → treatment_recommend → drug_interaction → END` (branches can start mid-chain). State passed via `AgentState` TypedDict; `messages` uses the `add_messages` reducer.
- **Session state**: LangGraph Checkpoint + Redis (`core/workflow/checkpointer.py`), `session_id` as `thread_id`. Each turn passes only the new `HumanMessage`; history, intermediate results, and tool context accumulate in the checkpoint (24h TTL, refreshed on read). Redis down → graph runs stateless.
- **Context length control**: when messages exceed 16, the `history_compression` node summarizes all but the last 8 into one `SystemMessage` (short window + history summary).
- **Long-term memory**: every 5 turns, clinical facts (主诉/诊断/用药/量表) are extracted from the checkpointed history into Milvus and injected as `memory_context` on later turns.
- Semantic cache: Milvus collection `qa_semantic_cache`, checked before the agent graph runs (exact match + similarity threshold 0.08). Hits return cached answers directly, but the turn is still recorded into the checkpoint via `aupdate_state` to preserve multi-turn continuity.
- Frontend has **no vue-router** — the entire app is one `App.vue` (~820 lines) with local `ref` state; three-column layout; `@/` alias maps to `src/`.

## Conventions

- Logging: agent layer uses `logging.getLogger("clinical_cds.agent")`, app layer `logging.getLogger("clinical_cds.chat")`; both go to console + `logs/backend.log` (5MB rotating, 5 backups).
- Auth: `API_AUTH_TOKEN` (in `agent/.env`) enables mandatory Bearer token checks (`secrets.compare_digest`); `X-User-Id` must match `^[A-Za-z0-9_.:-]{1,128}$`. Chat input must be ≥4 non-whitespace chars.
- Frontend security: all Markdown rendered with `marked` must pass through `DOMPurify` first.
- Frontend styling: scoped CSS, `oklch()` colors, `:deep()` to pierce Element Plus internals. Element Plus is globally registered (`<el-*>` tags); icons imported per-use from `@element-plus/icons-vue`.
- Frontend auth token comes from `VITE_API_AUTH_TOKEN` in `front/clinical_cds/.env.local`.

## Gotchas

- `agent/.env` is **gitignored and absent after clone** — the backend won't start without it. Minimum keys: `DASHSCOPE_API_KEY`, `REDIS_URL`, `MILVUS_HOST/PORT`, `NEO4J_URI/USER/PASSWORD`, `API_AUTH_TOKEN`, `CORS_ORIGINS`. Never commit real keys or patient data.
- The venv path in `CLAUDE.md` (`E:\000WORK\...\cloud_agent\.venv`) is **stale and does not exist**. Use system Python 3.12 or create a fresh venv.
- Redis/Milvus being down must not break inference — the checkpointer, semantic cache, and long-term memory all degrade gracefully by design; preserve that when editing memory/workflow code. Long-term clinical facts are extracted in the background every 5 turns.
- Frontend verification gate is `npm run type-check && npm run build` (there are no frontend unit tests).
- Agent-layer scripts in `agent/test/` are manual/ad-hoc, not pytest suites; the pytest suite lives in `app/test/` only.

## Docs to read before sensitive changes

- Auth/security: `learn/12-security-engineering/`, `app/test/test_chat_security.py`
- Agent workflow/memory: `learn/04-state-graph/` … `learn/08-long-term-memory/`
- Frontend: `front/clinical_cds/CLAUDE.md`
- Troubleshooting: `learn/10-e2e-verification/`, `learn/11-pitfalls/`
