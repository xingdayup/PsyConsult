# 15 简历口径

> 原则：每一句都能被代码证实。以下是 2026-08-23 校对过的准确版本（此前版本中"Text2Cypher 为主""余弦相似度排序""工具调用上下文入 checkpoint"均已修正）。

## 项目条目（推荐版）

**PsyConsult —— 精神科临床决策支持系统（个人项目）**

技术栈：LangGraph / LangChain / FastAPI / Vue 3 / Redis / Milvus / Neo4j / DashScope

- **临床推理工作流**：基于 LangGraph 编排鉴别诊断、治疗推荐、药物审查 3 个临床节点与 1 个意图路由节点，通过共享状态传递病例信息与各节点推理结论；节点内 ReAct Agent 按需调用 Neo4j 图谱与 Milvus 向量检索工具，SSE 流式逐节点推送。
- **知识构建与质量约束**：LLM 结构化抽取 + MERGE 幂等写入构建知识图谱（16 种药物、27 对相互作用）；诊断输出逐条对照 ICD-11 核心标准，带原文引用并区分"已有证据/未提及"。
- **双引擎知识检索**：Neo4j 以关键词图检索为主、可选启用 LLM Text2Cypher 生成查询并自动回退；Milvus 向量检索 ICD-11 与精神科指南（DashScope text-embedding-v2 嵌入）；另设两级语义缓存（精确 + 相似），推理结果自填充，重复问题 0.27s 命中（全流程约 60s）。
- **Agent 记忆与状态管理**：LangGraph Checkpoint + Redis 管理会话级状态（thread_id 隔离、TTL 续期、无 Redis 优雅降级）；超阈值自动"保留近期窗口 + LLM 历史摘要"压缩上下文；每 5 轮后台提取患者临床要点入 Milvus 长期记忆，支持跨会话语义召回。
- **工程化**：主导记忆体系 v1→v2 重构（自研 Redis 短期记忆 → Checkpoint，净删 500+ 行）；全链路实测验证（多轮指代、缓存命中、压缩保真、临床要点提取）；Bearer 鉴权 + DOMPurify 前端净化 + 输入校验。

## 精简版（简历空间紧张时，三行）

- LangGraph 多智能体临床决策支持系统：路由 + 诊断/治疗/药审流水线，ReAct 节点按需调 Neo4j 图谱与 Milvus 向量工具，SSE 流式输出
- LangGraph Checkpoint + Redis 会话状态 + 历史摘要压缩 + Milvus 长期临床记忆 + 语义缓存（重复问题 0.27s 命中）
- 主导记忆体系重构（自研方案 → Checkpoint，净删 500+ 行），全链路实测验证

## 口径红线（说过=翻车）

| 不要说 | 实际情况 |
|--------|---------|
| "Text2Cypher 自动生成查询，关键词兜底" | 默认关键词检索，Text2Cypher 是开关可选项 |
| "向量检索按余弦相似度排序"（指 RAG 集合） | RAG 集合未显式设置，langchain-milvus 默认 L2；显式 COSINE 的是记忆/缓存集合 |
| "checkpoint 保存工具调用上下文" | 工具轨迹不进共享状态，只有节点最终结论 |
| "12 种药物" | 16 种 Drug、27 条 INTERACTS_WITH |
| "长期偏好每 5 轮异步提取"（v1 简历常见写法） | v1 此链路实际断裂；v2（当前）才是真的 |

## 面试现场对齐技巧

被追问细节时主动给出精确锚点："这个逻辑在 `graph_manager.py` 的 `_compress_history`，阈值 16 保留 8"——具体到文件和数字的可信度，远高于形容词堆砌。
