# Repository Guidelines

## Project Structure & Module Organization
This repository contains a clinical decision support prototype with separate backend, agent, frontend, infrastructure, and data areas.

- `agent/`: LangGraph-style multi-agent system, CLI entrypoint, tools, MCP servers, memory, graph, and workflow code. Existing script-style tests live in `agent/test/`.
- `app/`: FastAPI application layer with routers, schemas, services, cache infrastructure, and `app_main.py`.
- `front/clinical_cds/`: Vite + Vue 3 + TypeScript frontend. Main source files are under `src/`.
- `docker/`: Local service definitions for Redis, Milvus, Neo4j, and MySQL.
- `mock_data/`: Markdown clinical guideline and drug reference data used for development and ingestion experiments.

## Build, Test, and Development Commands
Run infrastructure first when testing features that depend on storage or retrieval:

```bash
cd docker && docker compose up -d
```

Python setup and agent/API entrypoints:

```bash
cd agent && pip install -r requirements.txt
python main.py
python main.py --query "patient case text"
python test/clinical_test.py
python ../app/app_main.py
```

Frontend commands:

```bash
cd front/clinical_cds
npm install
npm run dev
npm run type-check
npm run build
npm run preview
```

## Coding Style & Naming Conventions
Use 4-space indentation for Python and keep modules in `snake_case.py`. Classes should use `PascalCase`; functions, variables, and async helpers should use `snake_case`. Keep agent responsibilities separated by domain in `agent/agents/`, and place shared workflow, graph, memory, or MCP logic under `agent/core/`.

Vue components should use `<script setup lang="ts">` where practical. TypeScript identifiers should use `camelCase` for variables/functions and `PascalCase` for components and types.

## Testing Guidelines
Existing tests are script-oriented and live in `agent/test/`, for example `clinical_test.py`, `build_kg.py`, and `milvus_rag.py`. Name new Python test scripts descriptively with a `_test.py` or `test_*.py` pattern. Prefer small tests that can run without external services; clearly document when Redis, Milvus, Neo4j, or model credentials are required. Use `npm run type-check` and `npm run build` before frontend changes are considered complete.

## Commit & Pull Request Guidelines
No Git history is available in this workspace, so use concise imperative commit messages such as `Add graph ingestion test` or `Fix chat response schema`. Pull requests should include a short purpose statement, commands run, environment or service requirements, linked issues when applicable, and screenshots for visible frontend changes.

## Security & Configuration Tips
Do not commit secrets or real patient data. Keep local credentials in environment files such as `agent/.env`, and use de-identified examples in `mock_data/` and tests.
