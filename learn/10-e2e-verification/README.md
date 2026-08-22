# 10 全链路实测

> 本章所有数字来自 2026-08-23 的真实端到端验证（docker 四服务 + 真实 DashScope LLM），日志在 `logs/backend.log`。
> 用法：面试时"你怎么知道它能跑？"——把这一章的数字背下来。

## 1. 验证矩阵与结果

| # | 验证项 | 结果 | 关键证据 |
|---|--------|------|---------|
| 1 | 基础设施 | ✅ | redis-stack / Milvus / Neo4j / MySQL 四容器健康 |
| 2 | Checkpoint 就绪 | ✅ | `Checkpointer ready – Redis session state at redis://localhost:6379` |
| 3 | 单轮全流程 | ✅ | 四节点全跑通，126 条 SSE 事件，`done:true` 正常收尾 |
| 4 | 多轮连续推理 | ✅ | 第 2 轮正确**中途入链**（orchestrator→treatment→drug），回答基于上文（"中度抑郁 + 艾司西酞普兰"） |
| 5 | checkpoint 累积 | ✅ | 消息 10 → 15 条跨轮累积（aget_state 实读） |
| 6 | 语义缓存命中 | ✅ | 重复提问 **0.273s**（全流程约 60s），`L1_EXACT distance=0.0000` |
| 7 | 缓存命中旁路写入 | ✅ | `event=cache_hit_state_recorded` |
| 8 | 长期记忆提取 | ✅ | 第 5 轮自动触发（`turn=5`），提取 6 条临床要点 |
| 9 | 长期记忆检索 | ✅ | 语义查询召回 4/6 条 |
| 10 | 历史压缩 | ✅ | 19 条 → 触发压缩，终态 11 条（8 保留 + 摘要 + 本轮输出） |
| 11 | 回归 | ✅ | pytest 11 项通过 |

## 2. 多轮验证的会话脚本

```
T1: 患者近两周情绪低落、失眠、食欲下降，以前喜欢打篮球现在没兴趣了，请问可能的诊断是什么
    → 路由 differential_diagnosis → 全流水线
T2: 这位患者如果确诊中度抑郁发作，一线治疗首选什么药物？起始剂量多少？
    → "这位患者"指代上一轮病例 = checkpoint 连续性考题
T3: 重复 T1 原文
    → 语义缓存命中考题
T4-T6: 三条药物审查短问题（补轮次）
T7: 注入 3 条填充消息（aupdate_state）至 18 条 + 一条真实提问
    → 历史压缩考题
```

## 3. 三个最值钱的截图/日志

**缓存命中（快 200 倍）：**
```
event=semantic_cache_hit level=L1_EXACT distance=0.0000 matched='患者近两周…'
event=cache_hit_state_recorded          ← 旁路写入 checkpoint
curl 实测: real 0m0.273s
```

**长期记忆提取产物：**
```
[MEMORY] Extracted 6 new clinical facts:
  主诉: 情绪低落、失眠、食欲下降、兴趣减退 2 周
  诊断: 抑郁症 (ICD-11: 6A71)
  PHQ-9: 10 分（中度）
  用药: 艾司西酞普兰 5 mg qd（晨服），2周后可滴定至10–20 mg qd
  复诊周期: 2周后首次评估疗效与耐受性
  过敏史: 无
```

**压缩前后 checkpoint 状态（aget_state 实读）：**
```
压缩前: 19 messages
压缩后: 11 messages
  [0-3] 近两轮药物问答（保留窗口）
  [4-6] 填充消息
  [7]   本轮 HumanMessage
  [8]   SystemMessage: 【历史会话摘要】主诉与症状：近两周情绪低落、失眠…
  [9-10] 本轮 AI 输出
→ 最初病例被删掉原文后，核心信息仍活在摘要里
```

## 4. 验证方法论（比数字更通用）

1. **先修通信再验业务**：鉴权 401 → 400 body 解析 → SSE 断流，逐层推进
2. **失败重试会污染 checkpoint**（输入消息已写入）——验证数据要能区分"遗留输入"与真实累积
3. **旁路写入要有专属日志事件**（cache_hit_state_recorded），否则断言只能靠猜
4. **独立脚本直读存储**（aget_state / redis-cli / pymilvus）做客观断言，别只信接口返回

## 面试官可能追问

1. 怎么验证"多轮真的有效"而不是模型瞎编？（T2 用指代词"这位患者"，答对了上一轮才有的诊断语境）
2. 压缩会不会把关键信息摘丢？（交叉冗余：关键临床要点同时在长期记忆里有第二份）
3. 这些验证怎么固化成 CI？（pytest 已覆盖鉴权/日志；多轮/压缩可用 InMemorySaver + 桩 LLM 做单测，见 v2 开发时的冒烟测试思路）
