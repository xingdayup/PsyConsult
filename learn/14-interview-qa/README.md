# 14 深挖 Q&A：面试官视角

> 用法：每题先自己答，再看参考答案。答案里的事实全部对齐当前代码实现。分三类：项目深挖 / LangGraph 八股 / 系统设计。

## A. 项目深挖

**A1. 多轮对话具体是怎么实现的？**
答：LangGraph Checkpointer（AsyncRedisSaver）。每轮请求只带新消息，`config.thread_id = session_id`；`AgentState.messages` 是 `add_messages` reducer 通道，新消息追加到 checkpoint 已有历史上，各节点直接读全量消息。TTL 24 小时读时续期。实测第 2 轮问"这位患者一线用药"能正确路由到治疗节点并引用上一轮诊断。

**A2. 消息越来越长怎么办？**
答：图入口有 history_compression 节点：>16 条时，保留最近 8 条，其余由 temperature=0 的 LLM 压缩成一条 SystemMessage 摘要（提示词约束保留主诉/诊断/用药/量表分等要素），用 RemoveMessage 全删 + 重放实现可控排序。实测 19→11 条，最初病例的主诉和 PHQ-9 分在摘要里无损保留。

**A3. 语义缓存怎么设计的？命中条件？**
答：Milvus 集合 qa_semantic_cache，IVF_FLAT + COSINE。两级：规范化文本精确匹配（L1_EXACT）；向量距离 < 0.08 判相似（L1_SEMANTIC）。按 user_id 过滤隔离。推理成功后自动写入（自填充）。实测重复问题 0.273s 返回，全流程约 60s。关键细节：命中不经过图，必须 `aupdate_state` 把该轮补进 checkpoint，否则多轮断。

**A4. 长期记忆为什么每 5 轮提取一次？提取了什么？**
答：每轮提取浪费且重复率高。按 (user_id, session_id) 进程内计数，第 5 的倍数轮起后台任务：从 checkpoint 读历史 → LLM 按"类别: 内容"格式提取临床要点 → 与已有记忆子串去重 → 向量化存 Milvus。实测提取 6 条（主诉/诊断 ICD-11 编码/PHQ-9/用药/复诊周期/过敏史）。已知局限：只增不删，用药调整后新旧共存——改进方向是按类别 upsert。

**A5. 这个项目你重构过什么？为什么？**
答：记忆体系整体重构（第 09 章）。v1 自研 Redis 短期记忆：只存 role/content 文本对、每轮拼字符串注入、>10 条硬裁剪、读改写竞态，且长期提取链路在 web 端根本没接、CLI 调了个不存在的方法。决定性认识：AgentState 本来就有 add_messages 累积语义，节点本来就读全量消息——v1 等于把框架自带的多轮能力扔掉重造了个更弱的。v2 换 Checkpoint 后净删 500 行。

**A6. 工具调用结果会存进 checkpoint 吗？**
答：不会。内层 ReAct agent 的工具调用轨迹在节点执行内消费，只有节点最终 AIMessage 写回共享状态。这是我接受的取舍：临床上有价值的是结论而非过程；要审计工具轨迹可以另接 langsmith/日志。

## B. LangGraph / Agent 八股

**B1. StateGraph 的 reducer 是什么？为什么需要？**
答：channel 级的合并函数，定义"新输入怎么和已有状态合并"。无 reducer 直接覆盖；`add_messages` 追加 + 按 id 去重更新 + 支持 RemoveMessage 删除。并行节点写同一 channel 时 reducer 决定合并语义，是 checkpoint 多轮累积的基础。

**B2. Checkpointer 在什么时机写盘？**
答：每个超步（super-step，一轮节点执行）结束后把全部 channel 序列化持久化，按 thread_id 组织。恢复时输入与已存状态做 reducer 合并。本项目用 AsyncRedisSaver，注意它依赖 RediSearch 建索引——官方 redis 镜像没有，必须 redis-stack（我踩过：FT.INFO unknown command）。

**B3. astream 的 stream_mode 有哪些？你怎么用？**
答：常用 values / updates / custom / messages。项目用 `["updates","custom"]`：updates 拿节点完成事件（渲染阶段面板），custom 拿节点里 `get_stream_writer()` 发的自定义事件（agent 启动、工具调用、token 级 chunk）。

**B4. create_react_agent 和自建 StateGraph 节点什么关系？**
答：项目两层都用：外层 StateGraph 表达"条件入口 + 固定临床流水线"的确定性结构；每个节点内部 create_react_agent 处理"调哪个工具调几次"的不确定性。结构确定性与行为自主性分层。

**B5. 如果要给图加人工审批（HITL），怎么做？**
答：interrupt_before/interrupt_after 指定节点，图暂停并 checkpoint 状态，人工决策后以同 thread_id 恢复。临床场景天然适用：药审节点前挂医生确认。checkpoint 让这成为"白拿"的能力。

## C. 系统设计

**C1. QPS 涨 100 倍，瓶颈在哪？怎么改？**
答：逐层看——LLM 调用是串行流水线（诊断→治疗→药审），延迟叠加；Milvus 嵌入调用是每次请求的前置同步步骤。改法：语义缓存命中率是第一杠杆（已有）；无依赖的节点可并行化；嵌入可缓存/异步化；LLM 按节点分级（路由用小模型）；进程内轮次计数器外置 Redis。

**C2. 医疗场景的幻觉怎么控制？**
答：三层——提示词层强制"逐条对照 ICD-11 + 原文引用 + 未提及标 ❌，不许编造"；检索层给标准原文而非让模型回忆；产品层明确"仅供参考"的免责边界 + 医生终审。彻底的 eval 需要 golden set 回归（未来工作）。

**C3. 为什么 SSE 不是 WebSocket？流断了怎么办？**
答：单向推送场景，SSE 复用 HTTP 基建（鉴权头、网关、重连语义），前端 EventSource/fetch 流读取即可。断流时生成器被取消，checkpoint 已记录到完成的节点；客户端重发同一 query 会因语义缓存拿到完整答案——缓存意外提供了断点恢复。

**C4. 三种存储（Redis/Milvus×2 集合）会不会过度设计？**
答：按访问模式拆：checkpoint 是 KV 整存整取要 TTL → Redis；长期记忆和语义缓存都是向量相似检索 → Milvus 但集合隔离（生命周期与淘汰策略不同：记忆只增、缓存可淘汰重建）。

**C5. 怎么评估这个系统的质量？**
答：分层 eval——单轮答案质量（golden 病例集 + LLM-as-judge 对照 ICD-11 要点覆盖率）；多轮记忆（指代问题准确率）；系统指标（缓存命中率、各节点延迟、token 成本——日志里都有埋点）。

## 使用建议

- 每题先口述录音再对答案，比默读有效
- A 类必须滚瓜烂熟（必问）；B 类答出"我的项目里怎么用的"就赢了纯八股选手
- C 类没有标准答案，讲清 trade-off 和"我的项目现状→改进方向"的结构
