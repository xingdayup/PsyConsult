# 06｜第一次 API：给接待窗口寄一封信

## 学习目标

先用“信封”理解 Header、Body、Token 和 session，再发送一次真实请求，观察服务端持续返回的多段结果。

## 生活类比：一封有通行证的病例信

把一次请求想成寄往接待窗口的信：

- **信封外标签**写明寄件人和信件类型，接待员不拆信也能先检查；
- **信封内病例**写本轮临床问题；
- **通行证**证明请求知道约定的访问口令，但只有门诊启用门禁时才检查；
- **快递单号**把多次来信归到同一段会话，不能拿它当人的身份证明。

## 图解

```text
┌────────────── 一封请求 ──────────────┐
│ 信封外标签：内容类型、X-User-Id       │ ← Header
│ 通行证：Bearer local-dev-token       │ ← Token（配置后才强制）
│ 信封内病例：query                    │ ← Body
│ 快递单号：session_id                 │ ← session
└────────────────┬─────────────────────┘
                 ▼
              接待窗口
                 │
                 └─ data: 第一段
                    data: 第二段
                    data: {"done": true}
```

真实名称现在再对应一次：**Header 是 HTTP 请求头，Body 是 JSON 请求体，Token 放在 `Authorization: Bearer ...`，session 是 Body 中的 `session_id`。**

## 分步骤体验

先在一个终端启动后端。

**用途：** 开放本地接待窗口 `5000` 端口。  
**预期：** 终端显示服务启动；Redis/Milvus 的降级警告不应让进程退出。

```powershell
python -m uvicorn app.app_main:app --host 0.0.0.0 --port 5000 --reload
```

再开一个 PowerShell 发送请求。下面示例假定 `agent/.env` 配置了 `API_AUTH_TOKEN=local-dev-token`。

**用途：** 把信封寄到 `/api/chat`，`-N` 让多段结果立即显示。  
**预期：** 先看到 `accepted`，再看到缓存/专家阶段与内容，最后看到 `{"done": true}`。

```powershell
curl.exe -N -X POST "http://127.0.0.1:5000/api/chat" `
  -H "Content-Type: application/json" `
  -H "X-User-Id: doctor_demo" `
  -H "Authorization: Bearer local-dev-token" `
  --data-raw '{"query":"虚构病例：患者近两周情绪低落、失眠、兴趣下降，请给出鉴别方向。","session_id":"demo_api_001"}'
```

如果后端没有配置 `API_AUTH_TOKEN`，删除 `Authorization` 行即可；**`X-User-Id` 仍必须保留**。

## 项目真实实现

接口只从 JSON Body 接收两个业务字段：

```json
{
  "query": "本轮病例或问题",
  "session_id": "demo_api_001"
}
```

`X-User-Id` 来自 Header，始终必填且须符合规定字符格式。Bearer 由 [`app/router/chat.py`](../../app/router/chat.py) 检查，只有 `API_AUTH_TOKEN` 非空时才强制。`session_id` 会成为 Redis Checkpoint 的 `thread_id`；它用于会话关联，不等同于用户身份。

响应不是一次性 JSON，而是 `text/event-stream`：[`app/service/chat_service.py`](../../app/service/chat_service.py) 持续生成 `data: ...` 事件。

## 源码二刷

像追 Python 函数参数一样阅读：

1. [`app/schemas/chat.py`](../../app/schemas/chat.py)：Body 为什么只有 `query`、`session_id`；
2. [`app/router/chat.py`](../../app/router/chat.py)：Header 如何变成 `user_id`；
3. [`app/service/chat_service.py`](../../app/service/chat_service.py)：三者如何进入 `stream_chat(query, user_id, session_id)`；
4. 搜索 `emit_sse`：返回内容如何加上 `data:` 和空行。

## 面试背板

> API 契约把身份和业务内容分开：`X-User-Id` 始终必填，JSON Body 只含 `query` 与 `session_id`；Bearer 仅在服务端配置共享 Token 后强制。`session_id` 映射为 Checkpoint 的线程号，用于恢复上下文，但不能当作认证凭证。长任务通过 SSE 在一次 POST 响应中持续返回状态和内容。

## 常见问题

**为什么 Body 里没有 `user_id`？** 当前真实接口从 `X-User-Id` Header 取得用户标识。

**有 `session_id` 为什么还要 `X-User-Id`？** 前者关联会话，后者标记调用者，职责不同。

**HTTP 200 是否代表分析正确？** 只代表流成功建立，不能证明过程完成或医学内容正确。

**PowerShell 的 `curl` 为什么表现不同？** 使用明确的 `curl.exe`，避免命中 PowerShell 别名。

## 自测

1. 信封外标签、信封内病例、通行证、快递单号分别对应什么？
2. 哪个字段始终必填？
3. Body 中有哪些字段？
4. 最后一段完成事件长什么样？

## 导航

- 上一页：[第一次 CLI](first-cli.md)
- 下一页：[第一次浏览器体验](first-browser.md)
- 相关源码：[`app/router/chat.py`](../../app/router/chat.py)
