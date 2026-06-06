# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

精神科临床决策支持系统原型 — 基于 LangGraph 的多智能体推理系统，Vue 3 前端 + FastAPI 后端，通过 SSE 流式返回诊疗建议。

## 常用命令

### 基础设施
```bash
cd docker && docker compose up -d          # 启动 Redis, Milvus, Neo4j, MySQL
docker compose -f docker/docker-compose.yml ps   # 检查容器状态
```

### Python 开发
使用虚拟环境 `E:\000WORK\学习文档\cloud_agent\.venv\Scripts\python.exe`。

```bash
# 安装依赖
pip install -r agent/requirements.txt

# 编译检查（不执行）
python -m compileall -q agent app

# 包导入检查
python -c "import app.app_main; print('ok')"

# 运行测试（pytest 配置在 pytest.ini：testpaths = app/test）
python -m pytest -q

# Agent CLI（交互模式 / 单次查询）
cd agent && python main.py
cd agent && python main.py --query "患者近两周情绪低落..."
```

### 前端开发
```bash
cd front/clinical_cds
npm install
npm run dev           # Vite 开发服务器 → http://localhost:5173
npm run type-check    # vue-tsc --build
npm run build         # 先 type-check 再构建
npm run build-only    # 仅 vite build
npm run preview       # 预览构建产物
```

### 启动后端
```bash
python -m uvicorn app.app_main:app --host 0.0.0.0 --port 5000 --reload
# 或直接运行
python app/app_main.py
```
后端监听 `http://127.0.0.1:5000`，聊天接口 `POST /api/chat`，返回 `text/event-stream`。

## 架构

### 核心数据流

```
Vue 前端 (Vite :5173)
  → POST /api/chat {query, user_id, session_id}
  → Bearer Token 鉴权 + X-User-Id 验证 (app/router/chat.py)
  → 输入长度校验 (≥4 个非空白字符)
  → 语义缓存检查 Milvus Collection: qa_semantic_cache (app/infra/cache.py)
    命中 → 直接返回缓存答案
    未命中 → 进入 LangGraph 多 Agent 工作流
  → 记忆上下文提取（Redis 短期 + Milvus 长期）
  → LangGraph Agent 图 (agent/core/workflow/graph_manager.py)
  → SSE 流式响应逐节点推送
  → 保存短期记忆到 Redis
```

### 三层结构

**`agent/`** — LangGraph 多智能体推理核心
- `agents/` — 领域 Agent：`orchestrator.py`（路由）、`diagnosis_agent.py`（鉴别诊断）、`treatment_agent.py`（治疗推荐）、`drug_review_agent.py`（药物审查）
- `core/workflow/` — `graph_manager.py`（StateGraph 组装）、`state.py`（AgentState TypedDict）
- `core/memory/` — `memory_manager.py`（统一入口）、`short_term.py`（Redis）、`long_term.py`（Milvus）、`preference_extractor.py`（LLM 偏好提取）
- `core/graph/` — Neo4j 知识图谱客户端、模型、解析器
- `core/mcp/` — MCP 工具管理
- `tools/` — `graph_tool.py`、`synonym_tool.py`、`vector_tool.py`
- `config/settings.py` — Pydantic Settings，用 `@lru_cache` 缓存的 `get_settings()`

**`app/`** — FastAPI 后端接口层
- `app_main.py` — FastAPI 应用、CORS、lifespan（启动时初始化 Agent 系统和缓存）
- `router/chat.py` — `/api/chat` 端点、Bearer Token 鉴权、X-User-Id 验证
- `service/chat_service.py` — SSE 流式响应、输入校验、语义缓存检查、Agent 图执行、记忆保存
- `schemas/chat.py` — ChatRequest 模型
- `infra/cache.py` — Milvus 语义缓存（L1 精确匹配 + L1 语义相似度，阈值 0.08）
- `infra/logging_config.py` — RotatingFileHandler（控制台 + `logs/backend.log`）
- `app_config/settings.py` — 单例 Settings，读取 `agent/.env`

**`front/clinical_cds/`** — Vue 3 + TypeScript + Vite
- 单页应用（无 vue-router），所有 UI 状态通过本地 `ref` 管理
- 三栏布局：左侧工作区导航、中间主工作台（SSE 消息面板 + 输入框）、右侧信息面板
- `@/` 路径别名映射到 `src/`
- DOMPurify 渲染 Markdown，marked 解析
- 前端通过 `.env.local` 配置 `VITE_API_AUTH_TOKEN`

### Agent 图编排（LangGraph StateGraph）

```
START → orchestrator（路由 LLM 判断意图）
           ├─→ differential_diagnosis → treatment_recommend → drug_interaction → END
           ├─→ treatment_recommend     → drug_interaction → END
           └─→ drug_interaction        → END
```

状态在 `AgentState` TypedDict 中传递：`messages`、`next_agent`、`user_id`、`session_id`、`memory_context`、`metadata`。

### 关键设计点

- **两套 Settings**：`agent/config/settings.py`（`@lru_cache`，Agent 使用）和 `app/app_config/settings.py`（模块级单例，FastAPI 使用），都读 `agent/.env`。两者字段不完全一致。
- **路径注入**：`app/app_main.py` 和 `app/service/chat_service.py` 都将 `agent/` 目录插入 `sys.path`，因此 app 层可以直接 `from config import get_settings`、`from core.workflow.graph_manager import AgentGraphManager`。
- **日志**：Agent 层用 `logging.getLogger("clinical_cds.agent")`；App 层用 `logging.getLogger("clinical_cds.chat")`，同时输出到控制台和 `logs/backend.log`（5MB 轮转，保留 5 个备份）。
- **记忆系统优雅降级**：Redis/Milvus 不可用时自动跳过，不阻塞推理流程。长期偏好每 5 轮异步提取。
- **鉴权**：`API_AUTH_TOKEN` 非空时强制 Bearer Token 验证（`secrets.compare_digest`）；`X-User-Id` 必须匹配 `^[A-Za-z0-9_.:-]{1,128}$`。
- **前端安全**：marked 渲染用户/GPT 内容前经过 DOMPurify 净化。

## 配置

所有后端配置集中在 `agent/.env`，最小配置：
```env
DASHSCOPE_API_KEY=你的Key
REDIS_URL=redis://localhost:6379
MILVUS_HOST=localhost
MILVUS_PORT=19530
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123
API_AUTH_TOKEN=local-dev-token
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

## 测试

- pytest 配置在 `pytest.ini`：`testpaths = app/test`，文件匹配 `test_*.py` / `*_test.py`
- 后端测试：`app/test/test_chat_security.py`（鉴权/鉴权测试）、`app/test/test_backend_logging.py`（日志配置测试）
- Agent 脚本式测试：`agent/test/clinical_test.py`、`agent/test/build_kg.py`、`agent/test/milvus_rag.py`
- 前端：`npm run type-check && npm run build` 作为验证门禁
