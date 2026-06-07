# 第一章：架构深度解析

> 本文档对临床决策支持系统（Clinical CDS）的整体架构进行逐层拆解，涵盖代码目录结构、状态定义、图编排、配置管理、启动链路等核心话题。所有代码片段均来自实际源文件，可通过标注的文件路径和行号快速定位。

---

## 1. 系统五层架构

本系统采用**浏览器-LangGraph 多智能体**的纵向分层架构，从前端到基础设施共五层：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 1: Browser (Vue 3 SPA)                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  front/clinical_cds/App.vue                                          │   │
│  │  fetch() + ReadableStream ▲    ▲ SSE: text/event-stream              │   │
│  └────────────────────────────┼────┼────────────────────────────────────┘   │
│                               │    │                                         │
│                    HTTP POST /api/chat ▲                                     │
│                    {query, user_id, session_id}│                              │
│                               │    │                                         │
├───────────────────────────────┼────┼─────────────────────────────────────────┤
│  Layer 2: FastAPI Backend     │    │                                         │
│  ┌────────────────────────────┼────┼─────────────────────────────────────┐   │
│  │  app/router/chat.py        │    │  Bearer Token + X-User-Id 鉴权      │   │
│  │  app/service/chat_service.py│   │  SSE 流式响应                       │   │
│  │  app/infra/cache.py        │    │  L1 语义缓存命中→直接返回           │   │
│  └────────────────────────────┼────┼─────────────────────────────────────┘   │
│                               │    │                                         │
├───────────────────────────────┼────┼─────────────────────────────────────────┤
│  Layer 3: LangGraph Agent Graph   │                                         │
│  ┌────────────────────────────┼────┼─────────────────────────────────────┐   │
│  │  agent/core/workflow/graph_manager.py  StateGraph 编排                │   │
│  │  ┌──────────┐    ┌───────────────────┐    ┌──────────┐               │   │
│  │  │Orchestrator│──→│Diagnosis → Treatment│──→│DrugReview│               │   │
│  │  │ (Router)  │    │ (鉴别诊断+症状提取) │    │ (药物审查)│               │   │
│  │  └──────────┘    └───────────────────┘    └──────────┘               │   │
│  │  ▲ ReAct Agent Pattern: SystemPrompt + Tools + LLM                    │   │
│  └────────────────────────────┬─────────────────────────────────────────┘   │
│                               │                                             │
├───────────────────────────────┼─────────────────────────────────────────────┤
│  Layer 4: Tools Backends      │                                             │
│  ┌────────────────────────────┼─────────────────────────────────────────┐   │
│  │  agent/tools/               │                                         │   │
│  │  ├── graph_tool.py ────────┼──→ Neo4j (Bolt Protocol)                │   │
│  │  ├── vector_tool.py ───────┼──→ Milvus (gRPC:19530)                  │   │
│  │  └── synonym_tool.py ──────┼──→ Local JSON (同义词字典)              │   │
│  │                             │                                         │   │
│  │  agent/core/memory/         │                                         │   │
│  │  ├── short_term.py ────────┼──→ Redis (RESP)                         │   │
│  │  └── long_term.py ─────────┼──→ Milvus (gRPC:19530)                  │   │
│  └─────────────────────────────┼─────────────────────────────────────────┘   │
│                                │                                             │
├────────────────────────────────┼────────────────────────────────────────────┤
│  Layer 5: Docker Infrastructure│                                             │
│  ┌─────────────────────────────┼─────────────────────────────────────────┐   │
│  │  docker-compose.yml         │                                         │   │
│  │  ├── Redis           :6379  │ (短期记忆)                               │   │
│  │  ├── Milvus          :19530 │ (长期记忆 + 语义缓存 + RAG)              │   │
│  │  ├── Neo4j           :7687  │ (知识图谱)                               │   │
│  │  └── MySQL           :3306  │ (待接入，规划中)                          │   │
│  └─────────────────────────────┼─────────────────────────────────────────┘   │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 │
                          Agent 日志流向:
                          agent/ → logging.getLogger("clinical_cds.agent")
                          app/   → logging.getLogger("clinical_cds.chat")
                          控制台 + logs/backend.log (5MB轮转,保留5个)
```

### 核心数据流

完整请求生命周期参考 `CLAUDE.md` 第 67-79 行的描述（source: `CLAUDE.md` L67-L79）：

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

---

## 2. 三层代码目录

### `agent/` — LangGraph 多智能体推理核心

| 文件路径 | 一句话描述 |
|---|---|
| `agent/agents/orchestrator.py` | 路由节点，LLM 判断用户意图并分发给下游 Agent |
| `agent/agents/diagnosis_agent.py` | 鉴别诊断 Agent，症状提取 + ICD-11 鉴别 |
| `agent/agents/treatment_agent.py` | 治疗推荐 Agent，检索指南输出分级方案 |
| `agent/agents/drug_review_agent.py` | 药物审查 Agent，分析相互作用风险 |
| `agent/core/workflow/graph_manager.py` | StateGraph 组装器，定义节点和有向边 |
| `agent/core/workflow/state.py` | AgentState TypedDict 全局状态定义 |
| `agent/core/memory/memory_manager.py` | 记忆管理器统一入口 |
| `agent/core/memory/short_term.py` | Redis 短期记忆实现 |
| `agent/core/memory/long_term.py` | Milvus 长期偏好实现 |
| `agent/core/memory/preference_extractor.py` | LLM 偏好提取器 |
| `agent/core/graph/models.py` | 知识图谱实体数据模型 |
| `agent/core/graph/parser.py` | 知识图谱 LLM 解析器 |
| `agent/core/mcp/mcp_manager.py` | MCP 工具管理器 |
| `agent/tools/graph_tool.py` | Neo4j 知识图谱查询工具 |
| `agent/tools/vector_tool.py` | Milvus 向量检索工具 |
| `agent/tools/synonym_tool.py` | 临床症状同义词映射工具 |
| `agent/config/settings.py` | Agent 层 Pydantic 配置 |
| `agent/main.py` | Agent CLI 交互模式入口 |

### `app/` — FastAPI 后端接口层

| 文件路径 | 一句话描述 |
|---|---|
| `app/app_main.py` | FastAPI 应用入口，CORS、lifespan |
| `app/router/chat.py` | `/api/chat` 端点，Bearer Token 鉴权 |
| `app/service/chat_service.py` | SSE 流式响应，Agent 图执行，记忆保存 |
| `app/schemas/chat.py` | ChatRequest 模型 |
| `app/infra/cache.py` | Milvus 语义缓存 |
| `app/infra/logging_config.py` | RotatingFileHandler 日志配置 |
| `app/app_config/settings.py` | App 层单例配置 |

### `front/clinical_cds/` — Vue 3 + TypeScript + Vite

| 文件路径 | 一句话描述 |
|---|---|
| `front/clinical_cds/App.vue` | 单文件应用，全部 UI 逻辑集中于此 |
| `front/clinical_cds/env.d.ts` | 环境变量类型声明 |
| `front/clinical_cds/vite.config.ts` | Vite 构建配置 |

---

## 3. AgentState TypedDict

定义在 `agent/core/workflow/state.py`（L1-L31）。

```python
# source: agent/core/workflow/state.py (L1-L31)
from typing import Annotated, TypedDict, Any, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """
    LangGraph 全局状态。
    负责在 Router、各个子 Agent 以及 Memory 之间传递信息。
    """
    # 消息记录，使用 add_messages 将新消息追加到列表末尾并自动转换元组
    # 写入者: 每个 Agent 节点的 __call__ 方法追加 AIMessage
    # 读取者: orchestrator 读取最新用户消息, 诊断/治疗/审查 Agent 读取完整对话历史
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # 决定下一步走向哪个节点的路由标记
    # 写入者: orchestrator.route() 的返回值
    # 读取者: graph_manager._route_condition()
    next_agent: str

    # 用户信息，用于鉴权和记忆隔离
    # 写入者: chat_service.stream_chat() 或 main.py 初始化时
    # 读取者: 记忆系统, 日志系统
    user_id: str
    session_id: str

    # 注入的记忆信息 (长短期记忆提取出的背景上下文)
    # 写入者: chat_service._extract_memory_context() 或 main.py._extract_memory_context()
    # 读取者: 各 Agent 的 _build_system_prompt() 方法
    memory_context: str

    # 工具调用的附带信息或元数据
    # 写入者: orchestrator.route() 设置 is_drug_review_workflow
    # 读取者: 各 Agent 可访问 metadata 中的标志位
    metadata: dict[str, Any]

class AgentOutput(TypedDict):
    """Agent 执行的标准输出格式。"""
    response: str
    tool_calls: list[dict[str, Any]]
    metadata: dict[str, Any]
```

**关键设计说明**:
- `messages` 使用 `Annotated[..., add_messages]` —— 这是 LangGraph 的 reducer 机制。新消息会被追加到列表末尾，自动处理 `BaseMessage` 和 `tuple` 类型的转换。
- `AgentOutput` 定义了标准的 Agent 输出格式，但目前实际节点返回的是 `{"messages": [AIMessage(content=...)]}` 格式，`AgentOutput` 作为接口约定使用。

---

## 4. StateGraph 拓扑

定义在 `agent/core/workflow/graph_manager.py`（L18-L84）。

### 图组装代码（L63-L84）

```python
# source: agent/core/workflow/graph_manager.py (L63-L84)
def build_graph(self) -> StateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("orchestrator", self._run_orchestrator)
    builder.add_node("differential_diagnosis", self._run_diagnosis)
    builder.add_node("treatment_recommend", self._run_treatment)
    builder.add_node("drug_interaction", self._run_drug_review)

    builder.add_edge(START, "orchestrator")

    builder.add_conditional_edges(
        "orchestrator", self._route_condition,
        {"differential_diagnosis": "differential_diagnosis",
         "treatment_recommend": "treatment_recommend",
         "drug_interaction": "drug_interaction"})

    # 3 步流水线（诊断内置症状提取 → 治疗 → 药物审查）
    builder.add_edge("differential_diagnosis", "treatment_recommend")
    builder.add_edge("treatment_recommend", "drug_interaction")
    builder.add_edge("drug_interaction", END)

    return builder.compile()
```

### 路由条件函数（L27-L28）

```python
# source: agent/core/workflow/graph_manager.py (L27-L28)
def _route_condition(self, state: AgentState) -> str:
    return state.get("next_agent", "differential_diagnosis")
```

### 可视化图拓扑

```
START
  │
  ▼
orchestrator ──→ conditional edge ──→ { differential_diagnosis,
  │                                      treatment_recommend,
  │                                      drug_interaction }
  │                         ┌──────────────────────┐
  ├──→ differential_diagnosis → treatment_recommend → drug_interaction → END
  ├──→ treatment_recommend     → drug_interaction → END
  └──→ drug_interaction        → END
```

**设计要点**:
- orchestrator 虽然输出三个可能的路由目标，但在**流水线模式下**，一旦进入 `differential_diagnosis`，它会继续经过 `treatment_recommend` 再到 `drug_interaction`，是一条完整的 3 步流水线。
- 条件路由只在 orchestrator 之后执行一次，后续是**硬边**（hard edges），不可跳过。
- `is_drug_review_workflow` 这个 metadata 标志在 orchestrator 中设置，但 Agent 图内部并不用它来决定流程 —— 它是留给调用方（如前端）识别意图的附加信息。

---

## 5. 两套 Settings

系统有两套独立的配置类，都读取 `agent/.env` 文件。

### `agent/config/settings.py`（Agent 层）

`source: agent/config/settings.py (L1-L96)`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore",
    )

    dashscope_api_key: str                          # alias: DASHSCOPE_API_KEY
    llm_api_key: str | None = None                  # alias: LLM_API_KEY
    model: str = "qwen-plus"                        # alias: MODEL
    base_url: str | None = None                     # alias: BASE_URL
    embedding_api_key: str | None = None            # alias: EMBEDDING_API_KEY
    dashscope_embedding_api_key: str | None = None  # alias: DASHSCOPE_EMBEDDING_API_KEY
    mcp_servers_config: Path                        # alias: MCP_SERVERS_CONFIG
    openweather_api_key: str | None = None          # alias: OPENWEATHER_API_KEY
    redis_url: str = "redis://localhost:6379"       # alias: REDIS_URL
    redis_ttl: int = 1800                           # alias: REDIS_TTL
    milvus_host: str = "localhost"                  # alias: MILVUS_HOST
    milvus_port: int = 19530                        # alias: MILVUS_PORT
    milvus_api_key: str | None = None               # alias: MILVUS_API_KEY
    neo4j_uri: str = "bolt://localhost:7687"        # alias: NEO4J_URI
    neo4j_user: str = "neo4j"                       # alias: NEO4J_USER
    neo4j_password: str = "password"                # alias: NEO4J_PASSWORD
    neo4j_database: str = "neo4j"                   # alias: NEO4J_DATABASE
    log_level: str = "INFO"                         # alias: LOG_LEVEL
```

获取方式：`get_settings()` 通过 `@lru_cache` 缓存实例。

```python
# source: agent/config/settings.py (L93-L96)
@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
```

### `app/app_config/settings.py`（App 层）

`source: app/app_config/settings.py (L1-L25)`

```python
# source: app/app_config/settings.py (L7-L25)
class Settings(BaseSettings):
    dashscope_api_key: str
    llm_api_key: str | None = None
    base_url: str | None = None
    embedding_api_key: str | None = None
    enable_semantic_cache: bool = True
    redis_url: str
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_api_key: str | None = None
    api_auth_token: str | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra='ignore')

settings = Settings()  # 模块级单例
```

### 对比表

| 字段 | `agent/config/settings.py` | `app/app_config/settings.py` | 说明 |
|---|---|---|---|
| `dashscope_api_key` | 是 | 是 | 重叠字段 |
| `llm_api_key` | 是 | 是 | 重叠字段 |
| `base_url` | 是 | 是 | 重叠字段 |
| `embedding_api_key` | 是 | 是 | 重叠字段 |
| `model` | 是 | **否** | Agent 层专属：指定 LLM 模型名 |
| `dashscope_embedding_api_key` | 是 | **否** | Agent 层专属：独立 embedding key |
| `mcp_servers_config` | 是 | **否** | Agent 层专属：MCP 配置路径 |
| `openweather_api_key` | 是 | **否** | Agent 层专属：天气 API |
| `redis_url` | 是 | 是 | 重叠字段 |
| `redis_ttl` | 是 | **否** | Agent 层专属：TTL 配置 |
| `milvus_host/port` | 是 | 是 | 重叠字段 |
| `milvus_api_key` | 是 | 是 | 重叠字段 |
| `neo4j_uri/user/password/database` | 是 | **否** | Agent 层专属：知识图谱配置 |
| `log_level` | 是 | **否** | Agent 层专属 |
| `enable_semantic_cache` | **否** | 是 | App 层专属：缓存开关 |
| `api_auth_token` | **否** | 是 | App 层专属：鉴权 |
| `cors_origins` | **否** | 是 | App 层专属：CORS |

### 为什么需要两套 Settings？

从 `CLAUDE.md` L150 的说明（source: `CLAUDE.md` L150）：
> 两套 Settings... agent/config/settings.py（`@lru_cache`，Agent 使用）和 app/app_config/settings.py（模块级单例，FastAPI 使用），都读 agent/.env。两者字段不完全一致。

根本原因：
1. **职责分离**：Agent 层是全套 LangGraph 配置，包含 Neo4j、MCP、Redis TTL 等知识图谱和记忆系统参数；App 层是 Web 接口配置，包含认证、CORS、语义缓存开关。
2. **初始化时序**：Agent 层使用 `@lru_cache` 延迟加载，而 App 层使用模块级单例（`settings = Settings()` 在 import 时立即实例化）。
3. **历史遗留**：两套 settings 随着开发演进逐渐分化，agent 层的 settings 更完整，涵盖了 app 层所需字段的超集（注意 app 层通过 `extra='ignore'` 忽略多余 env 变量）。

---

## 6. sys.path 注入

App 层的 Python 模块需要引用 `agent/` 目录下的代码（如 `from config import get_settings`, `from core.workflow.graph_manager import AgentGraphManager`），因此需要在运行时将 `agent/` 目录插入 `sys.path`。

### `app/app_main.py`（L5-L11）

```python
# source: app/app_main.py (L1-L11)
import sys
import os

# 将 agent 目录加入 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)
```

### `app/service/chat_service.py`（L8-L11）

```python
# source: app/service/chat_service.py (L8-L11)
# 初始化 Agent 和 Graph
AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)
```

### `agent/main.py`（L24-L25）

```python
# source: agent/main.py (L24-L25)
# 将父目录添加到导入路径
sys.path.insert(0, str(Path(__file__).parent))
```

### 为什么需要这样做？

本项目的目录结构为：
```
clinical_cds/
├── agent/       # LangGraph 核心
│   ├── config/  #   → from config import get_settings
│   ├── core/    #   → from core.workflow...
│   └── ...
├── app/         # FastAPI 接口
│   ├── service/ #   → 需要 import agent/ 下的模块
│   └── ...
└── front/       # 前端（无需 path 注入）
```

正常运行 `uvicorn app.app_main:app` 时，工作目录通常和 `app_main.py` 同级，`agent/` 不在 Python 模块搜索路径中。sys.path 注入使得 `app/` 层的代码可以直接使用 `from config import get_settings`（解析为 `agent/config/settings.py`），而不需要修改项目结构或使用相对导入。

### 可能的问题

1. **导入顺序敏感**：`sys.path.insert(0, AGENT_DIR)` 必须在所有 `from agent/*` 导入之前执行。`chat_service.py` 在 L12-L17 行集中导入，而 path 注入在 L8-L11 行，顺序正确。
2. **模块名冲突**：如果 `agent/config/settings.py` 和 `app/app_config/settings.py` 同时被 import，Python 通过 `sys.path` 的搜索顺序决定加载哪个。实际使用中，agent 层的 `from config import get_settings` 在 agent 内部使用，app 层的 `from app.app_config.settings import settings` 使用完整包路径。
3. **IDE 支持**：PyCharm/VSCode 可能无法自动识别这种动态路径注入，需要在 IDE 中将 `agent/` 标记为 Sources Root。

---

## 7. 启动链路

系统启动从 `app/app_main.py` 的 `lifespan` 事件开始，经过多层初始化后进入就绪状态。

### 步骤一：FastAPI lifespan（app/app_main.py L24-L30）

```python
# source: app/app_main.py (L24-L30)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    await init_agent_system()
    yield
    # 关闭时清理
    pass
```

### 步骤二：init_agent_system()（app/service/chat_service.py L74-L94）

```python
# source: app/service/chat_service.py (L74-L94)
async def init_agent_system():
    global graph, memory
    if graph is None:
        logger.info("event=agent_system_init step=graph_start")
        graph_manager = AgentGraphManager()
        graph = graph_manager.build_graph()

        logger.info("event=agent_system_init step=memory_start")
        from config import get_settings
        settings = get_settings()
        memory = MemoryManager(
            redis_url=settings.redis_url,
            redis_ttl=settings.redis_ttl,
            milvus_host=settings.milvus_host,
            milvus_port=settings.milvus_port,
            milvus_api_key=settings.milvus_api_key,
            embedding_api_key=settings.get_embedding_api_key(),
        )
        await memory.initialize()
        await semantic_cache.initialize()
        logger.info("event=agent_system_init step=complete")
```

### 步骤三：内部初始化链

**AgentGraphManager 初始化**（`agent/core/workflow/graph_manager.py` L21-L25）：
```python
# source: agent/core/workflow/graph_manager.py (L21-L25)
def __init__(self):
    self.orchestrator = OrchestratorAgent()
    self.diagnosis_node = DiagnosisAgentNode()
    self.treatment_node = TreatmentAgentNode()
    self.drug_review_node = DrugReviewAgentNode()
```

每个 Agent 的 `__init__` 内部会实例化 `ChatOpenAI`（如 `diagnosis_agent.py` L18-L24）：
```python
# source: agent/agents/diagnosis_agent.py (L18-L24)
def __init__(self):
    dotenv_path = os.path.join(...)
    load_dotenv(dotenv_path)
    from config import get_settings
    self.llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0.1)
    self.tools = [query_synonyms, query_knowledge_graph, query_vector_db]
    self.inner_agent = create_react_agent(self.llm, self.tools)
```

**MemoryManager 初始化**（`memory_manager.py` L83-L96）——并发初始化短期和长期存储：
```python
# source: agent/core/memory/memory_manager.py (L83-L96)
async def initialize(self) -> None:
    import asyncio
    await asyncio.gather(
        self.short_term.initialize(),
        self.long_term.initialize(),
        return_exceptions=True,
    )
    logger.info(
        "MemoryManager ready – short_term=%s, long_term=%s",
        "✓" if self.short_term.available else "✗ (disabled)",
        "✓" if self.long_term.available else "✗ (disabled)",
    )
```

**SemanticCache 初始化**（`app/infra/cache.py` L19-L52）——创建 Milvus Client 和确保 Collection 存在。

### 完整启动时序图

```
app_main.py lifespan()
  │
  ├── init_agent_system()
  │   ├── AgentGraphManager()
  │   │   ├── OrchestratorAgent()   → ChatOpenAI()
  │   │   ├── DiagnosisAgentNode()  → ChatOpenAI() + create_react_agent()
  │   │   ├── TreatmentAgentNode()  → ChatOpenAI() + create_react_agent()
  │   │   └── DrugReviewAgentNode() → ChatOpenAI() + create_react_agent()
  │   │
  │   ├── graph = graph_manager.build_graph()
  │   │   └── StateGraph.compile()  → 检查图结构一致性
  │   │
  │   ├── MemoryManager()
  │   │   ├── ShortTermMemory(Redis)
  │   │   └── LongTermMemory(Milvus)
  │   │
  │   ├── memory.initialize()
  │   │   ├── asyncio.gather(short_term.init, long_term.init)
  │   │   │   ├── Redis: 连接测试 → _available = True/False
  │   │   │   └── Milvus: 连接+创建Collection → _available = True/False
  │   │   └── 两者任一失败不影响启动（优雅降级）
  │   │
  │   └── semantic_cache.initialize()
  │       ├── MilvusClient() + DashScopeEmbeddings()
  │       └── _ensure_collection() → "qa_semantic_cache"
  │
  └── yield（应用就绪，开始处理请求）
```

---

## 8. 架构决策表

| 决策 | 理由 | 代价 |
|---|---|---|
| **LangGraph 而非自定义编排** | 利用 LangGraph 的 StateGraph + 条件边 + ReAct agent 预构建组件，减少手写状态机的工作量。获得 add_messages reducer、stream_mode 多模式支持、节点级错误隔离。 | 依赖 langgraph 版本演进（当前 0.x），API 可能变化（如 stream_mode 参数调整）；调试门槛较高，需要理解 LangGraph 内部概念。 |
| **ChatOpenAI 而非特定厂商 SDK** | 通过统一接口支持多种模型（Qwen、DeepSeek 等），仅需切换 `BASE_URL` 即可。langchain_openai 的 ChatOpenAI 已成为 LLM 兼容层的"通用适配器"。 | 无法使用厂商特有功能（如 Qwen 的函数调用扩展、DeepSeek 的 FIM 能力）。token 计费统计需要额外的 wrapper。 |
| **单文件 App.vue 而非组件树** | 减少编译步骤和构建复杂度，适合原型阶段快速迭代。所有 SSE 解析逻辑集中在 600+ 行内，无需跨组件传递状态。 | 可维护性差，无法单元测试 UI 子模块；多人协作时 Git 冲突概率高；不适合长期演进的大型项目。 |
| **ReAct Agent 模式** | LangGraph 的 `create_react_agent` 提供了标准的思考-行动-观察循环，三个领域 Agent 共享同一模式，代码结构一致性好。工具调用次数通过 system prompt 限制。 | 固定的 ReAct 循环可能导致不必要的工具调用；无法细粒度控制 ReAct 内部状态；LLM 可能忽略"最多调用 2 次"的约束。 |
| **SSE 而非 WebSocket** | 单向服务器推送天然适合 AI 流式响应场景。HTTP 协议无需维护长连接状态，兼容性好（可通过 CDN/Proxy）。实现简单，用 `StreamingResponse` + `async generator` 即可。 | 客户端无法向已建立的 SSE 连接发送额外数据；心跳重连机制需要自己实现（代码中通过在 chat_service.py 中 `async for` 逐事件推送，前端 `fetch`+`ReadableStream` 解析 `data:` 行）。 |
| **两套 Settings** | Agent 层配置（Neo4j、MCP、Redis TTL）与 App 层配置（鉴权、CORS、缓存开关）各自独立演化，互不影响。 | 配置验证：某些字段在两层间重复，无法保证一致性；新人容易混淆该用哪个 settings。 |
| **sys.path 注入** | 避免将 agent/ 打包为独立 Python package 或使用符号链接，保持开发时目录结构直观。 | IDE 静态分析支持不完整；多个入口点（CLI vs 后端）需要重复注入代码；可能产生隐式导入错误。 |
| **Milvus 语义缓存** | 通过 embedding 相似度（余弦距离 < 0.08）实现语义级别的查询匹配，L1_EXACT + L1_SEMANTIC 两级命中策略覆盖精确和近似场景。 | 缓存写放大：每次写入先 delete 再 insert；冷启动阶段无缓存；Milvus 服务不可用时缓存降级，SSE 会跳过缓存检查直接进入 Agent 图。 |
| **优雅降级** | Redis/Milvus/Neo4j 任一不可用时，系统不崩溃——记忆静默跳过、缓存静默跳过、图谱工具返回错误信息但 Agent 继续生成。 | 降级时用户体验下降（无记忆上下文、无缓存加速），但错误信息不够透明（前端只看到诊疗结果变差但不知道原因）。 |

---

## 章末要点

1. 系统架构为**五层纵深防御**：浏览器发请求 → API 鉴权 → 缓存检查 → Agent 推理 → 基础设施支撑。
2. `AgentState` 是贯穿整个 LangGraph 的"全局总线"，所有节点通过修改 state 相互通信。
3. 三步骤流水线（诊断→治疗→审查）是**硬编码的**，orchestrator 只能决定入口点，不能跳过中间步骤。
4. 两套 Settings 是历史演进的产物，新开发应优先使用 `agent/config/settings.py`（字段更全）。
5. 启动链路中各组件**独立初始化、独立降级**，不因单个后端不可用而阻塞。
