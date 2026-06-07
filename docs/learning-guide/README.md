# 临床CDS 学习指南

> 面向开发者的系统学习资源，以**核心代码走读**和**核心 Prompt 全览**为中心。

## 如何使用本指南

**推荐阅读路径：**

```
第1章 架构 → 第3章 工作流 → 第2章 Prompt
    ↓
第4章 记忆 → 第5章 工具
    ↓
第6章 流式前端
    ↓
第7章 部署配置
```

**按需跳读：**
- 只想看 Prompt → 第2章（全量 8 个 Prompt 逐字收录）
- 只想理解 Agent 怎么串起来 → 第3章
- 只想了解记忆/缓存怎么工作 → 第4章
- 想部署或排查问题 → 第7章

## 各章简介

| 章节 | 内容 | 预计阅读 |
|------|------|---------|
| [01-架构深度解析](./01-architecture-deep-dive.md) | 五层架构图、AgentState、StateGraph 拓扑、双 Settings 对比、sys.path 注入、启动链路、8 项架构决策 | 30 分钟 |
| [02-全量 Prompt 汇编](./02-core-prompts-compendium.md) | 全部 8 个 Prompt 逐字收录 + 设计分析（Orchestrator/Diagnosis/Treatment/DrugReview/PreferenceExtractor/Cypher/KGParser/build_kg） | 40 分钟 |
| [03-Agent 工作流代码走读](./03-agent-workflow-code.md) | Orchestrator 路由、ReAct Agent 通用模式、6 种流式事件、_timed_node 包装器、CLI 交互模式 | 35 分钟 |
| [04-记忆系统与语义缓存](./04-memory-cache-system.md) | MemoryManager、短期 Redis（Key/TTL/裁剪）、长期 Milvus（Schema/嵌入/去重）、PreferenceExtractor、语义缓存（L1_EXACT+L1_SEMANTIC） | 35 分钟 |
| [05-知识图谱与工具链](./05-knowledge-tools.md) | Neo4j Schema（5 节点+6 关系）、graph_tool 双模式、synonym_tool、vector_tool（含 pymilvus 补丁）、MCP 工具系统 | 30 分钟 |
| [06-SSE 流式交互与前端](./06-sse-streaming-frontend.md) | 后端 SSE 实现（10 种事件）、前端 ReadableStream 消费、状态映射、认证链路、会话管理、Markdown 渲染、API URL 降级 | 30 分钟 |
| [07-部署配置参考](./07-deployment-config.md) | 20+ 环境变量字典、双 Settings 对比、Docker Compose、前端构建、pytest、启动检查清单、日志配置 | 20 分钟 |

## 与 interview-guide 的关系

本指南与 `docs/interview-guide/` **互补而非替代**：

| 维度 | learning-guide | interview-guide |
|------|---------------|-----------------|
| 目标读者 | 新加入的开发者 | 面试官 / 项目讲解 |
| 侧重点 | 代码怎么写的、Prompt 为什么这样设计 | 项目做了什么、技术亮点在哪 |
| Prompt 覆盖 | 全部 8 个逐字收录 + 行号 | 精选片段 |
| 代码片段 | 完整方法级代码 + 逐行注解 | 关键片段 |
| 问答 | 无 | 16 个常见面试问答 |

## 前置知识

阅读本指南前，建议了解：

- **Python async/await**：理解 `async for`、`asyncio.gather`、`asyncio.create_task` 等异步模式
- **LangGraph 基础**：StateGraph、节点、条件边、`astream` 流式模式等概念
- **Vue 3 Composition API**：`ref`、`computed`、`<script setup>` 语法（第 6 章）
- **LangChain 基础**：`ChatOpenAI`、`@tool` 装饰器、`create_react_agent` 等
- **基础医学知识**：PHQ-9、GAD-7、ICD-11、SSRI 等术语（非必需，但对理解 Prompt 有帮助）

## 代码引用约定

- 所有代码引用格式：`agent/agents/orchestrator.py:47-64`
- 所有 Prompt 均为源文件**逐字引用**，未做改写
- 所有行号基于文档编写时的代码版本，后续可能偏移

## 文件索引

```
docs/learning-guide/
  README.md                       ← 本文件
  DESIGN.md                       ← 设计方案（编写时的规划文档）
  01-architecture-deep-dive.md    ← 推荐起点
  02-core-prompts-compendium.md   ← Prompt 大全
  03-agent-workflow-code.md       ← Agent 代码走读
  04-memory-cache-system.md       ← 记忆与缓存
  05-knowledge-tools.md           ← 知识工具
  06-sse-streaming-frontend.md    ← 流式与前端
  07-deployment-config.md         ← 部署参考
```
