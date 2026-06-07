# Clinical CDS 面试学习文档

这套文档用于面试前复习 Clinical CDS 项目。它不是运行手册，而是帮助你用技术面试语言讲清：项目解决什么问题、架构怎么设计、关键代码在哪里、Prompt 怎么写、线上部署和故障怎么处理。

## 项目一句话

PsyConsult 是一个面向精神科初诊和用药审查场景的临床决策支持原型，医生输入症状、病程或治疗方案后，系统通过 LangGraph 多 Agent、RAG、知识图谱和会话记忆，流式输出症状抽取、ICD-11 鉴别诊断、治疗建议和药物相互作用审查结果。

## 建议阅读路线

1. [项目架构](./01-project-architecture.md)：先讲清整体链路。
2. [Agent 工作流](./02-agent-workflow.md)：说明为什么拆成多个 Agent。
3. [Prompt 与工具](./03-prompts-and-tools.md)：展示你如何约束 LLM。
4. [流式后端](./04-streaming-and-backend.md)：讲清 SSE、首字节、耗时日志。
5. [数据、记忆与 RAG](./05-data-memory-rag.md)：说明 Redis、Milvus、Neo4j 各自价值。
6. [前端与安全](./06-frontend-and-security.md)：讲 Vue、会话缓存、XSS 和 API 配置。
7. [部署与运维](./07-deployment-and-ops.md)：解释 Pages、Tunnel、CORS 和线上排障。
8. [面试 Q&A](./08-interview-qna.md)：直接背诵或按需改写。
9. [截图清单](./09-screenshot-checklist.md)：准备面试展示材料。

## 3 分钟项目讲解顺序

1. **业务痛点**：精神科问诊信息非结构化，医生需要同时做症状标准化、鉴别诊断、治疗路径和药物风险判断。
2. **系统架构**：前端 Vue 负责会话和流式展示，FastAPI 提供 SSE 接口，LangGraph 编排多个临床 Agent，Redis/Milvus/Neo4j 支撑记忆、RAG 和知识图谱。
3. **核心创新**：不是直接让 LLM 回答，而是把任务拆成临床流程，配合工具调用和 Prompt 约束，让输出更结构化、可追踪。
4. **工程实现**：后端首条 SSE 立即返回状态，Agent 内部通过 `get_stream_writer()` 推送节点状态、工具状态和内容 chunk，前端逐块解析并展示阶段提示。
5. **部署经验**：前端部署到 Cloudflare Pages，后端通过 Cloudflare Tunnel 或固定 API 地址暴露，重点处理 CORS、API 地址注入和线上流式调试。

## 面试官可能关注的能力点

- Agent 编排：LangGraph 状态、条件路由、节点串联。
- Prompt 工程：任务、工具、输出格式、约束四件套。
- RAG/图谱：什么时候用向量检索，什么时候用结构化图谱。
- 工程化：SSE、首字节、日志、CORS、安全边界、部署排障。
- 产品理解：医生需要辅助决策、流程透明、不能黑盒回答。

