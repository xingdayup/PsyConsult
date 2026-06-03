# 05 - API 层与前端

## API 层 (FastAPI)

`app/` 目录是前端和 Agent 引擎之间的桥梁。用 FastAPI 框架，核心就是一条路由。

### 核心路由

```python
# app/router/chat.py
@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    return StreamingResponse(
        stream_chat(request.query, request.user_id, request.session_id),
        media_type="text/event-stream"
    )
```

`ChatRequest` 只有三个字段：`query`（医生的输入）、`user_id`（医生 ID）、`session_id`（会话 ID）。

### 请求处理流程

`app/service/chat_service.py` 的 `stream_chat()` 函数：

```
1. 语义缓存检查 (Milvus)
   ├── L1 精确匹配: 同样的问题问过吗？
   └── L1 语义匹配: 相似度 >0.92 的问题？
   └─ 未命中 → 继续

2. 加载记忆上下文
   ├── Redis: 取本次会话最近对话
   └── Milvus: 检索患者长期临床画像

3. 构造 AgentState + 执行 LangGraph 图
   state = {messages, user_id, session_id, memory_context}
   result = await graph.ainvoke(state, config=...)

4. SSE 流式返回
   每 5 个字符一块, 20ms 间隔 → 前端打字机效果
```

### 语义缓存

`app/infra/cache.py`。作用是 FAQ 类问题直接返回缓存，跳过 Agent 推理。预热数据：

```python
PRESET_QA = [
    {"query": "抑郁发作的 ICD-11 诊断标准是什么？", "response": "..."},
    {"query": "舍曲林的常用剂量和副作用是什么？",    "response": "..."},
    {"query": "PHQ-9 评分怎么分级？",              "response": "..."},
    {"query": "SSRI 和 SNRI 有什么区别？",          "response": "..."},
]
```

### 初始化

FastAPI 启动时（`lifespan` 事件），自动初始化 Agent 图 + 记忆系统 + 语义缓存。这些都是模块级单例——初始化一次，所有请求复用。

## 前端 (Vue 3)

`front/clinical_cds/src/App.vue` 是一个单文件组件。Element Plus 组件库 + `marked` 做 Markdown 渲染。

### 布局

```
┌──────────┬────────────────────────────────┐
│ 侧边栏    │ 主区域                          │
│          │ 🏥 精神科临床决策支持系统         │
│ ☁ CDS    │ ⚠ 免责声明                      │
│          │                                │
│ 诊疗会话  │ 消息列表 / 欢迎页                │
│ - 会话1   │                                │
│ - 会话2   │                                │
│          │                                │
│ [+新建]  │ 输入区 [textarea] [发送]         │
│ 👨‍⚕️      │                                │
└──────────┴────────────────────────────────┘
```

### 场景卡片

消息列表为空时，显示 6 张快捷卡片，覆盖全部 5 类疾病 + 药物审查：

```
😔 抑郁筛查     🎭 双相鉴别     🧠 精神病性症状
🔄 强迫症状     😰 焦虑障碍     💊 药物审查
```

每张卡片预填了一个典型病例描述，点击即可体验完整推理链路。这既是 UX 引导，也是功能隐式测试。

### SSE 流式消费

前端用 Fetch API 读取 `ReadableStream`，手动解析 SSE 格式（`data: {json}\n\n`），逐块累积到当前消息。`marked` 实时渲染 ICD-11 诊断报告中的 ✅❌ 表格和 Markdown 格式。

### 免责声明

顶部红色横幅："⚠ 本系统仅供临床参考，所有诊断建议须经执业医师确认。诊断标准基于 ICD-11。"

## 下一步

- Mock 数据：→ `06-Mock-Data.md`
- 环境搭建：→ `07-Setup-Guide.md`
