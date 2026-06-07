# 01. 项目架构

## 模块解决的问题

Clinical CDS 解决的是精神科问诊中的非结构化决策辅助问题。医生输入通常是自然语言，例如“患者近两周情绪低落、失眠、食欲下降”，系统需要把它转成临床可用的信息：症状、量表推断、鉴别诊断、治疗建议、药物相互作用风险。

项目没有让一个 LLM 直接回答全部问题，而是拆成前端交互层、后端 API 层、Agent 编排层、工具与数据层、部署运维层。

## 总体链路

```text
医生浏览器
  -> Cloudflare Pages / Vue 前端
  -> POST /api/chat
  -> FastAPI StreamingResponse
  -> stream_chat()
  -> LangGraph Agent 工作流
  -> Milvus / Neo4j / Redis
  -> SSE data: {...}
  -> 前端流式展示阶段和答案
```

## 核心文件和职责

| 模块 | 核心文件 | 职责 |
|---|---|---|
| 前端 | `front/clinical_cds/src/App.vue` | 会话 UI、SSE 解析、Markdown 安全渲染、API 地址配置 |
| API | `app/router/chat.py` | `/api/chat` 路由、鉴权头、SSE 响应 |
| 服务层 | `app/service/chat_service.py` | 初始化 Agent/Memory、语义缓存、记忆提取、SSE 流式输出 |
| 工作流 | `agent/core/workflow/graph_manager.py` | LangGraph 节点注册、路由、流水线编排 |
| Agent | `agent/agents/*.py` | 路由、诊断、治疗、药物审查 |
| 工具 | `agent/tools/*.py` | Milvus 向量检索、Neo4j 图谱检索、同义词映射 |
| 记忆 | `agent/core/memory/*.py` | Redis 短期会话、Milvus 长期偏好 |

## 关键代码片段

### FastAPI 注册路由和 CORS

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
```

面试讲法：  
前端和后端分离部署，所以 CORS 是必须处理的工程问题。线上排障时我重点检查 `OPTIONS` 预检是否允许 `https://psyconsult.pages.dev`。

### Agent 初始化入口

```python
graph_manager = AgentGraphManager()
graph = graph_manager.build_graph()
memory = MemoryManager(...)
await memory.initialize()
await semantic_cache.initialize()
```

面试讲法：  
FastAPI 启动时统一初始化图编排、会话记忆和语义缓存，避免每次请求重复构建大对象。请求进入时只执行业务链路。

## 面试 Q&A

**Q：这个项目为什么要拆前后端？**  
A：前端主要负责医生交互、会话切换和流式展示；后端负责临床推理、工具调用和数据库访问。这样前端可以部署到 Cloudflare Pages，后端可以独立暴露 API，也方便后续替换部署形态。

**Q：系统里哪些部分最体现工程能力？**  
A：第一是 SSE 流式输出和首字节优化；第二是 LangGraph 多 Agent 编排；第三是 Redis/Milvus/Neo4j 的分层数据设计；第四是线上 CORS、Tunnel、API 地址配置这些真实部署问题。

## 截图建议

- 截 `app/app_main.py` 中 CORS 和路由注册。
- 截 `app/service/chat_service.py` 中初始化 `AgentGraphManager`、`MemoryManager`、`semantic_cache` 的代码。
- 截项目目录结构，说明前端、后端、Agent、数据层分离。

