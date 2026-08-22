# 07 双引擎知识检索

> 学习目标：Neo4j 图谱检索与 Milvus 向量检索的分工、Text2Cypher 的真实开关状态（面试易翻车点）、语义缓存设计。
> 状态：骨架已含全部要点与代码锚点，叙述性文字待补。

## 1. 分工

| | Neo4j 图谱 | Milvus 向量 |
|---|-----------|------------|
| 擅长 | 精确关系查询："A 药和 B 药有什么相互作用" | 相似内容检索："这个症状组合像哪条诊断标准" |
| 数据 | 疾病-症状-药物结构化关系（MERGE 幂等写入） | ICD-11 标准与指南文档分块嵌入 |
| 规模 | 16 种 Drug、27 条 INTERACTS_WITH、9 条 CONTRAINDICATED_WITH | mock_data/*.md（需先跑 `milvus_rag.py` 导入） |

## 2. 图谱工具（`agent/tools/graph_tool.py`）——注意真实默认值

**默认：关键词检索**（`ENABLE_LLM_GRAPH_CYPHER` 未开启时直接走 `_fallback_graph_keyword_search`：提取中英文关键词 → 模糊匹配节点与关系 → 结构化文本返回）。

**可选：Text2Cypher**——设置 `ENABLE_LLM_GRAPH_CYPHER=true` 后启用 `GraphCypherQAChain`（LLM 按 schema 生成 Cypher），**失败才回退**关键词检索。

> ⚠️ 面试口径：不要说成"Text2Cypher 为主、关键词兜底"——方向反了。准确说法："关键词检索为主（快、稳、零 token），Text2Cypher 作为可选增强，链路失败自动回退"。要不要翻转默认是开放讨论题。

## 3. 向量工具（`agent/tools/vector_tool.py`）

- langchain_milvus `Milvus` 向量库，`similarity_search_with_score(query, k=3)`
- 嵌入：DashScope `text-embedding-v2`（1536 维）
- ⚠️ 度量事实：代码未显式设置 metric，langchain-milvus 建集合默认 **L2**；显式 COSINE 的是长期记忆和语义缓存两个集合。描述别写混。

## 4. 语义缓存（`app/infra/cache.py`）

- 集合 `qa_semantic_cache`，IVF_FLAT + COSINE
- **两级命中**：L1_EXACT（规范化文本相等）→ L1_SEMANTIC（距离 < 0.08）
- **按 user 隔离**：写入带 user_id，查询 filter 本用户
- **v2 补齐的自填充**：推理成功后 `set_cache(query, response, user_id)`——此前只有预载脚本写缓存，在线链路永远 miss（第 11 章坑 7）
- 实测：L1_EXACT 命中 0.273s（对比全流程约 60s）

## 5. 知识构建（`agent/test/build_kg.py`）

- LLM 结构化抽取：`with_structured_output(KnowledgeGraph)`，RecursiveCharacterTextSplitter 分块（2000/重叠 200），跨块 dict/set 去重合并
- 幂等写入：`MERGE (n:Label {id}) SET n += props`——重跑不重复
- 产物即 `mock_data/*.json`（nodes/edges 格式）

## 待补内容

- [ ] 关键词检索的 Cypher 全文走读（`_fallback_graph_keyword_search`）
- [ ] 语义缓存 0.08 阈值的含义与误命中风险讨论（距离阈值 vs 相似度）

## 面试官可能追问

1. 语义缓存会不会"相似但答案不该复用"？（会——阈值 0.08 很保守，且按用户隔离；极端案例应降级走全流程，可讨论加 LLM 判别层）
2. 图谱为什么不做主检索？（数据规模小、关键词已够；图的价值在关系查询而非模糊匹配）
3. RAG 分块为什么 2000/200 overlap？（临床文档条目化强，大块保条目完整，重叠防边界切断语义）
