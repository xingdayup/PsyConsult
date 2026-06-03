# 07 - 环境搭建指南

## 你需要什么

| 软件 | 干什么 | 怎么装 |
|------|--------|--------|
| Docker Desktop | 一键运行 Redis/Milvus/Neo4j/MySQL | docker.com 下载 |
| Python 3.10+ | 运行 Agent 和 API | python.org 下载 |
| Node.js 20+ | 运行前端 | nodejs.org 下载 |
| DashScope API Key | 调用大模型 | dashscope.console.aliyun.com 免费注册 |

Docker、Python、Node.js 的安装方法见 cloud_agent 文档 `10-Setup-and-Deployment.md` 的详细步骤。下面假设你已经装好了。

## 第一步：启动基础设施

```bash
cd clinical_cds
docker compose -f docker/docker-compose.yml up -d
```

等 30 秒，四个容器就绪：

```bash
docker ps
# 应该看到 clinical_redis, clinical_milvus, clinical_neo4j, clinical_mysql
```

验证 Neo4j（带 APOC 插件）：
```bash
# 浏览器打开 http://localhost:7474
# 用户名 neo4j，密码 password123
```

## 第二步：配置 .env

在 `agent/` 目录下新建 `.env` 文件：

```ini
DASHSCOPE_API_KEY=sk-你的key
MODEL=qwen-plus
BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

REDIS_URL=redis://localhost:6379
REDIS_TTL=1800

MILVUS_HOST=localhost
MILVUS_PORT=19530

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=123456
MYSQL_DATABASE=clinical_cds

LOG_LEVEL=INFO
```

> Windows 下创建 `.env`：记事本 → 另存为 → 文件名填 `".env"`（带引号）→ 保存类型选"所有文件"

## 第三步：安装 Python 依赖

```bash
cd agent
pip install -r requirements.txt
```

## 第四步：构建知识库

### 4a. 构建知识图谱（导入 Neo4j）

```bash
cd agent
python test/build_kg.py ../mock_data/icd11_depression.md
python test/build_kg.py ../mock_data/psychiatric_drugs.md
python test/build_kg.py ../mock_data/china_guidelines.md
python test/build_kg.py ../mock_data/icd11_schizophrenia.md
```

> 提示：`build_kg.py` 的默认文件是 `icd11_depression.md`，也可以通过命令行参数指定其他文件

验证：浏览器打开 `http://localhost:7474`，执行：
```cypher
MATCH (n) RETURN labels(n)[0] AS 类型, count(n) AS 数量
```
应该看到 Disease、Symptom、Drug 等类型的节点和计数。

### 4b. 构建向量索引（导入 Milvus）

编辑 `test/milvus_rag.py`，在 `main()` 函数里取消注释摄入那两行：

```python
def main():
    manager = MilvusRAGManager()
    # 取消下面两行的注释：
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    manager.ingest_documents(os.path.join(BASE_DIR, "mock_data"))
    # manager.query(...)  # 给这行加注释
```

运行：
```bash
cd agent
python test/milvus_rag.py
```

等待 1-2 分钟（需要调用嵌入模型处理所有文档）。

## 第五步：启动服务

开三个命令行窗口：

**窗口 1 — API 服务器**：
```bash
cd clinical_cds/app
uvicorn app_main:app --port 5000
```

看到 `Uvicorn running on http://0.0.0.0:5000` 表示成功。

**窗口 2 — 前端**：
```bash
cd clinical_cds/front/clinical_cds
npm install
npm run dev
```

看到 `Local: http://localhost:5173/` 表示成功。

**窗口 3 — CLI 测试（可选）**：
```bash
cd clinical_cds/agent
python main.py -q "舍曲林和帕罗西汀能联用吗？"
```

## 第六步：验证

浏览器打开 `http://localhost:5173`，点击场景卡片 "😔 抑郁筛查"，或手动输入：

> 患者近两周情绪低落、失眠、食欲下降，以前喜欢打篮球现在没兴趣了

预期看到完整的 4 步推理链流式输出：症状清单 → ICD-11 逐条对照 → 治疗建议 → 药物审查。

## 故障排查

| 症状 | 检查 |
|------|------|
| Agent 启动 Redis 报错 | `docker ps` 确认 clinical_redis 在运行 |
| 向量检索返回空 | 确认跑了第四步的 milvus_rag.py |
| 图谱查询失败 | 确认 Neo4j 在 https://localhost:7474 可登录 + 导入了数据 |
| 前端连不上后端 | 确认 API 在 5000 端口运行，CORS 已开启 |
| API 返回 500 | 检查 `.env` 中的 `DASHSCOPE_API_KEY` 是否有效 |
| `ModuleNotFoundError` | 在项目根目录的 `.venv` 虚拟环境中运行，或 `pip install -r requirements.txt` |
