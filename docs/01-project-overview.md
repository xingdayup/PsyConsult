# 项目总览与架构

## 项目目标

本项目实现了一个精神科临床决策支持系统原型。医生输入患者症状、诊断问题或用药方案后，系统通过多智能体流程完成：

- 症状结构化抽取。
- PHQ-9 / GAD-7 量表初步推断。
- 基于 ICD-11 的鉴别诊断。
- 基于指南和图谱的治疗建议。
- 药物相互作用审查。
- 对话短期记忆和用户长期临床信息记忆。
- 高频标准问题的语义缓存加速。

系统仅适合学习、原型验证和辅助参考，不应直接替代执业医师判断。

## 目录结构

```text
clinical_cds/
├── AGENTS.md                         # 仓库工作说明
├── agent/                            # 多 Agent 系统
│   ├── main.py                       # Agent CLI 入口
│   ├── requirements.txt              # Python 依赖
│   ├── .env                          # 本地环境变量，不应提交真实值
│   ├── agents/                       # 各专业 Agent 节点
│   ├── config/                       # Agent 配置、MCP 配置、症状同义词
│   ├── core/                         # workflow、memory、graph、mcp 核心代码
│   ├── mcp_servers/                  # MCP 工具服务
│   ├── tools/                        # LangChain tools
│   └── test/                         # 脚本式测试和数据入库脚本
├── app/                              # FastAPI 后端
│   ├── app_main.py                   # API 启动入口
│   ├── preload_cache.py              # 语义缓存预热脚本
│   ├── app_config/                   # API 侧配置
│   ├── infra/                        # 缓存等基础设施
│   ├── router/                       # API 路由
│   ├── schemas/                      # Pydantic 请求/响应模型
│   └── service/                      # API 业务服务
├── docker/
│   └── docker-compose.yml            # Redis、Milvus、Neo4j、MySQL
├── front/
│   └── clinical_cds/                 # Vue 3 前端项目
└── mock_data/                        # Markdown 示例临床知识数据
```

## 技术栈

后端与 Agent：

- Python。
- FastAPI。
- LangGraph。
- LangChain / LangChain Community。
- LangChain OpenAI 兼容接口，用于调用 DashScope Qwen。
- Redis：短期对话记忆。
- Milvus：长期记忆、文档 RAG、语义缓存。
- Neo4j：精神科知识图谱。
- MCP / FastMCP 风格工具服务。

前端：

- Vue 3。
- TypeScript。
- Vite。
- Element Plus。
- marked，用于渲染后端返回的 Markdown。

基础服务：

- Redis 7。
- Milvus 2.4 standalone。
- Neo4j 5 community。
- MySQL 8.0。

## 总体架构

```text
┌────────────────────────┐
│ Vue 前端                │
│ App.vue                 │
│ fetch /api/chat         │
└───────────┬────────────┘
            │ HTTP POST + SSE
            ▼
┌────────────────────────┐
│ FastAPI 后端            │
│ app/app_main.py         │
│ router/chat.py          │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│ chat_service.stream_chat│
│ 1. 查语义缓存           │
│ 2. 取记忆上下文         │
│ 3. 调 Agent 图          │
│ 4. 保存短期记忆         │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│ LangGraph 多 Agent 图   │
│ Router -> Symptom       │
│ -> Diagnosis            │
│ -> Treatment            │
│ -> DrugReview           │
└───────────┬────────────┘
            │
            ├── Redis: short-term memory
            ├── Milvus: long-term memory
            ├── Milvus: document RAG
            ├── Milvus: semantic cache
            ├── Neo4j: clinical KG
            └── JSON: symptom synonyms
```

## 运行时数据流

1. 医生在前端输入病例文本。
2. 前端 `App.vue` 通过 `fetch("http://127.0.0.1:5000/api/chat")` 提交 JSON。
3. FastAPI `/api/chat` 返回 `StreamingResponse`，媒体类型是 `text/event-stream`。
4. `stream_chat()` 先调用 `semantic_cache.get_cache(query, user_id)`。
5. 若缓存命中，直接把缓存答案切片成 SSE chunk 返回。
6. 若缓存未命中：
   - 从 Redis 读取当前用户和会话最近对话。
   - 从 Milvus 长期记忆集合检索相关用户背景。
   - 构造 `AgentState`。
   - 调用 LangGraph。
7. LangGraph 由 Router 决定入口节点，但后续节点会按固定流水线继续执行。
8. Agent 节点按需要调用工具：
   - `query_synonyms`：查本地症状同义词。
   - `query_vector_db`：查 Milvus 文档向量库。
   - `query_knowledge_graph`：查 Neo4j 知识图谱。
9. 后端保存本轮用户问题和系统回复到 Redis。
10. 后端把回复按 5 个字符一段流式返回前端。
11. 前端读取 SSE 数据并逐步追加到助手消息气泡。

## 当前实现特点

- Agent CLI 和 FastAPI 后端都能调用同一套 LangGraph 工作流。
- Redis、Milvus、Neo4j 不可用时，部分模块会降级，不一定直接中断程序。
- 语义缓存集合和长期记忆集合都由代码自动创建。
- 文档向量库和知识图谱需要通过脚本把 `mock_data/` 中的资料预先导入。
- 前端目前是单页应用，所有主要交互集中在 `src/App.vue`。

## 需要注意的地方

- `agent/.env` 是配置核心，后端配置也读取这里。
- Docker 中 Neo4j 默认密码是 `password123`，`agent/config/settings.py` 默认密码是 `password`，因此实际运行应以 `.env` 中的 `NEO4J_PASSWORD=password123` 为准。
- `agent/requirements.txt` 目前覆盖了主要依赖，但代码中还使用了 `fastapi`、`uvicorn`、`langchain-openai`、`langchain-milvus`、`langchain-neo4j`、`langchain-text-splitters` 等包；如果运行时报 `ModuleNotFoundError`，需要补装对应依赖。
- `mock_data/` 是开发示例数据，不应替代正式医学知识库。
