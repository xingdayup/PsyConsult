# 06. 前端与安全

## 模块解决的问题

前端需要让医生高效输入病例、看到流式状态、切换多个诊疗会话，并安全渲染模型返回的 Markdown。核心难点不是页面展示，而是流式解析和状态管理。

## 会话本地缓存

核心文件：`front/clinical_cds/src/App.vue`

```ts
const messagesBySession = ref<Record<string, ChatMessage[]>>({
  [currentSessionId.value]: [],
})
const messages = ref<ChatMessage[]>([])

function getSessionMessages(sessionId: string): ChatMessage[] {
  if (!messagesBySession.value[sessionId]) {
    messagesBySession.value[sessionId] = []
  }
  return messagesBySession.value[sessionId]
}
```

面试讲法：  
每个 `session_id` 有自己的消息数组。用户新建会话时不会清掉旧会话，切回旧会话可以恢复之前的消息。当前是浏览器内存缓存，不跨刷新持久化。

## SSE 前端解析

```ts
const reader = response.body.getReader()
const decoder = new TextDecoder()
let buffer = ''

while (true) {
  const { done, value } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })
  const lines = buffer.split('\n')
  buffer = lines.pop() || ''

  for (const line of lines) {
    if (!line.startsWith('data: ')) continue
    const parsed = JSON.parse(line.slice(6))
    ...
  }
}
```

面试讲法：  
前端没有用 EventSource，因为需要 POST JSON body。用 `fetch()` 拿到 `ReadableStream` 后手动按 SSE 行解析。

## 阶段提示与正文分离

```ts
if (parsed.status) {
  updateAssistantStatus(requestSessionId, msgIdx, statusLabel(parsed))
  continue
}

if (parsed.content) {
  appendAssistantMessage(requestSessionId, msgIdx, label + parsed.content)
}
```

面试讲法：  
后端返回 status 和 content 两类事件。前端把阶段状态展示在状态条里，正文内容追加到 Markdown 气泡中，避免“进度提示污染最终答案”。

## API 地址配置

```ts
const productionApiFallback = 'https://monthly-motel-understood-connection.trycloudflare.com'
const buildApiBaseUrl = import.meta.env.VITE_API_BASE_URL || ''
const isLocalApiBaseUrl = (value: string) =>
  /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/i.test(value)
```

面试讲法：  
线上部署时遇到过 Vite 构建变量、Pages Function 运行时变量、Cloudflare Tunnel 地址变化的问题，所以前端做了多层兜底：构建变量、运行时配置、本地开发地址、生产临时 tunnel。

## Markdown XSS 防护

```ts
function renderMarkdown(text: string) {
  const html = marked.parse(text, { breaks: true, gfm: true }) as string
  return DOMPurify.sanitize(html)
}
```

面试讲法：  
模型输出不应该被直接 `v-html` 渲染。这里先用 `marked` 转 Markdown，再用 `DOMPurify` 清洗，防止 `<img onerror=...>` 这类 XSS。

## 后端安全边界

核心文件：`app/router/chat.py`

- `X-User-Id` 从请求头读取，不信任 body。
- 可选 `Authorization: Bearer <token>`。
- `X-User-Id` 只允许有限字符和长度。
- 请求 schema 对 `query`、`session_id` 做长度/格式限制。

## 面试 Q&A

**Q：为什么不用 EventSource？**  
A：EventSource 主要适合 GET，而聊天请求需要 POST JSON body 和自定义请求头，所以用 `fetch()` 的 `ReadableStream` 手动解析 SSE。

**Q：你怎么避免前端多会话串流写错窗口？**  
A：发送请求时记录 `requestSessionId` 和 assistant 消息下标，流式返回时始终写入这个 session 的消息数组，即使用户切换窗口，也不会污染当前窗口。

**Q：模型返回 Markdown，为什么还要 DOMPurify？**  
A：因为模型内容可能包含 HTML。前端使用 `v-html` 时必须先消毒，防止 XSS。

## 截图建议

- 截 `messagesBySession` 和 `getSessionMessages()`。
- 截 SSE `reader.read()` 解析循环。
- 截 `parsed.status` 与 `parsed.content` 的分支。
- 截 `renderMarkdown()` 中的 `DOMPurify.sanitize()`。

