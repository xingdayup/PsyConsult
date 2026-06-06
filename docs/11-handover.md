# Clinical CDS 项目交接文档

## 项目概述

**精神科临床决策支持系统**，基于 LangGraph 多智能体架构，提供症状提取、ICD-11 鉴别诊断、分级治疗推荐和药物相互作用审查。前后端分离，SSE 流式输出。

- **前端**：Vue 3 + TypeScript + Element Plus，部署在 Cloudflare Pages
- **后端**：FastAPI + LangGraph 多 Agent，运行在本地 Windows 机器，通过 Cloudflare Tunnel 暴露公网
- **基础设施**：Docker 托管 Redis、Milvus、Neo4j、MySQL

## 工作内容总结

### 1. 流式架构改造（核心工作）

**问题**：前端 SSE 流式不工作——状态栏直接跳到最终步骤，LLM 回复内容一次性弹出，无增量展示效果。

**根因与修复**：
- `stream_mode="updates"` 只在节点完成后才推送 → 改为 `["updates", "custom"]` + `get_stream_writer()`，在节点启动时推状态、执行中逐 chunk 推内容
- `create_react_agent` 的 `prompt` 回调不传递 `state["messages"]` 给 LLM → 改为在 `__call__` 中手动拼接 `SystemMessage` + `messages`
- 工具调用期间长时间无内容 → 新增 `tool_call`/`tool_done` 状态推送，消除沉默期
- 每字符触发全量 markdown 重渲染致前端卡死 → 后端 buffer 积攒 20 字符或换行才推送（chunk 数从 4044 降至 ~200）
- Agent 标题每 chunk 重复拼接 → 仅 Agent 切换时拼接一次

### 2. Agent 状态管理修复

- `AgentState.messages` 的 reducer 从 `operator.add` 改为 `add_messages`，确保元组正确转换为 LangChain `BaseMessage`
- 所有消息初始化为 `HumanMessage(content=...)` 而非裸元组 `("user", ...)`

### 3. 提示词修复

- "记忆上下文为空"导致 DeepSeek 模型误判为"无任何输入" → 记忆区块仅在非空时展示
- 各 Agent 系统提示词增加"请从对话记录中读取"的显式引导
- 条件性展示记忆区块（`memory_block` 为空时不显示该段）

### 4. 代码清洗

- 删除教程模板注释（"小滴课堂"品牌信息）
- 删除废弃文件：`symptom_agent.py`、`react_agent_state.py`
- 删除过时文档目录 `docs_claude/`、`AGENTS.md`
- 清空所有 `__pycache__`
- 去敏处理：文档中个人路径替换为通用命令、API Key 在 gitignore 保护、`.env.local` 和 `CLAUDE.md` 从仓库移除

### 5. 文档建设

| 文档 | 内容 |
|------|------|
| `CLAUDE.md` | 完整架构说明、开发命令、数据流图、Agent 图编排 |
| `docs/08-usage-guide.md` | 本地启动全流程、鉴权配置、curl 测试、常见问题 |
| `docs/09-deployment-guide.md` | Cloudflare Pages + Railway 部署指南 |
| `docs/10-ops-guide.md` | 后端运维：启停、NSSM 服务、日志、故障排查 |

### 6. Git 管理

- 合并 `codex/hardening-baseline` 到 `master`
- 4 次提交，工作区清洁
- 仓库：`github.com/xingdayup/PsyConsult`

### 7. 部署

- **前端**：Cloudflare Pages（`psyconsult.pages.dev`），Git 自动部署
- **后端**：本地 Windows + cloudflared 隧道（`trycloudflare.com`）
- **数据库**：Docker Compose 本地托管（Redis、Milvus、Neo4j、MySQL）

## 技术架构

```
用户浏览器 → psyconsult.pages.dev (Cloudflare Pages)
                  ↓ POST /api/chat (SSE)
           xxx.trycloudflare.com (Cloudflare Tunnel)
                  ↓
         localhost:5002 (uvicorn)
                  ↓
    ┌─────────────┼─────────────┐
    ↓             ↓             ↓
  Redis        Milvus        Neo4j       MySQL
 (短期记忆)   (向量检索+缓存) (知识图谱)  (待接入)
```

### LangGraph Agent 流水线

```
START → orchestrator (路由)
           ├─→ differential_diagnosis (症状提取+ICD-11诊断)
           ├─→ treatment_recommend   (指南检索+分级治疗)
           └─→ drug_interaction      (药物相互作用审查)
```

## 当前状态

| 组件 | 地址 | 状态 |
|------|------|------|
| 前端 | https://psyconsult.pages.dev | 🟢 在线 |
| 后端 | https://xxx.trycloudflare.com | 🟢 在线 |
| Redis | localhost:6379 | 🟢 |
| Milvus | localhost:19530 | 🟢 |
| Neo4j | localhost:7474 | 🟢 |
| MySQL | localhost:3306 | 🟡 已配置，代码层待接入 |

## 待办事项

1. **固定域名隧道**：快速隧道每次重启 URL 会变，需注册域名 + named tunnel（参考 `docs/10-ops-guide.md` 第 7 节）
2. **NSSM 服务注册**：目前后端和隧道靠终端跑，重启需手动重开（参考 `docs/10-ops-guide.md` 第 3 节）
3. **MySQL 接入**：已配置但代码层未使用，规划存患者画像、就诊记录、量表分数（`CLAUDE.md` 已注明）
4. **`create_react_agent` 升级**：当前使用已废弃的 `langgraph.prebuilt.create_react_agent`，应迁移到 `langchain.agents.create_agent`
5. **向量数据库方案**：部署到 Railway 等云平台时 Milvus 不在其 Marketplace，需换 Zilliz Cloud 或 pgvector

## 关键文件索引

| 文件 | 作用 |
|------|------|
| `agent/core/workflow/graph_manager.py` | LangGraph 图组装 |
| `agent/core/workflow/state.py` | AgentState 定义 |
| `agent/agents/diagnosis_agent.py` | 诊断 Agent（含流式+工具状态） |
| `agent/agents/treatment_agent.py` | 治疗推荐 Agent |
| `agent/agents/drug_review_agent.py` | 药物审查 Agent |
| `agent/agents/orchestrator.py` | 路由 Agent |
| `app/service/chat_service.py` | SSE 流式处理核心 |
| `app/router/chat.py` | API 路由+鉴权+防缓冲 header |
| `front/clinical_cds/src/App.vue` | 前端全部逻辑（单页应用） |
| `agent/.env` | 后端配置（API Key、数据库连接、CORS） |

---

**版本**：master @ `3da885a` | **日期**：2026-06-06
