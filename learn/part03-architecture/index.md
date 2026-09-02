# Part 03｜架构地图：先看门诊，再看代码

## 学习目标

先用人话画出医生工作台、接待窗口、专家组和资料室，再把它翻译成真实目录与运行链路。学完能从一份请求讲到三领域流水线，而不是只会背技术名称。

## 生活类比：门诊平面图和施工图

来访者看平面图，只需知道挂号、诊室和资料室在哪里；维修人员还要看水电与管线施工图。软件架构也有两张图：第一张帮助理解职责，第二张帮助定位代码。本篇始终先画第一张。

## 图解

### 先画人话图

```text
医生工作台
    │ 病例
    ▼
接待窗口 ──检查来信、持续回传
    │
    ▼
会话入口 ──找回旧记录，必要时压缩
    │
    ▼
协调员 ──决定从哪位专家开始
    │
    ├─→ 诊断专家 → 治疗专家 → 药物专家
    ├─→ 治疗专家 → 药物专家
    └─→ 药物专家
             │
             └─查询资料室
```

### 再给技术图

```text
front/clinical_cds
    │ POST /api/chat + SSE
    ▼
app/  ── auth / validation / cache / streaming
    │
    ▼
agent/ LangGraph
START → history_compression（仅 Redis Checkpoint 可用时）
      → orchestrator
      → differential_diagnosis → treatment_recommend → drug_interaction → END

资料：Redis Checkpoint · Milvus · Neo4j
```

## 分步骤体验

1. [三层分工](three-layers.md)：先分清谁展示、谁接待、谁推理；
2. [请求流转](request-flow.md)：沿一份病例走完整条路；
3. [目录地图](directory-map.md)：把职责落到文件夹；
4. [设计取舍](design-tradeoffs.md)：理解为什么这样组合，以及付出的代价。

建议每页都先遮住技术图，用自己的话复述人话图。

## 项目真实实现

当前源码的关键事实是：

- Body 只有 `query`、`session_id`；
- `X-User-Id` 始终必填，Bearer 仅在配置 `API_AUTH_TOKEN` 时强制；
- Redis Checkpoint 可用时图入口包含 `history_compression`；
- 领域主线是鉴别诊断 → 治疗推荐 → 药物审查；
- Milvus 使用三个集合：`cloud_product_docs`、`qa_semantic_cache`、`long_term_memory`；
- MCP 有管理器与示例服务，但没有接入当前聊天主图。

这些事实分别可在 [`app/`](../../app/) 与 [`agent/`](../../agent/) 中核对。

## 源码二刷

第一次按目录读，第二次按链路读：

```text
app/router/chat.py
  → app/service/chat_service.py
  → agent/core/workflow/graph_manager.py
  → agent/agents/
  → agent/tools/
```

二刷目标不是记住每行，而是能回答“输入在哪里变形、状态在哪里恢复、下一步在哪里决定、输出在哪里变成流”。

## 面试背板

> 系统按展示、接待、推理三层分工。请求先在接待层完成身份与输入检查，再经过缓存和会话上下文，进入可路由的三领域流水线，执行过程转成 SSE 回传。Redis、Milvus、Neo4j 是支撑能力，不与业务层混为一层；MCP 当前只是预留扩展，并未接入主图。

## 常见问题

**基础设施算第四个业务层吗？** 本教程把它看作三层共同依赖的资料设施，不承担页面、HTTP 或临床流程职责。

**每次都一定走三位专家吗？** 不一定。协调员可从治疗或药审开始，但进入诊断后会继续走后续步骤。

**没有 Redis 还能运行吗？** 可以单轮运行，但不会恢复 Checkpoint 历史，入口也没有历史压缩节点。

## 自测

1. 不看技术图，画出人话图。
2. 把四个生活角色映射到目录或基础设施。
3. 说出三个领域节点的顺序。
4. MCP 当前是否在主链路中？

## 导航

- 上一篇：[Part 02｜第一次跑起来](../part02-quickstart/index.md)
- 下一页：[三层分工](three-layers.md)
- 本篇路线：[三层](three-layers.md) → [请求流](request-flow.md) → [目录](directory-map.md) → [取舍](design-tradeoffs.md)
