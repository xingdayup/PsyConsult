# 第六章：SSE 流式交互与前端架构

## 6.1 概述

系统的核心交互模式是：**Vue 前端通过 POST /api/chat 发起请求，后端 LangGraph Agent 图以 Server-Sent Events (SSE) 流式返回推理过程与结果**。前端接收并实时渲染每一个事件，实现 "边推理边展示" 的用户体验。

本文档从后端 SSE 实现、前端消费、状态映射、认证安全、会话管理、Markdown 渲染、API URL 配置等角度全面解析这一数据通路。

---

## 6.2 后端 SSE 实现

后端 SSE 的核心在 `app/service/chat_service.py` 中，由 `stream_chat` 这个 `async generator` 实现。

### 6.2.1 SSE 格式辅助函数

`emit_sse` 函数是生成 SSE 文本行的唯一入口，将所有事件统一编码为 `data:` 行格式：

```python
# app/service/chat_service.py，第 124-132 行
def emit_sse(payload: dict, kind: str) -> str:
    logger.info(
        "event=sse_emit user_id=%s session_id=%s kind=%s total=%.3fs",
        user_id,
        session_id,
        kind,
        time.perf_counter() - request_start,
    )
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

每次调用都会记录日志（`kind` 参数区分事件类别），并返回一个符合 SSE 协议的数据行：`data: {json}\n\n`。

### 6.2.2 StreamingResponse 端点

`app/router/chat.py` 中的 `/api/chat` 端点将 `stream_chat` generator 包装为 `StreamingResponse`：

```python
# app/router/chat.py，第 52-70 行
@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    user_id: Annotated[str, Depends(require_chat_identity)],
):
    return StreamingResponse(
        stream_chat(request.query, user_id, request.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

三个 HTTP 头的作用：

- `Cache-Control: no-cache, no-transform` — 禁止代理/浏览器缓存 SSE 响应
- `X-Accel-Buffering: no` — 禁止 Nginx 等反向代理缓冲流式内容
- `Connection: keep-alive` — 保持 TCP 长连接

### 6.2.3 完整事件类型

`stream_chat` 函数（第 120-256 行）按顺序产生以下 SSE 事件：

| 顺序 | JSON Payload | 触发时机 |
|------|-------------|---------|
| 1 | `{"status": "accepted", "content": "已接收病例，开始分析..."}` | 请求刚进入后端 |
| 2 | `{"status": "semantic_cache_check", "content": "正在检查语义缓存..."}` | 开始查询语义缓存 |
| — | `{"agent": "semantic_cache", "content": "<缓存答案>"}` | (仅缓存命中) 返回缓存内容 |
| 3 | `{"status": "memory_context_extract", "content": "正在提取会话记忆..."}` | 开始提取 Redis+Mlivus 记忆 |
| 4 | `{"status": "agent_workflow_start", "content": "正在进入多智能体分析..."}` | Agent 图开始执行 |
| 5 | `{"status": "agent_node_start", "agent": "<agent_name>"}` | 当前 Agent 节点激活 |
| 6 | `{"status": "agent_tool_call", "agent": "<name>", "content": "正在调用 <tool>..."}` | Agent 调用工具 |
| 7 | `{"status": "agent_tool_done", "agent": "<name>", "content": "工具查询完成，正在生成分析..."}` | 工具调用结束 |
| 8 | `{"agent": "<name>", "content": "<文本块>"}` | Agent 生成逐 token 内容 |
| 9 | `{"status": "agent_node_complete", "agent": "<name>", "content": "<name> 已完成..."}` | Agent 节点全部执行完毕 |
| 10 | `{"done": true}` | 完整流程结束 |

### 6.2.4 入口校验：短查询拦截

`stream_chat` 在进入任何流程之前先校验输入长度：

```python
# app/service/chat_service.py，第 24-28 行
MIN_CLINICAL_QUERY_LENGTH = 4
SHORT_QUERY_RESPONSE = (
    "请输入更完整的临床问题或患者信息，例如症状、持续时间、严重程度、既往用药、"
    "量表分数或需要审查的药物组合。当前输入过短，系统不会进入诊疗推理流程。"
)

# 第 116-118 行
def _is_insufficient_query(query: str) -> bool:
    normalized = "".join(query.strip().split())
    return len(normalized) < MIN_CLINICAL_QUERY_LENGTH
```

去掉空白后少于 4 个字符的直接返回提示文案，不进入 Agent 图，也不保存记忆。

### 6.2.5 双 stream_mode 机制

`graph.astream` 同时订阅两种模式（第 197-235 行）：

```python
async for stream_mode, data in graph.astream(
    state, config=config, stream_mode=["updates", "custom"]
):
```

- **`stream_mode="custom"`** — Agent 节点在执行过程中发出自定义事件：节点启动、工具调用、工具完成、token 块。所有 chunk 累积到 `full_response`。
- **`stream_mode="updates"`** — 每个 Agent 节点执行完毕后发出 `{node_name: output}`，表示节点已完成。

两种模式交替产生事件，前端据此区分 "推理中" 和 "节点完成"。

### 6.2.6 记忆保存与异步偏好提取

完整流程结束后（第 241-253 行）：

```python
if should_save_memory and memory and memory.short_term.available:
    turn = [
        {"role": "user", "content": query},
        {"role": "assistant", "content": response_text},
    ]
    await memory.save_conversation(user_id, session_id, turn)
    log_step("short_term_memory_save")
    asyncio.create_task(_run_long_term_memory_extract(user_id, session_id))
```

短时记忆（Redis）实时保存；长时偏好（Milvus）通过 `asyncio.create_task` 异步后台提取，不阻塞 SSE 响应。

---

## 6.3 前端 SSE 消费

前端在 `src/App.vue` 的 `sendQuery()` 函数（第 380-481 行）中消费 SSE 流。

### 6.3.1 fetch + ReadableStream 模式

使用标准的 `fetch` API 而非 `EventSource`，因为 SSE 需要 POST 方法发送请求体：

```typescript
// App.vue，第 408-419 行
const headers: Record<string, string> = {
  'Content-Type': 'application/json',
  'X-User-Id': userId.value,
}
if (apiAuthToken.value) {
  headers.Authorization = `Bearer ${apiAuthToken.value}`
}

const response = await fetch(`${apiBaseUrl.value}/api/chat`, {
  method: 'POST',
  headers,
  body: JSON.stringify({ query, session_id: requestSessionId }),
})
```

### 6.3.2 Line Buffering 读取循环

`ReadableStream` 返回二进制块，通过 `TextDecoder` 解码后按行分割。关键技巧是保存跨块的不完整行（`buffer`）：

```typescript
// App.vue，第 426-471 行
const reader = response.body.getReader()
const decoder = new TextDecoder()
let buffer = ''

while (true) {
  const { done, value } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })
  const lines = buffer.split('\n')
  buffer = lines.pop() || ''  // 保存不完整行

  for (const line of lines) {
    if (!line.startsWith('data: ')) continue
    const data = line.slice(6)
    if (data === '[DONE]') break

    try {
      const parsed = JSON.parse(data)
      // ... 事件分发
    } catch {
      // 忽略不完整的 SSE 帧
    }
  }
}
```

### 6.3.3 四种事件处理器

JSON 解析后的 `parsed` 对象按字段分派：

```typescript
// App.vue，第 443-468 行
if (parsed.done) {
  updateAssistantStatus(requestSessionId, msgIdx, '分析完成')
  continue
}

if (parsed.status) {
  updateAssistantStatus(requestSessionId, msgIdx, statusLabel(parsed))
  if (currentSessionId.value === requestSessionId) {
    await scrollMessages()
  }
  continue
}

if (parsed.content) {
  let label = ''
  if (parsed.agent && parsed.agent !== lastContentAgent.current) {
    lastContentAgent.current = parsed.agent
    label = `\n### ${agentLabel(parsed.agent)}\n`  // Agent 切换时插入 Markdown 标题
  }
  appendAssistantMessage(requestSessionId, msgIdx, label + parsed.content)
  if (currentSessionId.value === requestSessionId) {
    await scrollMessages()
  }
}
```

四种事件类型：

| 字段 | 处理 |
|------|------|
| `parsed.done` | 更新状态为 "分析完成"，结束循环 |
| `parsed.status` | 更新气泡内的 `stage-status` 文本（不修改 `content`） |
| `parsed.content` | 追加到 assistant 消息的 `content`。Agent 切换时自动插入 `### 标题` Markdown |
| 未知 | `catch {}` 静默跳过 |

### 6.3.4 Agent 切换检测

当前端收到 `{agent: "differential_diagnosis", content: "..."}` 时，如果 `agent` 比之前的值发生了变化，就在内容之前插入一行 Markdown 三级标题：

```typescript
if (parsed.agent && parsed.agent !== lastContentAgent.current) {
  lastContentAgent.current = parsed.agent
  label = `\n### ${agentLabel(parsed.agent)}\n`
}
```

这样最终渲染的效果是：

```
### 临床评估与鉴别诊断
[诊断分析的文本...]

### 治疗推荐
[治疗方案的文本...]
```

### 6.3.5 智能刷新 — 非按字刷新

前端没有对每一条 SSE chunk 都触发 DOM 更新。实际在 `sendQuery` 循环中每收到一条 content 事件就调用 `appendAssistantMessage`（修改 ref 数据）并 `scrollMessages`，Vue 的响应式系统自动批处理 DOM 更新。

---

## 6.4 状态映射函数

### 6.4.1 agentLabel() — Agent 名称 -> 中文标签

```typescript
// App.vue，第 332-340 行
function agentLabel(name: string): string {
  const labels: Record<string, string> = {
    orchestrator: '🧭 路由决策',
    differential_diagnosis: '🔬 临床评估与鉴别诊断',
    treatment_recommend: '💊 治疗推荐',
    drug_interaction: '⚠️ 药物审查',
  }
  return labels[name] || name
}
```

四个 Agent 节点映射：

| Agent 标识 | 中文显示 |
|-----------|---------|
| `orchestrator` | 🧭 路由决策 |
| `differential_diagnosis` | 🔬 临床评估与鉴别诊断 |
| `treatment_recommend` | 💊 治疗推荐 |
| `drug_interaction` | ⚠️ 药物审查 |

### 6.4.2 statusLabel() — SSE status -> 用户可见文本

```typescript
// App.vue，第 342-356 行
function statusLabel(parsed: { status?: string; agent?: string; content?: string }): string {
  if (parsed.status === 'agent_node_start' && parsed.agent) {
    return `正在${agentLabel(parsed.agent)}...`
  }
  if (parsed.status === 'agent_tool_call') {
    return parsed.content || '正在查询知识库...'
  }
  if (parsed.status === 'agent_tool_done') {
    return parsed.content || '工具查询完成'
  }
  if (parsed.status === 'agent_node_complete' && parsed.agent) {
    return `${agentLabel(parsed.agent)} 已完成`
  }
  return parsed.content || ''
}
```

| status | 显示文本 |
|--------|---------|
| `agent_node_start` | `正在🔬 临床评估与鉴别诊断...` |
| `agent_tool_call` | `正在调用 知识库工具...` |
| `agent_tool_done` | `工具查询完成，正在生成分析...` |
| `agent_node_complete` | `🔬 临床评估与鉴别诊断 已完成` |
| 其他 | 直接显示 `content` 字段内容 |

---

## 6.5 认证与安全

### 6.5.1 前端发送

前端始终发送 `X-User-Id` 头；`Authorization: Bearer` 仅在配置了 token 时发送：

```typescript
// App.vue，第 408-414 行
const headers: Record<string, string> = {
  'Content-Type': 'application/json',
  'X-User-Id': userId.value,
}
if (apiAuthToken.value) {
  headers.Authorization = `Bearer ${apiAuthToken.value}`
}
```

`userId` 默认为 `doctor_001`（第 187 行），是一个硬编码的前端调试值，实际部署时应改为用户登录后的身份标识。

### 6.5.2 后端校验

`require_chat_identity` 依赖（`app/router/chat.py`，第 25-50 行）执行双重验证：

```python
def require_chat_identity(
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str:
    # 1. Bearer Token 验证（仅在配置了 api_auth_token 时启用）
    if settings.api_auth_token:
        token = _extract_bearer_token(authorization)
        if token is None or not secrets.compare_digest(token, settings.api_auth_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 2. X-User-Id 必填 + 格式校验
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-User-Id header",
        )
    user_id = x_user_id
    if not USER_ID_PATTERN.fullmatch(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-User-Id header",
        )
    return user_id
```

`USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")` — 只允许字母数字及 `_.:-`，长度 1-128。

`secrets.compare_digest` — 使用常量时间比较防止时序攻击。

### 6.5.3 401/400 响应

- **401 Unauthorized** — `api_auth_token` 非空且 `Authorization` 头缺失或不匹配，返回 `Invalid or missing bearer token`。
- **400 Bad Request** — `X-User-Id` 缺失或不符合正则，分别返回 `Missing X-User-Id header` / `Invalid X-User-Id header`。

前端在 `sendQuery` 的第 422-423 行捕获非 2xx 响应：

```typescript
if (!response.ok || !response.body) {
  throw new Error(`Request failed with status ${response.status}`)
}
```

---

## 6.6 会话管理

会话管理完全在**客户端**实现，不经过后端。后端只接收 `session_id` 作为记忆存储的键前缀。

### 6.6.1 数据结构

```typescript
// App.vue，第 176-185 行
interface SessionItem {
  id: string
  name: string
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  status?: string  // 仅 assistant 消息使用，显示当前阶段状态
}
```

### 6.6.2 核心状态变量

```typescript
// App.vue，第 187-193 行
const userId = ref('doctor_001')
const currentSessionId = ref(`session_${Date.now()}`)
const sessions = ref<SessionItem[]>([{ id: currentSessionId.value, name: '新诊疗会话' }])
const messagesBySession = ref<Record<string, ChatMessage[]>>({
  [currentSessionId.value]: [],
})
const messages = ref<ChatMessage[]>([])
```

- `sessions` — 会话列表（纯内存，刷新页面即丢失）
- `messagesBySession` — 按 session_id 索引的消息池
- `messages` — 当前活跃会话的消息（双向绑定到视图）

### 6.6.3 selectSession / createSession

```typescript
// App.vue，第 311-323 行
async function selectSession(sessionId: string) {
  currentSessionId.value = sessionId
  setCurrentSessionMessages(sessionId)
  await scrollMessages()
}

function createSession() {
  const id = `session_${Date.now()}`
  sessions.value.unshift({ id, name: `诊疗会话 ${sessions.value.length + 1}` })
  messagesBySession.value[id] = []
  currentSessionId.value = id
  setCurrentSessionMessages(id)
}
```

`selectSession` 切换时从 `messagesBySession` 中恢复对应会话的消息。`createSession` 用 `Date.now()` 生成唯一 ID，新会话插入列表头部。

### 6.6.4 发送时的消息管理

```typescript
// App.vue，第 384-392 行（sendQuery 开头）
const requestSessionId = currentSessionId.value
const sessionMessages = getSessionMessages(requestSessionId)
setCurrentSessionMessages(requestSessionId)

sessionMessages.push({ role: 'user', content: query })
inputMessage.value = ''
isThinking.value = true
const msgIdx = sessionMessages.length
sessionMessages.push({ role: 'assistant', content: '' })
```

用户消息和 assistant 占位消息依次压栈，`msgIdx` 记录 assistant 消息的索引，后续所有 SSE 事件通过该索引更新同一条消息的内容和状态。

---

## 6.7 Markdown 渲染链路

### 6.7.1 renderMarkdown 函数

```typescript
// App.vue，第 262-265 行
import DOMPurify from 'dompurify'
import { marked } from 'marked'

function renderMarkdown(text: string) {
  const html = marked.parse(text, { breaks: true, gfm: true }) as string
  return DOMPurify.sanitize(html)
}
```

两步处理：

1. **`marked.parse`** — 将 Markdown 转为 HTML，开启 `breaks: true`（换行转 `<br>`）和 `gfm: true`（GitHub Flavored Markdown，含表格、任务列表）
2. **`DOMPurify.sanitize`** — 净化 HTML，仅保留安全标签和属性，防止 XSS

### 6.7.2 v-html 绑定

```html
<!-- App.vue，第 97 行 -->
<div v-if="msg.content" class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
```

### 6.7.3 CSS 样式穿透

由于 `marked` 生成的 HTML 是动态 innerHTML，Vue 的 scoped CSS 无法直接作用于其内部的标签。使用 `:deep()` 选择器穿透作用域：

```css
/* App.vue，第 812-843 行 */
.markdown-body :deep(p) {
  margin: 0 0 10px;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 13px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid oklch(0.82 0.018 235);
  padding: 8px;
  vertical-align: top;
}

.markdown-body :deep(th) {
  background: oklch(0.93 0.012 220);
  font-weight: 750;
}
```

这确保了 Agent 返回的 Markdown 表格、列表、段落在前端有正确的排版。

---

## 6.8 API URL 配置优先级

前端需要知道后端 API 地址，配置采用**多级降级**策略。

### 6.8.1 完整逻辑

```typescript
// App.vue，第 197-208 行
const productionApiFallback = 'https://monthly-motel-understood-connection.trycloudflare.com'
const buildApiBaseUrl = import.meta.env.VITE_API_BASE_URL || ''
const isLocalApiBaseUrl = (value: string) => /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/i.test(value)
const apiBaseUrl = ref(
  import.meta.env.DEV
    ? buildApiBaseUrl || 'http://127.0.0.1:5000'
    : buildApiBaseUrl && !isLocalApiBaseUrl(buildApiBaseUrl)
      ? buildApiBaseUrl
      : productionApiFallback,
)
const apiAuthToken = ref(import.meta.env.VITE_API_AUTH_TOKEN || '')
let runtimeConfigPromise: Promise<void> | null = null
```

### 6.8.2 开发 (DEV) 模式

```
VITE_API_BASE_URL (若有) → http://127.0.0.1:5000 (无配置时的硬编码降级)
```

即 `.env.local` 中的 `VITE_API_BASE_URL=http://127.0.0.1:5000` 被使用，没有配置时也默认到 `http://127.0.0.1:5000`。

### 6.8.3 生产 (PROD) 模式

三级降级：

```
1. VITE_API_BASE_URL (非 localhost 地址)
2. /api/config 运行时配置（Cloudflare Pages Functions 注入）
3. Cloudflare Tunnel 硬编码回退 URL
```

`loadRuntimeConfig` 函数（第 267-298 行）实现了第二级降级：

```typescript
async function loadRuntimeConfig() {
  if (runtimeConfigPromise) return runtimeConfigPromise

  runtimeConfigPromise = (async () => {
    if (apiBaseUrl.value && apiAuthToken.value) return  // 已加载则跳过

    try {
      const response = await fetch('/api/config', {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      })
      if (!response.ok) return
      const config = (await response.json()) as {
        apiBaseUrl?: unknown
        apiAuthToken?: unknown
      }
      if (typeof config.apiBaseUrl === 'string' && config.apiBaseUrl) {
        apiBaseUrl.value = config.apiBaseUrl
      }
      if (typeof config.apiAuthToken === 'string') {
        apiAuthToken.value = config.apiAuthToken
      }
    } catch {
      // 本地 Vite dev 没有 Pages Functions 端点，忽略
    }
  })()

  return runtimeConfigPromise
}
```

`runtimeConfigPromise` 使用共享 Promise 模式，避免并发请求 /api/config 端点。

### 6.8.4 无可用 API 时的错误提示

```typescript
// App.vue，第 399-406 行
if (!apiBaseUrl.value) {
  replaceAssistantMessage(
    requestSessionId,
    msgIdx,
    '线上前端缺少后端 API 地址。请在 Cloudflare Pages 环境变量中设置 VITE_API_BASE_URL 为后端公网 HTTPS 地址，然后重新部署。也可以访问 /api/config 检查运行时配置是否生效。',
  )
  return
}
```

---

## 6.9 空状态与场景卡片

当 `messages` 为空数组时，渲染空状态界面，包含 6 个临床场景预设卡片：

```typescript
// App.vue，第 210-247 行
const scenarios = [
  {
    title: '抑郁筛查',
    summary: '低落、失眠、兴趣下降',
    icon: DataAnalysis,
    query: '患者近两周情绪低落、失眠、食欲下降，以前喜欢的活动现在也没兴趣了',
  },
  {
    title: '双相鉴别',
    summary: '情绪高涨后转低落',
    icon: DocumentChecked,
    query: '患者情绪忽高忽低，有时话多、精力旺盛，持续一周后转为情绪低落',
  },
  {
    title: '精神病性症状',
    summary: '幻听、被监视感',
    icon: Connection,
    query: '患者声称听到有人在议论自己，坚信被监视，不愿出门见人',
  },
  {
    title: '强迫症状',
    summary: '反复洗手和检查',
    icon: DocumentChecked,
    query: '患者反复洗手、检查门锁，每天花数小时，明知不必要但控制不住',
  },
  {
    title: '焦虑障碍',
    summary: '紧张、心慌、入睡困难',
    icon: DataAnalysis,
    query: '患者持续紧张不安、心慌、入睡困难，总是担心各种事情已半年',
  },
  {
    title: '药物审查',
    summary: '舍曲林与帕罗西汀',
    icon: FirstAidKit,
    query: '患者正在服用舍曲林和帕罗西汀，最近出现恶心、失眠加重',
  },
]
```

模板中遍历 `scenarios` 生成按钮：

```html
<!-- App.vue，第 66-80 行 -->
<div class="scenario-grid">
  <button
    v-for="scenario in scenarios"
    :key="scenario.title"
    class="scenario-card"
    type="button"
    @click="sendQuery(scenario.query)"
  >
    <span class="scenario-icon">
      <el-icon><component :is="scenario.icon" /></el-icon>
    </span>
    <span class="scenario-title">{{ scenario.title }}</span>
    <span class="scenario-text">{{ scenario.summary }}</span>
  </button>
</div>
```

点击场景卡片相当于直接发送预设 query，与手动输入发送走同一 `sendQuery` 路径。

---

## 6.10 总结

前端 SSE 消费的数据流总结：

```
后端 stream_chat generator
  → StreamingResponse (text/event-stream)
    → fetch ReadableStream
      → TextDecoder + line buffer
        → JSON.parse "data:" 行
          → done → 结束状态
          → status → 更新阶段气泡
          → content+agent → 追加消息 + 自动插入 Markdown 标题
            → marked.parse → DOMPurify.sanitize → v-html 渲染
```

关键设计要点：

- **双 stream_mode** 使前端能区分 "推理中" 和 "节点完成" 两种事件
- **Line buffering** + 不完整行保存保证跨 TCP 分片的数据完整性
- **Agent 切换检测** 自动在内容中插入 `### 标题`，给用户清晰的"视角切换"感知
- **纯客户端会话** 让 `session_id` 仅用于后端记忆键前缀，会话切换零延迟
- **三级 API URL 降级** 使前端在 Cloudflare Pages、本地开发、Tunnel 部署间无缝切换
