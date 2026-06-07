# 第七章：部署配置参考

## 7.1 概述

本系统涉及多个基础设施组件（Redis、Milvus、Neo4j、MySQL）和两套独立的 Pydantic Settings 类。本文档提供一份完整的环境变量字典、两套 Settings 的对比表、Docker Compose 服务说明、前端构建配置、pytest 配置以及本地开发启动检查清单。

---

## 7.2 完整环境变量字典

所有环境变量均读取自项目根目录下的 `agent/.env` 文件。两个 Settings 类（`agent/config/settings.py` 和 `app/app_config/settings.py`）各自加载此文件的子集。

### 7.2.1 LLM 配置

| 变量 | 文件 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `LLM_API_KEY` | 两者 | `str \| None` | `None` | 聊天模型 API Key，优先级高于 DASHSCOPE_API_KEY |
| `DASHSCOPE_API_KEY` | 两者 | `str` | 必填 (agent) / `str` (app) | 阿里 DashScope API Key，作为 LLM Key 的兜底 |
| `MODEL` | agent | `str` | `"qwen-plus"` | 模型名称，也用于 LangChain ChatOpenAI |
| `BASE_URL` | 两者 | `str \| None` | `None` | API 端点 URL，可切换为 DeepSeek 等兼容端点 |
| `EMBEDDING_API_KEY` | 两者 | `str \| None` | `None` | 向量模型专用 Key |
| `DASHSCOPE_EMBEDDING_API_KEY` | agent | `str \| None` | `None` | DashScope embedding 专用 Key |
| `ENABLE_LLM_GRAPH_CYPHER` | agent .env | `str` | `"false"` | 是否启用 LLM 生成 Cypher（未暴露为 Pydantic 字段） |

### 7.2.2 MCP 配置

| 变量 | 文件 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `MCP_SERVERS_CONFIG` | agent | `Path` | `config/mcp_servers.json` | MCP 服务器配置文件路径 |

### 7.2.3 Redis (短期记忆)

| 变量 | 文件 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `REDIS_URL` | 两者 | `str` | `"redis://localhost:6379"` | Redis 连接 URL |
| `REDIS_TTL` | agent | `int` | `1800` | 短期记忆 TTL（秒） |

### 7.2.4 Milvus (长期记忆 + 语义缓存)

| 变量 | 文件 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `MILVUS_HOST` | 两者 | `str` | `"localhost"` | Milvus 主机地址 |
| `MILVUS_PORT` | 两者 | `int` | `19530` | Milvus gRPC 端口 |
| `MILVUS_API_KEY` | 两者 | `str \| None` | `None` | Milvus 鉴权 Key (Zilliz Cloud) |
| `ENABLE_SEMANTIC_CACHE` | app | `bool` | `True` | 是否启用语义缓存 |

### 7.2.5 Neo4j (知识图谱)

| 变量 | 文件 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `NEO4J_URI` | agent | `str` | `"bolt://localhost:7687"` | Neo4j Bolt 连接 URI |
| `NEO4J_USER` | agent | `str` | `"neo4j"` | Neo4j 用户名 |
| `NEO4J_PASSWORD` | agent | `str` | `"password"` | Neo4j 密码 |
| `NEO4J_DATABASE` | agent | `str` | `"neo4j"` | Neo4j 数据库名 |

### 7.2.6 MySQL (暂未接入)

| 变量 | 所属文件 | 说明 |
|------|---------|------|
| `MYSQL_HOST` | .env | 暂未被 Settings 加载，计划存放患者结构化画像 |
| `MYSQL_PORT` | .env | |
| `MYSQL_USER` | .env | |
| `MYSQL_PASSWORD` | .env | |
| `MYSQL_DATABASE` | .env | |

### 7.2.7 鉴权

| 变量 | 文件 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `API_AUTH_TOKEN` | app | `str \| None` | `None` | Bearer Token 鉴权值，空则不启用 Token 检查 |

### 7.2.8 CORS

| 变量 | 文件 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `CORS_ORIGINS` | app | `str` | `"http://localhost:5173,http://127.0.0.1:5173"` | 逗号分隔的允许跨域源列表 |

### 7.2.9 日志

| 变量 | 文件 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `LOG_LEVEL` | agent | `str` | `"INFO"` | 日志级别 (DEBUG/INFO/WARNING/ERROR) |

### 7.2.10 前端

| 变量 | 文件 | 说明 |
|------|------|------|
| `VITE_API_BASE_URL` | `.env.local` / `.env.production` | 后端 API 基础 URL |
| `VITE_API_AUTH_TOKEN` | `.env.production` | 前端发送的 Bearer Token（生产环境） |

---

## 7.3 两套 Settings 完整对比表

### agent/config/settings.py

基于 `pydantic-settings`，使用 `@lru_cache` 缓存实例。读 `agent/.env`（相对路径）。提供辅助方法 `get_model_config()`、`get_llm_api_key()`、`get_embedding_api_key()`。

### app/app_config/settings.py

模块级单例 `settings = Settings()`，直接暴露所有字段。读 `agent/.env`（绝对路径拼接）。为 FastAPI 层提供 `get_cors_origins()` 方法和 `api_auth_token` 字段。

### 字段对比

| 字段 | agent/config/settings.py | app/app_config/settings.py | 类型 (agent) | 类型 (app) | 默认值 (agent) | 默认值 (app) |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| `dashscope_api_key` | ✅ (alias DASHSCOPE_API_KEY) | ✅ | `str` | `str` | 必填验证 | 必填 |
| `llm_api_key` | ✅ (alias LLM_API_KEY) | ✅ | `str \| None` | `str \| None` | `None` | `None` |
| `model` | ✅ (alias MODEL) | ❌ | `str` | — | `"qwen-plus"` | — |
| `base_url` | ✅ (alias BASE_URL) | ✅ | `str \| None` | `str \| None` | `None` | `None` |
| `embedding_api_key` | ✅ (alias EMBEDDING_API_KEY) | ✅ | `str \| None` | `str \| None` | `None` | `None` |
| `dashscope_embedding_api_key` | ✅ (alias DASHSCOPE_EMBEDDING_API_KEY) | ❌ | `str \| None` | — | `None` | — |
| `mcp_servers_config` | ✅ (alias MCP_SERVERS_CONFIG) | ❌ | `Path` | — | `config/mcp_servers.json` | — |
| `openweather_api_key` | ✅ (alias OPENWEATHER_API_KEY) | ❌ | `str \| None` | — | `None` | — |
| `redis_url` | ✅ (alias REDIS_URL) | ✅ | `str` | `str` | `"redis://localhost:6379"` | 必填 |
| `redis_ttl` | ✅ (alias REDIS_TTL) | ❌ | `int` | — | `1800` | — |
| `milvus_host` | ✅ (alias MILVUS_HOST) | ✅ | `str` | `str` | `"localhost"` | `"localhost"` |
| `milvus_port` | ✅ (alias MILVUS_PORT) | ✅ | `int` | `int` | `19530` | `19530` |
| `milvus_api_key` | ✅ (alias MILVUS_API_KEY) | ✅ | `str \| None` | `str \| None` | `None` | `None` |
| `neo4j_uri` | ✅ (alias NEO4J_URI) | ❌ | `str` | — | `"bolt://localhost:7687"` | — |
| `neo4j_user` | ✅ (alias NEO4J_USER) | ❌ | `str` | — | `"neo4j"` | — |
| `neo4j_password` | ✅ (alias NEO4J_PASSWORD) | ❌ | `str` | — | `"password"` | — |
| `neo4j_database` | ✅ (alias NEO4J_DATABASE) | ❌ | `str` | — | `"neo4j"` | — |
| `log_level` | ✅ (alias LOG_LEVEL) | ❌ | `str` | — | `"INFO"` | — |
| `api_auth_token` | ❌ | ✅ | — | `str \| None` | — | `None` |
| `cors_origins` | ❌ | ✅ | — | `str` | — | `"http://localhost:5173,http://127.0.0.1:5173"` |
| `enable_semantic_cache` | ❌ | ✅ | — | `bool` | — | `True` |

字段差异解读：

- `agent/config/settings.py` 关注 **Agent 推理层的完整配置**：模型名、MCP、Neo4j、日志级别、天气 API（遗留字段），以及 Redis TTL
- `app/app_config/settings.py` 关注 **FastAPI 接口层的运行配置**：鉴权 token、CORS 源、语义缓存开关，以及基础设施连接所需的子集
- 相同字段在两者中的类型和默认值基本一致（`redis_url` 在 app 中无默认值、必须显式配置）

### 实例化方式

```python
# agent/config/settings.py — @lru_cache 缓存
@lru_cache
def get_settings() -> Settings:
    return Settings()

# app/app_config/settings.py — 模块级单例
settings = Settings()
```

---

## 7.4 Docker Compose 服务

所有基础服务定义在 `docker/docker-compose.yml` 中。

### 7.4.1 服务总览

```yaml
# docker/docker-compose.yml（完整）
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    container_name: clinical_redis
    ports:
      - "6379:6379"
    restart: unless-stopped

  milvus:
    image: milvusdb/milvus:v2.4.0
    container_name: clinical_milvus
    command: ["milvus", "run", "standalone"]
    ports:
      - "19530:19530"
      - "9091:9091"
    environment:
      ETCD_USE_EMBED: "true"
      ETCD_DATA_DIR: /var/lib/milvus/etcd
      COMMON_STORAGETYPE: local
    restart: unless-stopped

  neo4j:
    image: neo4j:5-community
    container_name: clinical_neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/password123
      NEO4J_PLUGINS: '["apoc"]'
    restart: unless-stopped

  mysql:
    image: mysql:8.0
    container_name: clinical_mysql
    ports:
      - "3306:3306"
    environment:
      MYSQL_ROOT_PASSWORD: 123456
      MYSQL_DATABASE: clinical_cds
    restart: unless-stopped
```

### 7.4.2 服务详情

| 服务 | 镜像 | 容器名 | 端口 | 默认认证 | 用途 |
|------|------|--------|------|---------|------|
| Redis | `redis:7-alpine` | `clinical_redis` | 6379 | 无 | 短期记忆存储、消息 TTL 裁剪 |
| Milvus | `milvusdb/milvus:v2.4.0` | `clinical_milvus` | 19530 (gRPC), 9091 (HTTP) | 无 | 长期偏好存储、语义缓存向量检索 |
| Neo4j | `neo4j:5-community` | `clinical_neo4j` | 7474 (HTTP), 7687 (Bolt) | `neo4j / password123` | 知识图谱（疾病-症状-药物关系） |
| MySQL | `mysql:8.0` | `clinical_mysql` | 3306 | `root / 123456` | 结构化患者数据（暂未接入代码） |

Milvus 的特殊配置：

- `ETCD_USE_EMBED: "true"` — 使用嵌入式 etcd（非独立部署 etcd 集群）
- `COMMON_STORAGETYPE: local` — 使用本地存储而非 S3/MinIO

### 7.4.3 常用命令

```bash
# 启动全部服务
docker compose -f docker/docker-compose.yml up -d

# 检查服务状态
docker compose -f docker/docker-compose.yml ps

# 查看日志
docker compose -f docker/docker-compose.yml logs -f

# 停止服务
docker compose -f docker/docker-compose.yml down

# 停止并删除数据卷
docker compose -f docker/docker-compose.yml down -v
```

---

## 7.5 前端构建配置

### 7.5.1 vite.config.ts

```typescript
// front/clinical_cds/vite.config.ts
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

export default defineConfig({
  plugins: [
    vue(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
})
```

插件：`@vitejs/plugin-vue` + `vite-plugin-vue-devtools`。别名 `@` 映射到 `./src`。

### 7.5.2 .env.local（开发用）

```env
# front/clinical_cds/.env.local
VITE_API_BASE_URL=http://127.0.0.1:5000
```

### 7.5.3 .env.production.example

```env
# front/clinical_cds/.env.production.example
VITE_API_BASE_URL=https://your-backend-public-url.example.com
VITE_API_AUTH_TOKEN=
```

> 注意：`.env.production` 不会被提交到 Git。生产部署时需在 Cloudflare Pages 的环境变量面板中设置这些变量。

### 7.5.4 npm 脚本

```json
// front/clinical_cds/package.json — scripts 节
{
  "dev": "vite",                                   // 启动开发服务器 → localhost:5173
  "build": "run-p type-check \"build-only {@}\" --", // 类型检查 + 构建（并行）
  "preview": "vite preview",                       // 预览构建产物
  "build-only": "vite build",                      // 仅构建（不类型检查）
  "type-check": "vue-tsc --build"                  // 仅类型检查
}
```

`type-check` 使用 `vue-tsc --build` 进行完整的 TypeScript 类型检查。`build` 使用 `npm-run-all2` 的 `run-p` 并行执行类型检查和构建。

### 7.5.5 Node.js 版本要求

```json
"engines": {
  "node": "^20.19.0 || >=22.12.0"
}
```

---

## 7.6 pytest 配置

```ini
# pytest.ini
[pytest]
testpaths = app/test
python_files = test_*.py *_test.py
```

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `testpaths` | `app/test` | 测试文件所在目录 |
| `python_files` | `test_*.py *_test.py` | 匹配两种命名风格 |

### 现有测试文件

| 文件 | 测试内容 |
|------|---------|
| `app/test/test_chat_security.py` | 鉴权（token 校验、X-User-Id 正则、401/400 响应） |
| `app/test/test_backend_logging.py` | 日志配置（handler 去重、日志轮转、force 重配置） |
| `agent/test/clinical_test.py` | 临床 Agent 流程手动测试 |
| `agent/test/build_kg.py` | Neo4j 知识图谱构建脚本 |
| `agent/test/milvus_rag.py` | Milvus RAG 检索测试 |

### 常用命令

```bash
# 运行全部测试
python -m pytest -q

# 运行单个测试文件
python -m pytest app/test/test_chat_security.py -q

# 运行单个测试用例
python -m pytest app/test/test_chat_security.py::test_xxx -q
```

---

## 7.7 本地开发启动检查清单

### 步骤 1：启动基础服务

```bash
docker compose -f docker/docker-compose.yml up -d
```

检查所有服务是否正常运行：

```bash
docker compose -f docker/docker-compose.yml ps
```

预期输出（所有服务 `Up` 状态）：

```
NAME               STATUS          PORTS
clinical_redis     Up              ......
clinical_milvus    Up              ......
clinical_neo4j     Up              ......
clinical_mysql     Up              ......
```

### 步骤 2：配置 agent/.env

最少需要以下配置项（替换 API Key 为实际值）：

```env
LLM_API_KEY=sk-your-key
BASE_URL=https://api.deepseek.com/v1
DASHSCOPE_API_KEY=sk-your-dashscope-key
```

基础设施连接信息保持默认值（指向 localhost）即可。

### 步骤 3：安装 Python 依赖

```bash
pip install -r agent/requirements.txt
```

验证导入：

```bash
python -c "import app.app_main; print('ok')"
```

### 步骤 4：（可选）构建知识图谱

```bash
python agent/test/build_kg.py
```

此步骤从数据文件构建 Neo4j 图谱，填充 `Disease`、`Symptom`、`Drug` 等节点和关系。不执行此步骤时 Agent 仍可运行，但会缺少图谱查询结果。

### 步骤 5：启动后端

```bash
python -m uvicorn app.app_main:app --host 0.0.0.0 --port 5000 --reload
```

或直接运行：

```bash
python app/app_main.py
```

启动日志应显示：

```
event=logging_configured log_file=...
event=agent_system_init step=graph_start
event=agent_system_init step=memory_start
event=agent_system_init step=complete
```

表示 Agent 图和记忆系统初始化成功。

### 步骤 6：启动前端

```bash
cd front/clinical_cds
npm install
npm run dev
```

前端开发服务器应启动在 `http://localhost:5173`。

### 步骤 7：验证端到端连通

使用 curl 发送测试请求：

```bash
curl -X POST http://127.0.0.1:5000/api/chat \
  -H "Content-Type: application/json" \
  -H "X-User-Id: doctor_001" \
  -d '{"query": "患者近两周情绪低落、失眠", "session_id": "test_session"}' \
  --no-buffer
```

如果配置了 `API_AUTH_TOKEN`，需额外添加 `-H "Authorization: Bearer <token>"`。

正常响应以 `data: {"status": "accepted", "content": "已接收病例，开始分析..."}` 开头，以 `data: {"done": true}` 结尾。

---

## 7.8 后端日志配置

后端日志由 `app/infra/logging_config.py` 统一初始化，在 `app_main.py` 的 lifespan 启动时调用。

### 7.8.1 日志格式

```python
# app/infra/logging_config.py 第 10 行
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
```

示例输出：

```
2026-06-07 14:30:00,123 INFO clinical_cds.chat event=chat_request_start user_id=doctor_001 session_id=test_session query_chars=15
```

### 7.8.2 双 Handler

```python
# app/infra/logging_config.py，第 32-48 行
# 1. 控制台 Handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler._clinical_cds_handler = True

# 2. 文件 Handler（轮转：5MB x 5 备份）
file_handler = RotatingFileHandler(
    log_path,
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=5,              # 保留 5 个备份
    encoding="utf-8",
)
file_handler.setFormatter(formatter)
file_handler._clinical_cds_handler = True

root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)
```

日志文件默认写入项目根目录的 `logs/backend.log`。

### 7.8.3 去重保护

```python
# app/infra/logging_config.py，第 29-30 行
elif any(getattr(handler, "_clinical_cds_handler", False) for handler in root_logger.handlers):
    return log_path
```

通过在每个 handler 上设置 `_clinical_cds_handler = True` 标记，防止 `configure_backend_logging` 被重复调用时添加重复 handler。配合 `force=True` 参数可强制重新配置（先移除所有旧 handler）。

### 7.8.4 日志分层

| Logger Name | 模块 | 用途 |
|-------------|------|------|
| `clinical_cds` | 通用 | 日志初始化事件 |
| `clinical_cds.chat` | `app/service/chat_service.py` | SSE 事件、缓存命中、Agent 执行步骤 |
| `clinical_cds.agent` | `agent/` 目录下各模块 | Agent 内部日志 |

---

## 7.9 最小部署检查清单

```bash
# ====== 基础设施 ======
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml ps

# ====== 后端 ======
# 执行环境：系统 Python（虚拟环境 E:\000WORK\学习文档\cloud_agent\.venv\Scripts\python.exe）
pip install -r agent/requirements.txt
python -m compileall -q agent app          # 编译检查
python -m uvicorn app.app_main:app --reload

# ====== 前端 ======
cd front/clinical_cds
npm install
npm run dev

# ====== 验证 ======
curl -X POST http://127.0.0.1:5000/api/chat \
  -H "Content-Type: application/json" \
  -H "X-User-Id: doctor_001" \
  -d '{"query":"测试","session_id":"check"}'

# ====== 测试 ======
python -m pytest -q

# ====== 前端构建 ======
npm run type-check   # 类型检查
npm run build-only   # 仅构建（部署到 Cloudflare Pages 时使用）
```
