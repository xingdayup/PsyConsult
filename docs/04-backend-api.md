# 后端 FastAPI 服务

## 后端职责

`app/` 是前端和 Agent 系统之间的 API 层，主要职责：

- 启动时初始化 LangGraph Agent 系统。
- 初始化 Redis/Milvus 记忆系统。
- 初始化 Milvus 语义缓存。
- 提供 `/api/chat` 流式接口。
- 将 Agent 回复通过 SSE 分片返回给前端。

## 目录结构

```text
app/
├── app_main.py              # FastAPI 启动入口
├── preload_cache.py         # 语义缓存预热脚本
├── app_config/
│   └── settings.py          # API 侧配置，读取 agent/.env
├── infra/
│   └── cache.py             # Milvus 语义缓存
├── router/
│   └── chat.py              # /api/chat 路由
├── schemas/
│   └── chat.py              # 请求/响应 Pydantic 模型
└── service/
    └── chat_service.py      # API 到 Agent 的业务编排
```

## 启动入口

文件：

```text
app/app_main.py
```

主要逻辑：

1. 将 `agent/` 目录加入 `sys.path`。
2. 创建 FastAPI 应用。
3. 在 lifespan 启动钩子中调用 `init_agent_system()`。
4. 配置 CORS。
5. 注册 `chat.router` 到 `/api` 前缀。
6. 使用 uvicorn 监听 5000 端口。

启动命令：

```bash
cd app
python app_main.py
```

## API 路由

文件：

```text
app/router/chat.py
```

接口：

```text
POST /api/chat
```

请求模型：

```python
class ChatRequest(BaseModel):
    query: str
    user_id: Optional[str] = "user_1001"
    session_id: Optional[str] = "default_session"
```

响应：

- 类型：SSE。
- `media_type="text/event-stream"`。
- 每条数据形如：

```text
data: {"content": "文本片段"}

data: {"done": true}
```

curl 示例：

```bash
curl -N -X POST http://127.0.0.1:5000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"患者近两周情绪低落、失眠、食欲下降\",\"user_id\":\"doctor_001\",\"session_id\":\"session_001\"}"
```

## 服务层

文件：

```text
app/service/chat_service.py
```

全局对象：

- `graph`：LangGraph 编译后的图。
- `memory`：`MemoryManager` 实例。

启动初始化：

```python
async def init_agent_system():
    graph_manager = AgentGraphManager()
    graph = graph_manager.build_graph()
    memory = MemoryManager(...)
    await memory.initialize()
    await semantic_cache.initialize()
```

聊天流程：

```python
async def stream_chat(query: str, user_id: str, session_id: str):
    cache_hit = await semantic_cache.get_cache(query, user_id)
    if cache_hit:
        response_text = cache_hit["answer"]
    else:
        mem_context = await _extract_memory_context(user_id, session_id, query)
        state = {...}
        result = await graph.ainvoke(state, config=config)
        response_text = result["messages"][-1].content

    await memory.save_conversation(...)
    yield SSE chunks
```

## 语义缓存

文件：

```text
app/infra/cache.py
```

缓存 Collection：

```text
qa_semantic_cache
```

字段：

- `id`
- `question`
- `question_norm`
- `answer`
- `scope`
- `user_id`
- `enabled`
- `embedding`

embedding：

- 模型：`text-embedding-v2`
- 维度：1536
- 存储：Milvus
- 索引：`IVF_FLAT`
- metric：`COSINE`

命中逻辑：

1. 归一化 query：去首尾空格、转小写、压缩空白。
2. 先查用户级精确缓存。
3. 再查公共精确缓存。
4. 再做向量语义检索。
5. 语义距离超过阈值 `0.08` 时不命中。

缓存范围：

- `public`：公共缓存。
- `user`：指定用户缓存。

## 缓存预热

文件：

```text
app/preload_cache.py
```

预置问题包括：

- 抑郁发作 ICD-11 诊断标准。
- 舍曲林常用剂量和副作用。
- PHQ-9 评分分级。
- SSRI 和 SNRI 区别。

运行：

```bash
cd app
python preload_cache.py
```

运行后会把预设 QA 写入 Milvus 的 `qa_semantic_cache`。

## CORS

`app_main.py` 当前允许所有来源：

```python
allow_origins=["*"]
allow_credentials=True
allow_methods=["*"]
allow_headers=["*"]
```

这适合本地开发。生产环境应限制来源域名，例如只允许正式前端域名。

## 和 Agent 的路径关系

后端为了导入 Agent 代码，会把 `agent/` 加入 `sys.path`：

```python
AGENT_DIR = os.path.join(project_root, "agent")
sys.path.insert(0, AGENT_DIR)
```

因此后端可以直接导入：

```python
from core.workflow.graph_manager import AgentGraphManager
from core.memory.memory_manager import MemoryManager
```

## 常见问题

### 后端启动时报找不到 `router`

推荐从 `app/` 目录启动：

```bash
cd app
python app_main.py
```

### 后端启动时报缺少 FastAPI 或 uvicorn

补装：

```bash
pip install fastapi uvicorn
```

### API 有响应但很慢

可能原因：

- 语义缓存未命中。
- Agent 正在调用多个 LLM。
- Milvus 或 Neo4j 首次连接。
- 文档 RAG 或图谱查询耗时。

可以先运行 `app/preload_cache.py` 预热高频问题。

### 缓存一直不命中

检查：

- Milvus 是否启动。
- `MILVUS_HOST`、`MILVUS_PORT` 是否正确。
- `DASHSCOPE_API_KEY` 是否可用于 embedding。
- `qa_semantic_cache` 是否成功创建。
- query 是否和预置问题差异过大。
