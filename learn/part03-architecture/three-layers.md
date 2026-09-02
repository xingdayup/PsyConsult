# 08｜三层分工：工作台、窗口、专家组

## 学习目标

分清三个业务层各自负责什么、绝不该负责什么，并能判断一项修改应该落在哪个目录。

## 生活类比：不要让接待员替专家诊断

门诊中，工作台负责人与信息交互，接待员负责核对来信和安排流转，专家负责专业判断。如果把诊断规则写在接待台上，规则一变就会牵动整个窗口；如果让专家自己画页面，也会失去清晰边界。

## 图解

### 先画人话图

```text
┌─────────────┐
│ 医生工作台   │ 看、写、切换会话
└──────┬──────┘
       ▼
┌─────────────┐
│ 接待窗口     │ 验身份、收材料、回传进度
└──────┬──────┘
       ▼
┌─────────────┐
│ 专家组       │ 路由、诊断、治疗、药审
└──────┬──────┘
       ▼
   共享资料室
```

### 再给技术图

```text
front/clinical_cds/   UI state · POST · SSE reader · safe Markdown
         │
app/                  auth · Pydantic · cache · StreamingResponse
         │
agent/                AgentState · StateGraph · prompts · tools
         │
Redis / Milvus / Neo4j
```

依赖方向是工作台调用接待层，接待层调用推理层；临床推理不要反向塞进页面或路由。

## 分步骤体验

遇到需求时先做归类练习：

1. “按钮禁用和消息展示”属于医生工作台；
2. “缺少 `X-User-Id` 返回 400”属于接待窗口；
3. “诊断后必须进入治疗节点”属于专家组；
4. “会话状态保存在哪里”属于资料设施与推理状态的交界；
5. “缓存命中后仍记录本轮”由接待层协调缓存与专家图状态。

## 项目真实实现

- [`front/clinical_cds/`](../../front/clinical_cds/)：三栏工作台、本地会话消息、请求发送与安全展示；
- [`app/router/chat.py`](../../app/router/chat.py)：`POST /api/chat`、身份规则；
- [`app/service/chat_service.py`](../../app/service/chat_service.py)：语义缓存、长期记忆、图调用与 SSE；
- [`agent/core/workflow/`](../../agent/core/workflow/)：状态、Checkpoint、图组装和历史压缩；
- [`agent/agents/`](../../agent/agents/)：协调者及三个领域角色；
- [`agent/tools/`](../../agent/tools/)：对资料设施的查询工具。

`app/` 通过将 `agent/` 加入导入路径直接调用推理模块，这是当前原型选择，也形成了一定耦合。

## 源码二刷

做一次“职责审查”：

1. 在 [`app/router/chat.py`](../../app/router/chat.py) 找输入与身份检查，确认没有诊断 Prompt；
2. 在 [`agent/agents/`](../../agent/agents/) 找 Prompt 与工具，确认没有 HTTP 状态码；
3. 在 [`front/clinical_cds/src/App.vue`](../../front/clinical_cds/src/App.vue) 找展示逻辑，确认真实诊断规则不应在这里维护。

发现跨界代码时，先描述影响，再决定是否重构。

## 面试背板

> 我把系统拆成 UI、API 编排和 Agent 推理三层。UI 只负责交互与流消费，API 负责不可信输入、鉴权、缓存和传输，Agent 层维护临床流程、状态与工具。基础设施通过明确入口被调用。这样能分别测试和演进，但当前 API 直接导入 agent 模块，仍是原型期耦合点。

## 常见问题

**缓存为什么放在 `app/` 而不是领域 Agent？** 它决定请求是否进入整张图，属于应用级快路径，不是某位专家的临床职责。

**历史压缩属于接待层吗？** 触发节点在 Agent 图入口，因为它修改图的消息状态；接待层只提供 Checkpoint 条件。

**前端能不能直接连模型？** 不应这样做，会暴露密钥并绕过服务端校验、审计和流程控制。

## 自测

1. 身份校验、治疗 Prompt、Markdown 展示分别在哪一层？
2. 为什么不能在路由里写临床推理？
3. 当前三层之间有什么原型期耦合？

## 导航

- 上一页：[Part 03 入口](index.md)
- 下一页：[一份请求如何流转](request-flow.md)
- 相关目录：[`app/`](../../app/) · [`agent/`](../../agent/) · [`front/`](../../front/)
