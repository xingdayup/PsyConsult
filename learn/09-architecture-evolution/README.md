# 09 架构演进复盘：v1 自研记忆 → v2 Checkpoint

> 学习目标：这是本项目最值得讲的一章——一次真实的架构重构决策。为什么推翻自己一个月前的工作、v1 到底哪里不够、v2 换来了什么、付出了什么代价。

## 1. v1 是什么样（2026-08-22 之前）

```
每轮请求:
  ① 从 Redis 读短期消息列表 (memory:short:{user}:{session}, TTL 30min)
  ② 拼成 memory_context 文本字符串（最近 10 条 + Milvus 长期偏好）
  ③ 注入 AgentState.memory_context 字段
响应后:
  ④ save_conversation: get → 追加本轮 → set（读-改-写）
```

v1 的问题（逐条都有实锤）：

| # | 问题 | 实锤 |
|---|------|------|
| 1 | **只存 role/content 文本对**，各节点中间结论、工具调用全部不落盘 | checkpoint 里能看到诊断/治疗/药审三段输出，v1 的 Redis 里只有最终回答 |
| 2 | **硬裁剪丢信息**：>10 条砍到最近 6 条，早期病例细节直接消失 | `short_term.py._trim` |
| 3 | **长期提取链路从未生效**：web 端从不调用提取；CLI 调用**不存在的方法** `extract_and_save_preferences`（重构改名漏改） | CLI 必崩 AttributeError（finally 块里裸抛） |
| 4 | **读-改-写竞态**：同会话并发请求互相覆盖消息 | `save_conversation` 先 get 后 set |
| 5 | 文本注入与消息历史**两套事实来源**，图状态每轮从零开始 | 每轮 `state = {"messages": [单条]}` |

## 2. 决策：为什么换 LangGraph Checkpoint

决定性论据：**State 里已经有的东西，不该再手工同步一遍**。`AgentState.messages` 本来就是 add_messages reducer 累积语义，节点本来就吃全量 messages——v1 却每轮把 state 清零、再从 Redis 捞文本拼回去，等于框架送的多轮能力全部扔掉，自己用更弱的方式重造。

v2 换来：
- 完整 state 持久化（含节点结论），`thread_id` 一个参数完成隔离
- 历史天然进入各 agent prompt，`memory_context` 只剩长期记忆（职责变纯）
- 框架保证的状态合并语义替代手写读-改-写
- 官方 TTL / 断点续跑 / 时间旅行（aget_state_history）白拿

付出：
- Redis 必须换 redis-stack（RediSearch 依赖，第 11 章坑 2）
- 每超步序列化写盘（消息长后有开销 → 引出第 06 章压缩节点）
- 新增依赖 langgraph-checkpoint-redis

## 3. 迁移中补出来的三个非显然逻辑

重构不是 1:1 替换，有三个 v1 不存在的新问题：

1. **缓存命中旁路**（`_record_cache_hit_turn`）：命中语义缓存不经过图，必须 `aupdate_state` 手动补记该轮，否则多轮断裂——"所有改变对话状态的路经都必须写 checkpoint"这条不变式，是重构时才显性化的
2. **历史压缩**：消息只增不减是 checkpoint 模式的新代价，新增压缩节点（16/8 + 摘要）对冲
3. **提取源切换**：长期记忆提取从"读 Redis 短期消息"改为"读 checkpoint 历史"（`aget_state`），格式渲染函数随迁

## 4. 删除清单（"删代码也是交付"）

- `agent/core/memory/short_term.py` 整文件
- MemoryManager 的 `save_conversation / get_recent_messages / background_extract / finalize_session`
- chat_service 与 main.py 的历史拼装注入逻辑
- 净变化：+549 / -569 行（新功能两个，总行数反而降）

## 5. 如果重来一次

会在 v1 就问一个问题："**LangGraph 的 state 到底能不能跨请求存活？**"——文档里 checkpoint 一章读完就能避免整段弯路。教训：引入框架时把它的核心抽象（state/reducer/checkpointer）摸透，比急着写业务节点值钱。

## 面试官可能追问

1. v1 的问题里哪个最致命？（#3：长期记忆从未生效——写了完整功能但入口断的，测试没覆盖端到端）
2. 重构怎么保证不退步？（先全链路实测基线：多轮/缓存/压缩/提取逐项验证，第 10 章）
3. 还会再演进吗？（长期记忆 upsert 语义；图节点粒度的 checkpoint 细化；多 worker 下的进程内计数器外置）
