# 05 会话状态管理（Checkpointer + Redis）

> 学习目标：讲清 LangGraph Checkpoint 的机制、本项目的接入方式、以及"无 Redis 也能跑"的优雅降级。
> 状态：骨架已含全部要点与代码锚点，叙述性文字待补。

## 1. Checkpoint 是什么

LangGraph 的 checkpointer 在**每个超步（super-step）后**把整个 state channel 序列化持久化，按 `thread_id` 组织。下次以相同 thread_id 调用，图的输入会**合并进已有状态**（messages 走 reducer 追加），节点读到的是累积后的完整状态。

对比"自己往 Redis 存消息"（v1 做法，第 09 章）：checkpoint 存的是**结构化 state**（含每个节点的输出消息、路由标记），不只是 role/content 文本对；恢复语义由框架保证。

## 2. 本项目接入（`agent/core/workflow/checkpointer.py`）

```python
saver = AsyncRedisSaver(
    redis_url=..., 
    ttl={"default_ttl": 86400, "refresh_on_read": True},  # 24h，读时续期
)
await saver.asetup()          # 建索引（FT.CREATE，依赖 RediSearch！）
graph = builder.compile(checkpointer=saver)
config = {"configurable": {"thread_id": session_id}}
```

三个工程决策：
- **thread_id = session_id**：前端会话隔离天然复用；session_id 已被正则校验，安全
- **TTL + 读时续期**：活跃会话不过期，废弃会话 24h 后由 Redis 自动回收（对齐旧版 30min 短期记忆的意图，放宽到天级）
- **工厂返回 None 的降级**：包未装 / Redis 不可用 / asetup 失败 → 返回 None → 图无状态运行，功能不崩（多轮能力丢失但有日志告警）

## 3. Redis 里存了什么（实测）

键形如 `checkpoint:checkpoint:{thread_id}`、`checkpoint_write:{thread_id}:...`，依赖 RediSearch 索引做时间线查询。实测 `aget_state` 返回完整消息列表（见第 10 章：10 → 15 → 压缩后 11 条）。

## 4. 缓存命中的旁路写入（`chat_service._record_cache_hit_turn`）

```python
await graph.aupdate_state(config, {
    "messages": [HumanMessage(query), AIMessage(answer)]
})
```
不经图执行、直接把该轮追加进 checkpoint——多轮连续性对调用方透明。

## 5. 相关坑（详见第 11 章）

- redis:7-alpine **没有 RediSearch**，`FT.INFO` 报 unknown command → 必须用 `redis/redis-stack-server` 镜像
- `from_conn_string` 是上下文管理器，服务器长持场景要直接构造 + `asetup()`

## 待补内容

- [ ] AsyncRedisSaver 的存储结构走读（checkpoint blob / writes / index 三类键）
- [ ] TTL 实验记录：暂停 24h+ 后会话恢复行为（可模拟：手动改 TTL）

## 面试官可能追问

1. checkpoint 每轮都全量写，消息很长了会不会越来越慢？（会——所以有第 06 章的历史压缩；也可讨论增量序列化）
2. 多 worker 部署时 checkpoint 一致性？（Redis 集中式存储天然共享；注意进程内轮次计数器不共享的小坑）
3. 为什么不用 PostgresSaver？（合理；Redis 已在栈内且访问模式是 KV 整存整取）
