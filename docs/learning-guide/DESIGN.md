# 学习文档设计方案

## 定位

`docs/learning-guide/` 定位为**开发者学习资源**，以**核心代码走读**和**核心 Prompt 全览**为中心，帮助新成员快速深入理解系统机理。

与 `docs/interview-guide/` 的关系：**互补，非替代**。
- interview-guide：面向面试场景，侧重 Q&A 和口语化讲解
- learning-guide：面向学习场景，侧重代码级深度分析和 Prompt 设计原理

## 文档结构

```
docs/learning-guide/
  DESIGN.md                       - 本文件：设计方案
  README.md                       - 学习路径导航
  01-architecture-deep-dive.md    - 架构深度解析（含关键代码片段）
  02-core-prompts-compendium.md   - 全量 Prompt 汇编与设计分析
  03-agent-workflow-code.md       - Agent 工作流代码走读
  04-memory-cache-system.md       - 记忆系统与语义缓存详解
  05-knowledge-tools.md           - 知识图谱、向量库与工具链
  06-sse-streaming-frontend.md    - SSE 流式交互与前端架构
  07-deployment-config.md         - 部署、配置与环境变量参考
```

## 推荐阅读顺序

1. **速览** → README.md
2. **主线** → 01 → 03 → 02（理解架构 → 理解 Agent 工作流 → 理解 Prompt 设计）
3. **子系统** → 04 → 05（记忆缓存 → 知识工具）
4. **交互层** → 06（SSE 流式 + 前端）
5. **运维** → 07（部署配置参考）

## 各章来源文件

| 章节 | 主要来源文件 |
|------|------------|
| 01-架构 | `CLAUDE.md`, `agent/core/workflow/graph_manager.py`, `agent/core/workflow/state.py`, `app/app_main.py` |
| 02-Prompt | `agent/agents/*.py`, `agent/core/memory/preference_extractor.py`, `agent/tools/graph_tool.py`, `agent/core/graph/parser.py`, `agent/test/build_kg.py` |
| 03-工作流 | `agent/core/workflow/graph_manager.py`, `agent/agents/*.py`, `agent/main.py` |
| 04-记忆 | `agent/core/memory/*.py`, `app/infra/cache.py`, `app/service/chat_service.py` |
| 05-工具 | `agent/tools/*.py`, `agent/core/graph/*.py`, `agent/core/mcp/*.py`, `agent/mcp_servers/clinical_tools.py` |
| 06-流式 | `app/service/chat_service.py`, `app/router/chat.py`, `front/clinical_cds/src/App.vue` |
| 07-部署 | `agent/config/settings.py`, `app/app_config/settings.py`, `docker/docker-compose.yml`, `front/clinical_cds/vite.config.ts` |

## 编写原则

1. **代码引用精确到行号**，需与源文件验证
2. **Prompt 逐字收录**，不摘要、不删减
3. **代码块使用正确的语言标注**（python/bash/typescript/json）
4. **用注释解释代码**，而非用文字描述代码
5. **章节间交叉引用**，但避免冗余重复

## 验证清单

- [ ] 每章引用的代码路径和行号与实际文件一致
- [ ] 每章引用的 Prompt 原文与源文件逐字一致
- [ ] 所有代码块语法高亮正确
- [ ] README 阅读时间估算合理
- [ ] 章节间链接有效
