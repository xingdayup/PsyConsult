# 环境配置与启动

## 运行前准备

需要准备：

- Python，建议 3.10 或更新版本。
- Node.js，前端 `package.json` 要求 `^20.19.0 || >=22.12.0`。
- Docker Desktop 或可运行 Docker Compose 的环境。
- DashScope API Key，用于 Qwen Chat 和 `text-embedding-v2` 向量模型。

## 基础服务配置

基础服务定义在 `docker/docker-compose.yml`：

```yaml
services:
  redis:
    ports:
      - "6379:6379"

  milvus:
    image: milvusdb/milvus:v2.4.0
    ports:
      - "19530:19530"
      - "9091:9091"

  neo4j:
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/password123

  mysql:
    ports:
      - "3306:3306"
```

启动：

```bash
cd docker
docker compose up -d
```

查看服务：

```bash
docker compose ps
```

停止服务：

```bash
docker compose down
```

## Python 环境配置

推荐在项目根目录或 `agent/` 目录创建虚拟环境：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

安装依赖：

```bash
cd agent
pip install -r requirements.txt
```

如果运行时报缺少模块，可以补装代码中实际使用到的包：

```bash
pip install fastapi uvicorn langchain-openai langchain-milvus langchain-neo4j langchain-text-splitters
```

这些包在当前源码中被导入：

- `app/app_main.py`：`fastapi`, `uvicorn`
- `agent/agents/*.py`：`langchain_openai`
- `agent/tools/vector_tool.py`：`langchain_milvus`
- `agent/tools/graph_tool.py`：`langchain_neo4j`
- `agent/test/milvus_rag.py`、`agent/test/build_kg.py`：`langchain_text_splitters`

## `.env` 配置

项目主要读取 `agent/.env`。不要把真实密钥提交到代码仓库。建议按下面模板配置：

```dotenv
# ====== LLM 配置（必填）======
DASHSCOPE_API_KEY=你的 DashScope API Key
MODEL=qwen-plus
BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# ====== Redis 短期记忆 ======
REDIS_URL=redis://localhost:6379
REDIS_TTL=1800

# ====== Milvus 长期记忆、RAG、语义缓存 ======
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_API_KEY=

# ====== Neo4j 知识图谱 ======
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123
NEO4J_DATABASE=neo4j

# ====== MySQL 当前主要由 docker 提供，业务代码暂未深度使用 ======
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=123456
MYSQL_DATABASE=clinical_cds

# ====== 日志 ======
LOG_LEVEL=INFO
```

## 配置读取位置

`agent/config/settings.py`：

- 使用 `pydantic-settings`。
- 默认读取当前运行目录下的 `.env`。
- 校验 `DASHSCOPE_API_KEY` 非空。
- 提供 `get_settings()` 缓存配置。
- 给 Agent CLI、MemoryManager、Neo4jClient 等模块使用。

`app/app_config/settings.py`：

- 直接定位到项目根目录下的 `agent/.env`。
- 给 API 侧的 `SemanticCache` 使用。

各 Agent 节点和工具：

- 多数文件通过 `dotenv.load_dotenv(agent/.env)` 显式读取。
- `ChatOpenAI` 使用：
  - `DASHSCOPE_API_KEY`
  - `MODEL`
  - `BASE_URL`

## Agent CLI 启动

交互模式：

```bash
cd agent
python main.py
```

单次查询：

```bash
cd agent
python main.py --query "患者近两周情绪低落、失眠、食欲下降"
```

指定用户和会话：

```bash
cd agent
python main.py \
  --user doctor_001 \
  --session outpatient_20260603 \
  --query "患者服用舍曲林和帕罗西汀，最近失眠加重"
```

开启 debug 日志：

```bash
cd agent
python main.py --debug
```

## 后端 API 启动

推荐从 `app/` 目录启动，因为 `app_main.py` 使用了相对导入：

```bash
cd app
python app_main.py
```

默认监听：

```text
http://0.0.0.0:5000
```

前端访问时使用：

```text
http://127.0.0.1:5000/api/chat
```

启动时后端会执行：

1. 构建 LangGraph。
2. 初始化 Redis/Milvus 记忆系统。
3. 初始化语义缓存。
4. 注册 `/api/chat` 路由。

## 前端启动

```bash
cd front/clinical_cds
npm install
npm run dev
```

常用命令：

```bash
npm run type-check
npm run build
npm run preview
```

默认开发地址通常是：

```text
http://localhost:5173
```

前端当前把后端地址写死为：

```ts
fetch('http://127.0.0.1:5000/api/chat', ...)
```

如果后端端口变化，需要修改 `front/clinical_cds/src/App.vue` 中的请求地址。

## 数据导入顺序

如果需要完整 RAG 和知识图谱能力，推荐顺序：

1. 启动 Docker 基础服务。
2. 配置 `agent/.env`。
3. 导入 Markdown 文档到 Milvus：

```bash
cd agent
python test/milvus_rag.py
```

4. 导入知识图谱到 Neo4j：

```bash
cd agent
python test/build_kg.py ../mock_data/icd11_depression.md
```

不传文件时，`build_kg.py` 默认读取 `mock_data/icd11_depression.md`。

5. 可选：预热后端语义缓存：

```bash
cd app
python preload_cache.py
```

## 快速验证

验证 Agent：

```bash
cd agent
python test/clinical_test.py
```

验证后端：

```bash
cd app
python app_main.py
```

然后另开终端用 curl：

```bash
curl -N -X POST http://127.0.0.1:5000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"患者近两周情绪低落、失眠、食欲下降\",\"user_id\":\"doctor_001\",\"session_id\":\"test_session\"}"
```

验证前端：

```bash
cd front/clinical_cds
npm run type-check
npm run build
```
