# 测试、验证与排错

## 测试类型

当前项目主要是脚本式测试和验证脚本，而不是完整 pytest 测试套件。

主要脚本：

```text
agent/test/clinical_test.py     # 端到端 Agent 链路测试
agent/test/milvus_rag.py        # Milvus 文档导入和检索脚本
agent/test/build_kg.py          # Markdown -> 知识图谱 -> Neo4j
app/preload_cache.py            # API 语义缓存预热
```

前端验证命令：

```text
npm run type-check
npm run build
```

## 后端基础服务检查

启动：

```bash
cd docker
docker compose up -d
```

查看：

```bash
docker compose ps
```

预期服务：

- `clinical_redis`
- `clinical_milvus`
- `clinical_neo4j`
- `clinical_mysql`

端口：

- Redis：6379
- Milvus：19530、9091
- Neo4j HTTP：7474
- Neo4j Bolt：7687
- MySQL：3306

## Agent 链路测试

运行：

```bash
cd agent
python test/clinical_test.py
```

该脚本会：

1. 构建 `AgentGraphManager`。
2. 初始化一条测试 `AgentState`。
3. 输入典型抑郁发作病例。
4. 调用 `graph.ainvoke(state)`。
5. 打印 CDS 输出和消息数量。

如果成功，说明：

- `.env` 至少能被读取。
- LLM 能调用。
- LangGraph 能构建。
- Agent 节点能执行。

如果失败，优先检查：

- `DASHSCOPE_API_KEY`
- `MODEL`
- `BASE_URL`
- Python 依赖
- Redis/Milvus/Neo4j 是否启动

## Milvus RAG 验证

运行：

```bash
cd agent
python test/milvus_rag.py
```

预期行为：

- 连接 Milvus。
- 加载 `mock_data/` 下 Markdown。
- 切分成 chunk。
- 调用 embedding。
- 写入 `cloud_product_docs`。

常见失败：

### `DASHSCOPE_API_KEY` 不存在

检查 `agent/.env`：

```dotenv
DASHSCOPE_API_KEY=你的 Key
```

### Milvus 连接失败

检查：

```bash
cd docker
docker compose ps
```

确认 `clinical_milvus` 已启动，端口 `19530` 可用。

### pymilvus 兼容性问题

`agent/tools/vector_tool.py` 和 `agent/test/milvus_rag.py` 都包含了对 `pymilvus 2.6.x` 与 `langchain-milvus 0.3.x` 连接处理的兼容 patch。如果相关包版本变化，仍可能出现连接异常。

## Neo4j 图谱验证

导入：

```bash
cd agent
python test/build_kg.py ../mock_data/icd11_depression.md
```

访问 Neo4j Browser：

```text
http://localhost:7474
```

登录：

```text
neo4j / password123
```

验证查询：

```cypher
MATCH (n) RETURN labels(n), n LIMIT 25;
```

如果没有节点：

- 检查导入脚本是否成功结束。
- 检查 `.env` 中 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`。
- 检查 Docker 中 Neo4j 密码是否和 `.env` 一致。

## API 验证

启动后端：

```bash
cd app
python app_main.py
```

另开终端测试：

```bash
curl -N -X POST http://127.0.0.1:5000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"PHQ-9 评分怎么分级？\",\"user_id\":\"doctor_001\",\"session_id\":\"api_test\"}"
```

如果先运行过：

```bash
cd app
python preload_cache.py
```

则 `PHQ-9 评分怎么分级？` 这类问题应该更容易命中语义缓存。

## 前端验证

安装依赖：

```bash
cd front/clinical_cds
npm install
```

类型检查：

```bash
npm run type-check
```

构建：

```bash
npm run build
```

开发启动：

```bash
npm run dev
```

浏览器访问：

```text
http://localhost:5173
```

## 常见排错

### 中文显示乱码

源码是 UTF-8。Windows PowerShell 读取中文文件时建议显式指定：

```powershell
Get-Content -LiteralPath .\app\app_main.py -Encoding UTF8
```

如果终端输出仍异常，可设置：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

### `ModuleNotFoundError`

先安装主依赖：

```bash
cd agent
pip install -r requirements.txt
```

如仍缺少模块，根据报错补装，例如：

```bash
pip install fastapi uvicorn langchain-openai langchain-milvus langchain-neo4j langchain-text-splitters
```

### 后端启动时找不到 `router` 或 `service`

从 `app/` 目录启动：

```bash
cd app
python app_main.py
```

### 后端启动很慢

原因可能是：

- 初始化 Agent 图。
- 连接 Redis、Milvus。
- 初始化 embedding。
- 首次创建 Milvus Collection。

观察控制台日志即可。

### 前端显示请求失败

检查：

- 后端是否启动。
- 后端是否监听 `5000`。
- `App.vue` 中后端地址是否正确。
- 浏览器控制台是否有 CORS 或网络错误。

### Agent 输出不符合预期

检查：

- mock 数据是否已经导入 Milvus。
- 知识图谱是否已经导入 Neo4j。
- query 是否足够明确。
- Router 是否进入了预期节点。
- 工具是否返回了空结果。

### Neo4j 密码不一致

Docker Compose 中：

```text
NEO4J_AUTH=neo4j/password123
```

`.env` 应配置：

```dotenv
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123
```

### Milvus 文档集合名看起来不对

当前集合名是：

```text
cloud_product_docs
```

这是旧命名遗留，但代码里 Agent RAG 工具和导入脚本都使用这个名称。只要两边一致，功能可以正常运行。

### 语义缓存和 RAG 混淆

二者都使用 Milvus，但 Collection 不同：

- `qa_semantic_cache`：后端 API 高频问答缓存。
- `cloud_product_docs`：Agent RAG 文档检索。
- `long_term_memory`：用户长期记忆。

## 建议的最小验证顺序

1. `docker compose up -d`
2. `python test/milvus_rag.py`
3. `python test/build_kg.py ../mock_data/icd11_depression.md`
4. `python test/clinical_test.py`
5. `python app_main.py`
6. `curl -N -X POST http://127.0.0.1:5000/api/chat ...`
7. `npm run type-check`
8. `npm run build`
9. `npm run dev`

## 学习时建议重点看哪些文件

先看：

```text
agent/main.py
agent/core/workflow/graph_manager.py
agent/agents/orchestrator.py
agent/agents/symptom_agent.py
app/service/chat_service.py
front/clinical_cds/src/App.vue
```

再看：

```text
agent/tools/vector_tool.py
agent/tools/graph_tool.py
agent/core/memory/memory_manager.py
app/infra/cache.py
agent/test/milvus_rag.py
agent/test/build_kg.py
```

这样能最快理解从前端输入到 Agent 推理再到知识检索的完整链路。
