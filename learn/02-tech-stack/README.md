# 02 技术栈地图

> 学习目标：每个选型都能回答"解决什么问题、替代方案是什么、为什么选它"——这是 AI 应用工程师面试的基本功。

## 选型总表

| 技术 | 在本项目中的角色 | 替代方案 | 选择理由 |
|------|----------------|---------|---------|
| **LangGraph** | 多 Agent 编排、状态图、Checkpoint | AutoGen / CrewAI / 自研循环 | 显式状态图 + 原生 checkpoint + 流式支持，对"流程确定的临床流水线"最合适 |
| **LangChain** | LLM 抽象、工具协议、Embeddings | 直接调 SDK | `create_react_agent`、`with_structured_output`、统一消息模型 |
| **FastAPI** | HTTP + SSE 流式接口 | Flask / Django | 原生 async、StreamingResponse、依赖注入做鉴权 |
| **Vue 3 + Vite** | 前端 SPA | React | —（个人熟悉度） |
| **Redis (redis-stack)** | Checkpointer 存储 | Postgres / SQLite saver | 已有 Redis；注意**必须 redis-stack**（依赖 RediSearch，见第 11 章坑 2） |
| **Milvus** | 向量库：长期记忆 + 语义缓存 + RAG | Qdrant / FAISS / pgvector | 国内生态、本地 docker 一键起 |
| **Neo4j** | 知识图谱：疾病-症状-药物关系 | — | 关系型查询（药物相互作用）天然是图问题 |
| **DashScope (qwen-plus)** | LLM + text-embedding-v2 嵌入 | OpenAI / DeepSeek | OpenAI 兼容模式接入 LangChain，成本可控 |

## 两个容易讲不清楚的点

### 为什么是 LangGraph 而不是"一个 Agent + 一堆工具"？

临床流程是**半确定的**：症状描述必走"诊断→治疗→药审"流水线，但入口由意图决定。LangGraph 的 StateGraph 正好表达这种"条件入口 + 固定流水线"结构，每个节点内部再用 ReAct agent 处理不确定性（调哪个工具、调几次）。纯 ReAct 大 Agent 的问题是：流水线顺序不可控、中间结果没有结构化落点、无法逐节点流式推送。

### 为什么 Redis 做 Checkpoint、Milvus 做记忆？

访问模式不同：
- Checkpoint 是**按 key 的整存整取**（thread_id → 完整 state），要低延迟、可过期 → Redis
- 长期记忆是**按语义的相似检索**（患者背景 vs 当前问题），要向量索引 → Milvus
- 语义缓存同理是相似检索（问过的相似问题）→ Milvus，还能和 RAG 共用嵌入服务

## 依赖版本关键项（`agent/requirements.txt`）

```
langchain >= 1.2.0          langgraph >= 1.1.0
langgraph-checkpoint-redis >= 0.5.0   ← Checkpoint 存储，2026-08 引入
pymilvus >= 2.4.0           neo4j >= 5.20.0
```

## 面试官可能追问

1. LangGraph 的 checkpoint 和你自己往 Redis 存消息有什么区别？（→ 第 05/09 章核心考点）
2. 如果 QPS 上去了，哪些组件先成为瓶颈？（Milvus 嵌入调用是串行前置 → 可异步/缓存；LLM 本身）
3. 为什么不用 pgvector 一个库统一向量+关系？（合理追问，答：可以，原型期选择独立组件换取各自生态的工具链）
