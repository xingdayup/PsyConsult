# Clinical CDS 使用指南

本文档说明如何在本地启动并使用当前加固后的 Clinical CDS 原型，包括后端鉴权、前端配置、基础服务、验证命令和常见问题。

## 1. 前置条件

项目根目录：

```powershell
cd <项目根目录>
```

当前推荐使用的 Python 虚拟环境：

```powershell
python
```

需要本机已安装：

- Docker Desktop，用于 Redis、Milvus、Neo4j、MySQL。
- Node.js，前端要求 `^20.19.0 || >=22.12.0`。
- 可用的大模型 API Key，例如 DashScope。

## 2. 配置环境变量

后端和 agent 默认读取 `agent/.env`。如果没有这个文件，先新建：

```powershell
New-Item -ItemType File -Path agent\.env
```

写入最小配置：

```env
DASHSCOPE_API_KEY=你的DashScopeKey
REDIS_URL=redis://localhost:6379
MILVUS_HOST=localhost
MILVUS_PORT=19530
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123

# 本地原型鉴权。设置后，/api/chat 必须带 Authorization: Bearer local-dev-token
API_AUTH_TOKEN=local-dev-token

# 默认只允许本地 Vite 前端访问
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

前端可以新建 `front/clinical_cds/.env.local`：

```env
VITE_API_BASE_URL=http://127.0.0.1:5000
VITE_API_AUTH_TOKEN=local-dev-token
```

如果你暂时不想启用 API token，可以删除或留空后端 `API_AUTH_TOKEN`，同时前端 `VITE_API_AUTH_TOKEN` 也留空。但仍需要通过前端发送 `X-User-Id`。

## 3. 安装依赖

Python 依赖：

```powershell
& 'python' -m pip install -r agent\requirements.txt
```

前端依赖：

```powershell
cd front\clinical_cds
npm install
cd ..\..
```

## 4. 启动基础服务

启动 Redis、Milvus、Neo4j、MySQL：

```powershell
cd docker
docker compose up -d
cd ..
```

检查容器：

```powershell
docker compose -f docker\docker-compose.yml ps
```

Neo4j 浏览器默认地址：

```text
http://localhost:7474
```

默认账号密码：

```text
neo4j / password123
```

## 5. 启动后端

推荐从项目根目录用包方式启动：

```powershell
& 'python' -m uvicorn app.app_main:app --host 0.0.0.0 --port 5000 --reload
```

后端地址：

```text
http://127.0.0.1:5000
```

聊天接口：

```text
POST http://127.0.0.1:5000/api/chat
```

接口返回 `text/event-stream`，前端会按 SSE 流式读取。

后端会同时把日志输出到控制台和文件：

```text
logs/backend.log
```

实时查看日志：

```powershell
Get-Content logs\backend.log -Wait
```

每次聊天请求会看到类似下面的耗时记录：

```text
event=chat_step user_id=doctor_001 session_id=session_demo step=semantic_cache_check elapsed=0.123s total=0.123s
event=chat_step user_id=doctor_001 session_id=session_demo step=memory_context_extract elapsed=0.045s total=0.168s
event=agent_node_complete user_id=doctor_001 session_id=session_demo node=orchestrator elapsed=1.234s
event=chat_step user_id=doctor_001 session_id=session_demo step=agent_workflow elapsed=6.789s total=6.957s
event=chat_step user_id=doctor_001 session_id=session_demo step=sse_complete elapsed=0.001s total=6.958s
```

常见 `step` 含义：

- `local_input_validation`：输入过短等本地校验。
- `semantic_cache_check`：Milvus 语义缓存检查。
- `memory_context_extract`：Redis/Milvus 记忆上下文提取。
- `agent_workflow`：LangGraph 多 Agent 推理总耗时。
- `short_term_memory_save`：短期记忆写入 Redis。
- `sse_complete`：SSE 响应完成。

## 6. 启动前端

打开新终端：

```powershell
cd <项目根目录>\front\clinical_cds
npm run dev
```

浏览器访问：

```text
http://localhost:5173
```

页面中输入症状、诊断问题或用药方案即可。前端会自动发送：

- `X-User-Id: doctor_001`
- `Authorization: Bearer <VITE_API_AUTH_TOKEN>`，仅当 `.env.local` 配置了 token 时发送。

## 7. 直接用 curl 测试接口

启用 `API_AUTH_TOKEN=local-dev-token` 时：

```powershell
curl.exe -N -X POST http://127.0.0.1:5000/api/chat `
  -H "Content-Type: application/json" `
  -H "X-User-Id: doctor_001" `
  -H "Authorization: Bearer local-dev-token" `
  -d "{\"query\":\"患者近两周情绪低落、失眠、兴趣下降，请做鉴别诊断\",\"session_id\":\"session_demo\"}"
```

未带 token 时应返回 401：

```powershell
curl.exe -i -X POST http://127.0.0.1:5000/api/chat `
  -H "Content-Type: application/json" `
  -H "X-User-Id: doctor_001" `
  -d "{\"query\":\"患者近两周情绪低落\",\"session_id\":\"session_demo\"}"
```

未带 `X-User-Id` 时应返回 400：

```powershell
curl.exe -i -X POST http://127.0.0.1:5000/api/chat `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer local-dev-token" `
  -d "{\"query\":\"患者近两周情绪低落\",\"session_id\":\"session_demo\"}"
```

## 8. 常用验证命令

Python 编译检查：

```powershell
& 'python' -m compileall -q agent app
```

后端包导入检查：

```powershell
& 'python' -c "import app.app_main; print('ok')"
```

后端自动化测试：

```powershell
& 'python' -m pytest -q
```

前端类型检查：

```powershell
cd front\clinical_cds
npm run type-check
```

前端构建：

```powershell
npm run build
```

`npm run build` 可能出现依赖包 pure annotation 或 chunk size warning，只要命令退出码为 0，就表示构建成功。

## 9. 常见问题

### 401 Unauthorized

原因：后端设置了 `API_AUTH_TOKEN`，请求没有带正确的 `Authorization: Bearer ...`。

处理：

- 前端：确认 `front/clinical_cds/.env.local` 中的 `VITE_API_AUTH_TOKEN` 和后端一致。
- curl：确认 header 是 `Authorization: Bearer local-dev-token`。

### 400 Missing X-User-Id header

原因：后端要求通过 `X-User-Id` 指定当前医生或用户身份。

处理：

- 前端默认会发送 `doctor_001`。
- curl 需要手动加 `-H "X-User-Id: doctor_001"`。

### 后端启动时报模型 Key 缺失

原因：`agent/.env` 没有配置 `DASHSCOPE_API_KEY`，或当前终端没有读到环境文件。

处理：

```powershell
Get-Content agent\.env
```

确认文件里有：

```env
DASHSCOPE_API_KEY=你的DashScopeKey
```

### 图谱或检索不可用

原因：Redis、Milvus、Neo4j 未启动，或还没有导入 mock 数据。

处理：

```powershell
docker compose -f docker\docker-compose.yml ps
```

如果服务没启动：

```powershell
cd docker
docker compose up -d
```

### 浏览器跨域失败

原因：前端地址不在后端 `CORS_ORIGINS` 白名单。

处理：在 `agent/.env` 中加入实际前端地址，例如：

```env
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

修改后重启后端。

## 10. 重要提醒

本项目是临床决策支持原型，只能用于学习、演示和开发验证。不要输入真实患者身份信息，不要把系统输出直接作为诊断或处方依据。诊断和用药必须由执业医师结合病史、查体、量表、实验室检查和最新指南确认。
