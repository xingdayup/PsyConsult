# 12 安全与工程化

> 学习目标：AI 应用落地必被问的安全与可靠性话题，本项目都有对应实现可讲。
> 状态：骨架已含全部要点与代码锚点，叙述性文字待补。

## 1. 接口安全（`app/router/chat.py`）

- **Bearer Token**：`API_AUTH_TOKEN` 非空即强制校验，`secrets.compare_digest` 恒定时间比较（防时序侧信道）
- **身份头**：`X-User-Id` 必填 + 正则 `^[A-Za-z0-9_.:-]{1,128}$`——同一正则同时校验 `session_id`
- **为什么正则这么严**：user_id/session_id 会拼进 Redis key 和 Milvus 标量过滤表达式（`filter=f'user_id == "{user_id}"'`），不校验就是注入面
- **输入长度**：query 1-4000 字 + 归一化后 ≥4 非空白字符，太短直接拒绝（省一次图执行）

## 2. 前端安全（`front/clinical_cds/App.vue`）

- 所有 Markdown（用户输入回显 + LLM 输出）经 **DOMPurify** 净化后再交给 marked 渲染——LLM 输出可能被提示注入诱导产出 `<script>`/`onerror`
- 鉴权 token 放 `.env.local`（`VITE_API_AUTH_TOKEN`），不进 git

## 3. 可靠性：三层优雅降级

| 组件挂了 | 系统行为 |
|---------|---------|
| Redis（Checkpoint） | 图无状态运行，多轮失效，单轮正常 |
| Milvus（长期记忆/缓存/RAG） | 记忆与缓存跳过，agent 靠参数知识回答 |
| Neo4j | 图谱工具返回空，agent 在输出中说明依据指南推理 |

设计原则：**记忆与检索是增强（enhancement）不是依赖（dependency）**——任何外围存储故障都不阻塞推理主路径。每个降级路径都有告警日志（`Checkpointer disabled` / `Milvus unavailable`）。

## 4. 可观测性

- 双 logger 命名空间：`clinical_cds.agent` / `clinical_cds.chat`，结构化事件（`event=xxx user_id=... session_id=... elapsed=...`）
- RotatingFileHandler：控制台 + `logs/backend.log`（5MB × 5 备份）
- 每个节点计时（`_timed_node`），SSE 每次发射计时——全链路可定位慢节点

## 5. 工程化清单

- pytest（鉴权 + 日志配置，11 项）+ `compileall` 语法门禁 + 前端 `type-check && build` 门禁
- `AGENTS.md` / `CLAUDE.md` 双指令文件，架构文档与代码同步更新
- 配置对齐：两套 Settings 默认值与 docker-compose 一致（第 11 章的教训固化）

## 6. AI 特有风险（面试加分项）

- **幻觉抑制**：诊断节点强制"逐条对照 ICD-11 + 原文引用 + 未提及明确标 ❌"，不许编症状
- **提示注入面**：检索结果（图谱/向量返回的文本）会进入 LLM 上下文——原型信任 mock_data，生产需要内容过滤
- **免责边界**：输出仅供临床参考——医疗 AI 的监管语境（三类证、人机责任划分）值得了解一句

## 面试官可能追问

1. 为什么用恒定时间比较而不是 `==`？（字符串比较的短路时序可泄露 token 前缀）
2. 优雅降级会不会把故障"藏"起来？（会——所以降级必须配告警；可讨论健康检查端点聚合各组件状态）
3. LLM 输出直接 markdown 渲染还有什么风险？（链接钓鱼/误导内容，DOMPurify 挡 XSS 挡不了语义风险）
