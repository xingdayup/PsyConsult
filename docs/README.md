# Clinical CDS 学习文档

本目录是 `clinical_cds` 项目的学习文档入口。项目是一个精神科临床决策支持原型，包含：

- `agent/`：基于 LangGraph 的多智能体推理系统。
- `app/`：FastAPI 后端接口层，负责接收前端请求、初始化 Agent、提供 SSE 流式响应。
- `front/clinical_cds/`：Vue 3 + Vite + TypeScript 前端。
- `docker/`：Redis、Milvus、Neo4j、MySQL 本地基础服务。
- `mock_data/`：临床指南、ICD-11 诊断标准、药物资料等示例数据。

## 推荐阅读顺序

1. [项目总览与架构](./01-project-overview.md)
2. [环境配置与启动](./02-environment-configuration.md)
3. [Agent 多智能体系统](./03-agent-system.md)
4. [后端 FastAPI 服务](./04-backend-api.md)
5. [前端 Vue 应用](./05-frontend.md)
6. [数据、图谱与向量检索](./06-data-and-ingestion.md)
7. [测试、验证与排错](./07-testing-and-troubleshooting.md)

## 一句话运行流程

先启动基础服务，再配置 `agent/.env`，然后启动后端和前端：

```bash
cd docker
docker compose up -d

cd ../agent
pip install -r requirements.txt

cd ../app
python app_main.py

cd ../front/clinical_cds
npm install
npm run dev
```

后端默认监听 `http://127.0.0.1:5000`，前端由 Vite 默认监听 `http://localhost:5173`。

## 当前项目的核心链路

前端发送病例描述到后端 `/api/chat`，后端先查询 Milvus 语义缓存。如果缓存命中，直接返回缓存答案；如果未命中，则进入 LangGraph 多 Agent 工作流：

```text
Vue 前端
  -> FastAPI /api/chat
  -> 语义缓存 Milvus Collection: qa_semantic_cache
  -> LangGraph Agent 图
  -> Redis 短期记忆 + Milvus 长期记忆
  -> Neo4j 知识图谱 + Milvus 文档 RAG + 本地症状同义词
  -> SSE 流式响应返回前端
```

## 安全提醒

`agent/.env` 中会包含模型 API Key、数据库密码等敏感信息。不要提交真实密钥、真实患者资料或可识别个人身份的信息。文档中的 `.env` 示例全部使用占位符。

## 新版使用指南

- [Clinical CDS 使用指南](./08-usage-guide.md)
