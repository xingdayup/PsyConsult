# 03｜面试价值：从“调过模型”讲到“设计过系统”

## 学习目标

把项目讲成一个有问题、有设计、有取舍、有边界的工程故事，而不是罗列技术名词。

## 生活类比：介绍餐厅，不要只报厨具品牌

如果面试官问“你做了什么餐厅”，只回答烤箱、冰箱和收银机品牌，听不出你的设计能力。更好的讲法是：服务谁、菜如何流转、拥堵怎么处理、食材断供怎么办。介绍 PsyConsult 也一样，先讲医生工作流，再讲支撑它的技术。

## 图解

```text
差的表达：框架 A + 框架 B + 数据库 C + 数据库 D

好的表达：
临床资料分散
   ↓
拆成三领域流水线
   ↓
加入会话连续性、知识检索、流式反馈
   ↓
设计外部依赖降级与安全边界
   ↓
说明原型限制和下一步演进
```

## 分步骤体验

用四句话组织一次 60 秒回答：

1. **场景**：医生需要在一处整理病例并核对多类资料；
2. **方案**：接待层把请求交给诊断、治疗、药审三个领域步骤；
3. **难点**：长任务要持续反馈，多轮对话要保留上下文，资料服务失败不能拖垮主流程；
4. **边界**：这是辅助原型，生产化仍需认证、审计、数据治理与临床验证。

## 项目真实实现

可用于支撑面试叙述的真实证据：

- 图由 [`agent/core/workflow/graph_manager.py`](../../agent/core/workflow/graph_manager.py) 组装，含路由和三领域流水线；
- Redis Checkpoint 以 `session_id` 作为 `thread_id`，可用时入口包含历史压缩；
- Milvus 有三个用途不同的集合：`cloud_product_docs`、`qa_semantic_cache`、`long_term_memory`；
- [`app/service/chat_service.py`](../../app/service/chat_service.py) 把执行过程转成分段事件；
- MCP 管理器和示例服务已经存在，但**尚未接入聊天主图**，不能说成已上线能力。

## 源码二刷

为每个面试观点准备一处证据：

| 观点 | 源码证据 |
|---|---|
| 专业分工 | [`agent/agents/`](../../agent/agents/) |
| 有状态多轮 | [`agent/core/workflow/checkpointer.py`](../../agent/core/workflow/checkpointer.py) |
| 历史压缩 | [`agent/core/workflow/graph_manager.py`](../../agent/core/workflow/graph_manager.py) |
| 流式交互 | [`app/service/chat_service.py`](../../app/service/chat_service.py) |
| MCP 只是预留 | [`agent/core/mcp/`](../../agent/core/mcp/) 与主图的未引用关系 |

不要声称源码没有实现的能力。

## 面试背板

> 我做的是一个精神科临床决策支持原型。系统把病例请求组织成鉴别诊断、治疗推荐和药物审查流水线，并通过资料检索补充证据。Redis Checkpoint 保持同一会话上下文，内容过长时在入口压缩历史；服务端把长耗时过程持续推送到医生工作台。设计上允许 Redis、Milvus 等外部能力降级，但医学输出仍需人工复核。MCP 目前只有管理与示例代码，尚未接入主图。

## 常见问题

**面试时先讲技术栈可以吗？** 可以提，但先用一句话说明用户和问题，否则技术没有上下文。

**项目最大的亮点是什么？** 可强调分层、可观察流水线、会话状态和优雅降级；不要把“用了大模型”当唯一亮点。

**被问到不足怎么办？** 说明事实、影响和改进顺序，比回避更能体现工程判断。

## 自测

1. 用 60 秒、不看文档介绍项目。
2. 为“多轮连续性”指出一个源码文件。
3. 为什么不能说 MCP 已接入生产流程？
4. 说出一个当前取舍和一个后续改进。

## 导航

- 上一页：[临床边界](clinical-boundary.md)
- 返回：[Part 01 入口](index.md)
- 下一篇：[Part 02｜第一次跑起来](../part02-quickstart/index.md)
- 深入练习：[`learn/14-interview-guide/`](../14-interview-guide/README.md)
