# learn-PsyConsult —— 精神科临床决策支持系统 学习文档

> 一个 AI 应用工程师对自己项目的完整复盘：从架构决策到全链路实测，从踩坑实录到面试冲刺。
> 项目本体：[PsyConsult](../) —— LangGraph 多智能体 + FastAPI + Vue 3，支持多轮临床问答。

## 项目一句话

医生输入病例描述 → 系统经语义缓存 / 多智能体推理（鉴别诊断 → 治疗推荐 → 药物审查）→ SSE 流式返回诊疗建议；会话状态由 LangGraph Checkpoint + Redis 管理，长期临床要点存 Milvus。

## 学习路线图

```
 Phase 1 基础概念        Phase 2 架构与核心实现       Phase 3 实战与验证
 ┌─────────────┐      ┌─────────────────────┐      ┌─────────────────┐
 │ 01 项目总览  │      │ 04 StateGraph 编排   │      │ 10 全链路实测    │
 │ 02 技术栈地图│  →   │ 05 会话状态管理      │  →   │ 11 踩坑实录     │
 └─────────────┘      │ 06 上下文工程        │      │ 12 安全与工程化  │
                      │ 07 双引擎检索        │      └─────────────────┘
 Phase 4 面试冲刺      │ 08 长期记忆          │              │
 ┌─────────────┐      │ 09 架构演进复盘      │              ▼
 │ 13 项目自述  │ ←───────────────────────────── Phase 4
 │ 14 深挖 Q&A  │      └─────────────────────┘
 │ 15 简历口径  │
 └─────────────┘
```

## 目录

| 章节 | 内容 | 预计时长 |
|------|------|---------|
| [01 项目总览](./01-project-overview/) | 场景、能力边界、系统架构鸟瞰 | 0.5h |
| [02 技术栈地图](./02-tech-stack/) | 每个技术选型解决什么问题、为什么是它 | 1h |
| [03 请求的一生](./03-request-lifecycle/) | 从前端输入到 SSE 输出的全链路时序 | 1.5h |
| [04 StateGraph 编排](./04-state-graph/) | 节点、条件路由、AgentState 与 add_messages reducer | 1.5h |
| [05 会话状态管理](./05-session-state/) | Checkpointer + Redis：thread_id、TTL、优雅降级 | 1.5h |
| [06 上下文工程](./06-context-engineering/) | 短期窗口 + 历史摘要压缩节点 | 1.5h |
| [07 双引擎检索](./07-dual-retrieval/) | Neo4j 图谱检索 + Milvus 向量检索 + 语义缓存 | 2h |
| [08 长期记忆](./08-long-term-memory/) | LLM 临床要点提取、向量去重、周期触发 | 1h |
| [09 架构演进复盘](./09-architecture-evolution/) | v1 自研短期记忆 → v2 Checkpoint 的重构决策 | 1.5h |
| [10 全链路实测](./10-e2e-verification/) | 多轮对话/缓存/压缩的真实日志与数据 | 1h |
| [11 踩坑实录](./11-pitfalls/) | 9 个真实 bug 的定位与修复过程 | 1.5h |
| [12 安全与工程化](./12-security-engineering/) | 鉴权、净化、优雅降级、配置对齐 | 1h |
| [13 项目自述](./13-interview-self-intro/) | STAR：60 秒版 / 3 分钟版 | 0.5h |
| [14 深挖 Q&A](./14-interview-qa/) | 面试官视角的高频追问与参考答案 | 2h |
| [15 简历口径](./15-resume/) | 严格对齐代码实现的项目描述 | 0.5h |

## 快速开始

```bash
git clone https://github.com/xingdayup/PsyConsult.git
cd PsyConsult

# 1. 基础服务（redis-stack 自带 RediSearch，Checkpoint 依赖它）
cd docker && docker compose up -d && cd ..

# 2. 密钥：agent/.env 写入 DASHSCOPE_API_KEY=sk-xxx（最小配置仅此一项）

# 3. 后端 http://127.0.0.1:5000
python -m venv .venv && .venv/Scripts/pip install -r agent/requirements.txt
.venv/Scripts/python -m uvicorn app.app_main:app --host 127.0.0.1 --port 5000

# 4. 前端 http://localhost:5173
cd front/clinical_cds && npm install && npm run dev
```

## 目录结构

```
learn/
├── README.md                       # 本文件
├── 01-project-overview/            # Phase 1：基础概念
├── 02-tech-stack/
├── 03-request-lifecycle/           # Phase 2：架构与核心实现
├── 04-state-graph/
├── 05-session-state/
├── 06-context-engineering/
├── 07-dual-retrieval/
├── 08-long-term-memory/
├── 09-architecture-evolution/
├── 10-e2e-verification/            # Phase 3：实战与验证
├── 11-pitfalls/
├── 12-security-engineering/
├── 13-interview-self-intro/        # Phase 4：面试冲刺
├── 14-interview-qa/
└── 15-resume/
```

## 与 docs/ 的关系

仓库根部的 `docs/01-08` 是 v1 架构时期的学习文档，其中记忆体系相关内容已过时（v1 自研短期记忆已被 LangGraph Checkpoint 取代）。本目录基于 v2 架构（2026-08 重构并全链路实测）撰写，冲突处以本目录为准。

## License

MIT
