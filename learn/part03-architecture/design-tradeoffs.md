# 11｜设计取舍：没有免费的架构

## 学习目标

不把技术选择说成“最佳实践”，而是能说明每项选择解决什么问题、带来什么代价，以及当前原型还没有完成什么。

## 生活类比：门诊扩建的选择题

设置多个专家诊室能让职责清楚，却增加会诊时间；建立档案室能延续上下文，却要承担隐私和过期清理；边讨论边回传能减少等待焦虑，却让断线处理更复杂。架构设计是在约束中选组合，不是收集越多设备越好。

## 图解

### 先画人话图

```text
选择                    得到                    付出
分专家诊室              职责清楚                更多协调与等待
边工作边回信            尽早看到进度            断线和分段处理
保存会话档案            连续追问                隐私、过期和依赖
三类资料柜              各管一种资料            运维和概念复杂度
预留外部工具接口        便于未来扩展            没接通前不能算能力
```

### 再给技术图

```text
LangGraph multi-agent ──清晰节点/路由──代价：模型调用与状态复杂度
SSE over POST ─────────增量反馈──────代价：单向流、解析与代理缓冲
Redis Checkpoint ──────多轮状态──────代价：可用性与数据治理
Milvus × 3 collections ─不同语义─────代价：索引、生命周期、命中解释
Neo4j ─────────────────关系查询──────代价：图谱建设与一致性
MCP code (not wired) ──扩展预留──────现状：不在聊天主图
```

## 分步骤体验

评审一个设计时用四问法：

1. **问题是什么？** 例如长推理期间用户看不到反馈；
2. **当前选择是什么？** 用一次 POST 响应持续返回 SSE；
3. **代价是什么？** 客户端要处理分片，代理可能缓冲，恢复能力有限；
4. **替代方案何时更好？** 若需要高频双向控制，才考虑 WebSocket，而不是因为它“更高级”。

对 Redis、Milvus、Neo4j 和多 Agent 重复这四问。

## 项目真实实现

### 三领域流水线

收益是 Prompt、工具和输出职责清楚；代价是调用次数与时延增加。协调者允许从中间节点开始，减少无关步骤，但自由文本路由仍可能误判。

### Redis 入口

Checkpoint 可用时加入 `history_compression`，得到多轮连续性与上下文控制；不可用时直接进入协调者，保证单轮可用，但历史消失。

### 三个 Milvus 集合

- `cloud_product_docs`：文档片段；
- `qa_semantic_cache`：完整问答缓存；
- `long_term_memory`：提取后的长期临床事实。

分开能避免语义混淆，也带来三套结构和生命周期治理。

### MCP 现状

[`agent/core/mcp/mcp_manager.py`](../../agent/core/mcp/mcp_manager.py) 能加载配置并发现工具，[`agent/mcp_servers/`](../../agent/mcp_servers/) 有示例服务；但 [`agent/core/workflow/graph_manager.py`](../../agent/core/workflow/graph_manager.py) 与聊天初始化没有连接它们。因此当前取舍是“保留扩展骨架，主链路暂不承担外部 MCP 依赖”。

## 源码二刷

为每个取舍找到正反两处证据：

- SSE：服务端 `yield` 与工作台 `reader.read()`；
- Checkpoint：创建成功的压缩入口与失败时 `None` 分支；
- 缓存：命中快路径与补写会话状态；
- 多 Agent：条件入口与固定后续边；
- MCP：管理器实现与主图零调用。

相关入口：[`app/service/chat_service.py`](../../app/service/chat_service.py)、[`agent/core/workflow/checkpointer.py`](../../agent/core/workflow/checkpointer.py)、[`agent/core/workflow/graph_manager.py`](../../agent/core/workflow/graph_manager.py)。

## 面试背板

> 这个架构优先满足原型的可观察性、专业分工和多轮连续性：SSE 尽早反馈，多 Agent 明确职责，Redis 保存图状态，Milvus 分别承担文档、缓存和长期事实。代价是更多外部依赖、时延和数据治理成本，所以 Redis/Milvus 设计了降级。MCP 目前只保留扩展代码，没有接入主图，我不会夸大为已实现能力。

## 常见问题

**为什么不用 WebSocket？** 当前主要是“一次请求、服务端持续返回”，SSE 足够简单；需要持续双向消息时再评估 WebSocket。

**为什么既有 Milvus 又有 Neo4j？** 前者擅长语义相似检索，后者表达明确实体关系，两者解决的问题不同。

**降级是否意味着结果完全不受影响？** 不是。它保证流程尽量可用，不保证缺少资料后质量不变。

**MCP 为什么不直接接上？** 接入还需工具信任、超时、权限、失败隔离和测试，保留代码不等于完成这些工作。

## 自测

1. 为 SSE 说出一个收益和两个代价。
2. 为什么三个 Milvus 集合不能合并理解？
3. Redis 降级保住了什么、失去了什么？
4. 用源码事实说明 MCP 的当前状态。

## 导航

- 上一页：[目录地图](directory-map.md)
- 返回：[Part 03 入口](index.md)
- 下一阶段建议：[`learn/04-state-graph/`](../04-state-graph/README.md)
- 面试深化：[`learn/14-interview-guide/`](../14-interview-guide/README.md)
