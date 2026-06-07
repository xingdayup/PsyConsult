# 09. 面试截图清单

准备 8 张左右截图即可，不要太多。每张截图都要能证明一个能力点。

## 1. 项目目录结构

**截图位置：** 项目根目录。  
**要框出来：** `agent/`、`app/`、`front/clinical_cds/`、`docker/`、`docs/`。  
**讲解词：**  
项目按前端、FastAPI 后端、Agent 系统、基础设施和文档分层，方便独立开发和部署。

## 2. LangGraph 工作流

**截图位置：** `agent/core/workflow/graph_manager.py`。  
**要框出来：** `add_node`、`add_conditional_edges`、`add_edge`。  
**讲解词：**  
Orchestrator 先路由，再进入诊断、治疗和药物审查节点。诊断链路会继续串到治疗和药物审查，形成临床辅助决策闭环。

## 3. AgentState

**截图位置：** `agent/core/workflow/state.py`。  
**要框出来：** `messages`、`user_id`、`session_id`、`memory_context`。  
**讲解词：**  
State 是各 Agent 共享的数据载体，既传递消息，也传递用户、会话和记忆上下文。

## 4. Diagnosis Prompt

**截图位置：** `agent/agents/diagnosis_agent.py`。  
**要框出来：** `_build_system_prompt()` 中症状提取、鉴别诊断、约束三段。  
**讲解词：**  
Prompt 不是简单角色扮演，而是明确任务步骤、工具、输出格式和禁止编造。

## 5. Agent 内部流式

**截图位置：** `agent/agents/diagnosis_agent.py`。  
**要框出来：** `get_stream_writer()`、`AIMessageChunk`、`writer({"chunk": buffer})`。  
**讲解词：**  
Agent 生成过程中主动把 chunk 写回 LangGraph custom stream，前端可以实时显示内容，而不是等节点完成。

## 6. 后端 SSE

**截图位置：** `app/service/chat_service.py`。  
**要框出来：** `emit_sse()`、第一条 `accepted`、`graph.astream(... stream_mode=["updates", "custom"])`。  
**讲解词：**  
后端统一封装 SSE 输出，并记录每次 emit 的耗时，方便定位首字节和慢节点。

## 7. API 路由与安全

**截图位置：** `app/router/chat.py`。  
**要框出来：** `require_chat_identity()`、`StreamingResponse`、headers。  
**讲解词：**  
接口支持 SSE，用户身份从请求头读取，可选 Bearer Token，并设置防缓冲 header。

## 8. 前端流式解析

**截图位置：** `front/clinical_cds/src/App.vue`。  
**要框出来：** `reader.read()` 循环、`parsed.status`、`parsed.content`。  
**讲解词：**  
前端用 fetch 读取 ReadableStream。status 更新阶段条，content 追加 Markdown 正文。

## 9. 前端安全渲染

**截图位置：** `front/clinical_cds/src/App.vue`。  
**要框出来：** `renderMarkdown()`、`DOMPurify.sanitize()`。  
**讲解词：**  
模型输出不能直接 v-html 渲染，先 Markdown 转 HTML，再用 DOMPurify 防 XSS。

## 10. 数据工具

**截图位置：** `agent/tools/vector_tool.py` 和 `agent/tools/graph_tool.py`。  
**要框出来：** `query_vector_db()`、`query_knowledge_graph()`。  
**讲解词：**  
向量库负责指南和诊断标准检索，图谱负责疾病、症状、药物关系查询。

## 11. 线上 CORS 排障

**截图位置：** 终端命令输出。  
**命令：**

```powershell
curl.exe -i -X OPTIONS https://你的后端地址/api/chat `
  -H "Origin: https://psyconsult.pages.dev" `
  -H "Access-Control-Request-Method: POST" `
  -H "Access-Control-Request-Headers: content-type,x-user-id"
```

**讲解词：**  
POST 能通不代表浏览器能用，浏览器还会先发 CORS 预检。这个截图可以证明你处理过真实线上部署问题。

## 12. Demo 页面

**截图位置：** `https://psyconsult.pages.dev/`。  
**要框出来：** 阶段提示、流式回答、多会话列表。  
**讲解词：**  
这是最终用户视角，展示系统能按阶段反馈，并输出结构化临床辅助建议。

