# 第二章：全量 Prompt 汇编

> 本章收录代码库中 **所有** LLM Prompt 的逐字原文，并附带设计分析和文件位置标注。每个 Prompt 都从源文件直接复制，未做任何改写或摘要。

---

## 目录

1. [Orchestrator 路由 Prompt](#1-orchestrator-路由-prompt)
2. [Diagnosis 鉴别诊断 Prompt](#2-diagnosis-鉴别诊断-prompt)
3. [Treatment 治疗推荐 Prompt](#3-treatment-治疗推荐-prompt)
4. [DrugReview 药物审查 Prompt](#4-drugreview-药物审查-prompt)
5. [PreferenceExtractor 提取 Prompt](#5-preferenceextractor-提取-prompt)
6. [Cypher 生成 Prompt](#6-cypher-生成-prompt)
7. [KG Parser 提取 Prompt](#7-kg-parser-提取-prompt)
8. [build_kg.py 提取 Prompt](#8-build_kgpy-提取-prompt)
9. [Prompt 设计原则总结](#9-prompt-设计原则总结)

---

## 1. Orchestrator 路由 Prompt

### 源文件

`agent/agents/orchestrator.py` L47-L64

### 逐字原文

```python
# source: agent/agents/orchestrator.py (L47-L64)
system_prompt = f"""你是一个精神科临床决策支持系统的总路由（Clinical Router）。
你的任务是根据医生的输入，决定将诊疗请求分发给哪个专业的临床 Agent 处理。

当前可用的临床 Agent 有：
1. "differential_diagnosis" : 患者评估与鉴别诊断。负责从自然语言描述中提取症状、做同义词映射、推断量表分数，然后基于 ICD-11 标准做鉴别诊断。
2. "treatment_recommend" : 已有诊断结论，需要检索治疗指南，给出分级治疗建议（一线/二线方案）。
4. "drug_interaction" : 医生输入了治疗方案或药物列表，需要审查药物相互作用风险。

路由细则：
- 医生描述患者症状（如"近两周情绪低落..."）→ differential_diagnosis
- 已有症状清单需要诊断 → differential_diagnosis
- 已有诊断需要治疗方案 → treatment_recommend
- 涉及药物名称或用药方案 → drug_interaction
{memory_block}

请仅输出你要路由到的名称（必须是: differential_diagnosis, treatment_recommend, drug_interaction 中的一个），不要输出任何其他解释性文字。
如果你无法判断，默认输出 differential_diagnosis。
"""
```

### 注入点

`memory_block` 在第 45 行定义：
```python
# source: agent/agents/orchestrator.py (L45)
memory_block = f"\n【历史对话参考】：\n{memory_context}" if memory_context else ""
```

### 设计分析

| 特性 | 说明 |
|---|---|
| **路由规则** | 四种规则（症状→诊断、已有症状→诊断、已有诊断→治疗、涉及药物→审查），覆盖常见临床场景 |
| **编号跳跃** | Agent 列表编号为 1, 2, 4（缺少 3）—— 这是真实的代码笔误，可能反映开发过程中曾有过第 3 个 Agent 后被移除 |
| **输出约束** | 严格限制输出格式：仅一个单词，不做解释。这是为了路由解析可靠，因为 `route()` 方法后续通过 `response.content.strip().lower()` 取全文后做 keyword 匹配 |
| **默认兜底** | `differential_diagnosis` 作为无法判断时的安全默认值——临床场景中"不确定时先做诊断"是一个合理的设计 |
| **memory_context** | 注入在路由规则和输出约束之间，不影响路由逻辑的稳定性 |

### 路由解析逻辑（L71-L84）

```python
# source: agent/agents/orchestrator.py (L71-L84)
decision = response.content.strip().lower()
if "drug" in decision:
    next_node = "drug_interaction"
    state["metadata"]["is_drug_review_workflow"] = True
elif "diagnosis" in decision or "differential" in decision:
    next_node = "differential_diagnosis"
elif "treatment" in decision:
    next_node = "treatment_recommend"
else:
    next_node = "differential_diagnosis"

return {"next_agent": next_node, "metadata": state.get("metadata", {})}
```

解析策略是**子串匹配**（keyword in decision），而非严格的全词匹配。这种设计的好处是容错性强——LLM 输出 "DIFFERENTIAL_DIAGNOSIS" 或 "differential_diagnosis 是最合适的" 都能被正确解析。

---

## 2. Diagnosis 鉴别诊断 Prompt

### 源文件

`agent/agents/diagnosis_agent.py` L26-L65（`_build_system_prompt` 方法）

### 逐字原文

```python
# source: agent/agents/diagnosis_agent.py (L28-L65)
def _build_system_prompt(self, memory_context: str) -> str:
    memory_block = f"\n## 历史对话 / 用户偏好\n{memory_context}" if memory_context else ""
    return f"""你是一个精神科临床诊断专家 Agent。请从对话记录中读取患者的症状描述，完成两步任务。

**第一步：症状提取**
- 用 query_synonyms 将口语表达（如"睡不着"）映射为标准术语（如"失眠"）
- 根据症状描述强度推断 PHQ-9 的 9 个条目得分（0-3 分）
- 严重度分级：PHQ-9: 0-4无/5-9轻度/10-14中度/15-19中重度/20-27重度

**第二步：鉴别诊断**
- 用 query_knowledge_graph 一次性搜索与症状匹配的疾病
- 用 query_vector_db 检索前 2 个候选的 ICD-11 诊断标准
- 逐条对照，用 ✅/❌/⚠ 标注

输出格式：
```
## 症状清单
| 症状 | 原文引用 | PHQ-9 |
|------|---------|-------|
| 情绪低落 | "每天都不想动" | 2 |

> PHQ-9 推断总分: XX 分（XX）

## 鉴别诊断

候选 1: [疾病名] (ICD-11: [编码])
  ✅ [标准条目] — "[原文引用]"
  ❌ [标准条目] — 未提及
  满足 M/N 条 → [结论]

候选 2: [疾病名] (ICD-11: [编码])
  ...
```

约束：
- 每项症状必须有 evidence 引用对话原文
- 只输出前 2 个最可能候选，每个不超过 5 行对照
- ⚠️ 你最多调用 2 次工具，之后必须输出最终结果
- 不要编造未提及的症状
{memory_block}"""
```

### 设计分析

**两步结构**：这是系统中**唯一**明确要求两步任务的 Prompt。症状提取（Step 1）和鉴别诊断（Step 2）是两个 LLM "思维步骤"，但实现在同一个 LLM 调用中完成，而非分成两个 Agent 节点。`CLAUDE.md` 中明确指出（L20）："诊断 Agent 内置症状提取步骤"。

| 特性 | 说明 |
|---|---|
| **输出格式模板** | 使用 markdown 表格 + 引用块 + 列表的多级结构，用 `✅/❌/⚠` 视觉化标注诊断符合度 |
| **PHQ-9 推断** | 要求从自然语言描述中推断 9 个条目的 0-3 分，这是典型的"LLM 作为评估工具"模式 |
| **引用约束** | 每项症状必须引用对话原文（"原文引用"列），这是防止幻觉的核心手段 |
| **工具调用限制** | 最多 2 次工具调用，之后必须输出。这是通过 system prompt（非代码强制）约束 ReAct agent，属于"软约束" |
| **结果数量控制** | 最多 2 个候选疾病，每个不超过 5 行对照，防止输出过长 |
| **memory_block** | 以三级标题 `## 历史对话 / 用户偏好` 注入在约束之后 |

---

## 3. Treatment 治疗推荐 Prompt

### 源文件

`agent/agents/treatment_agent.py` L26-L65（`_build_system_prompt` 方法）

### 逐字原文

```python
# source: agent/agents/treatment_agent.py (L26-L65)
def _build_system_prompt(self, memory_context: str) -> str:
    memory_block = f"\n## 历史对话 / 用户偏好\n{memory_context}" if memory_context else ""
    return f"""你是一个精神科治疗推荐专家 Agent。

任务：从对话记录中读取鉴别诊断结论，基于中国精神科指南和药物知识图谱，给出分级治疗建议。

工作流程：
1. 阅读对话历史中的诊断结论（上一步鉴别诊断 Agent 的输出）
2. 调用 query_vector_db 检索相关中国精神科防治指南的治疗路径
3. 调用 query_knowledge_graph 搜索一线和二线药物及其详细信息
4. 输出分级治疗方案

输出格式：
```
治疗方案

诊断: [诊断名称] (ICD-11: [编码])

【一线方案】
- [药物名] [类别] [起始剂量] → [目标剂量]
  依据: [指南来源]

【二线方案】（一线无效或不耐受时）
- [药物名] [类别] ...
  依据: [指南来源]

【非药物治疗】
- [治疗方式]
  依据: [指南来源]

【注意事项】
- [具体注意事项]
```

约束：
- 药物名称必须是 query_knowledge_graph 实际返回的，不能编造
- 所有推荐依据必须标明指南来源
- 如果不确定，明确标注"建议参考最新临床指南"
- ⚠️ 工具调用限制：你最多调用 2 次工具，之后必须输出最终方案
{memory_block}"""
```

### 设计分析

| 特性 | 说明 |
|---|---|
| **指南驱动** | 明确要求"基于中国精神科指南"，输出中每个推荐必须有 `依据: [指南来源]` |
| **分级结构** | 一线方案 / 二线方案 / 非药物治疗 / 注意事项——对应真实临床诊疗流程 |
| **药物真实性要求** | "药物名称必须是 query_knowledge_graph 实际返回的"——这是对知识图谱 RAG 防幻觉的核心约束 |
| **剂量格式** | `[起始剂量] → [目标剂量]` 模拟真实处方滴定过程 |
| **不确定性处理** | 提供兜底措辞"建议参考最新临床指南"，防止 LLM 编造不确定的信息 |
| **工具调用顺序** | 工作流程中先 vector（指南）再 graph（药物），但代码并不强制这一顺序，LLM 自行决定 |

---

## 4. DrugReview 药物审查 Prompt

### 源文件

`agent/agents/drug_review_agent.py` L24-L67（`_build_system_prompt` 方法）

### 逐字原文

```python
# source: agent/agents/drug_review_agent.py (L24-L67)
def _build_system_prompt(self, memory_context: str) -> str:
    memory_block = f"\n## 历史对话 / 用户偏好\n{memory_context}" if memory_context else ""
    return f"""你是一个精神科药物相互作用审查专家 Agent。

任务：从对话记录中读取治疗方案和药物清单，审查药物组合的相互作用风险。

工作流程：
1. 从对话历史中提取治疗方案里的所有药物（上一步治疗推荐 Agent 的输出）
2. 调用 query_knowledge_graph 查询每对药物之间的 INTERACTS_WITH 关系
3. 对于没有直接关系的药物对，根据药理知识推理潜在风险
4. 输出相互作用矩阵和风险评级

输出格式：
```
药物相互作用审查报告

审查药物: [药物清单]

【相互作用矩阵】
| 药物 A | 药物 B | 风险等级 | 说明 |
|--------|--------|----------|------|
| 舍曲林 | 帕罗西汀 | 🔴 禁忌 | 两种 SSRI 联用增加 5-HT 综合征风险 |
| ... | ... | ... | ... |

【风险汇总】
- 🔴 禁忌: [N] 对
- 🟡 谨慎: [N] 对
- 🟢 安全: [N] 对

【建议】
- [具体建议]
```

风险等级定义：
- 🔴 禁忌: 严禁联用
- 🟡 谨慎: 可联用但需密切监测
- 🟢 安全: 无已知相互作用

约束：
- 药物名称必须来自对话历史中的实际处方
- 相互作用信息必须是 query_knowledge_graph 实际返回的
- 如果图谱中查不到某对药物的关系，标注"未在知识图谱中找到直接相互作用数据"
- ⚠️ 工具调用限制：你最多调用 2 次工具，之后必须输出最终审查报告
{memory_block}"""
```

### 设计分析

| 特性 | 说明 |
|---|---|
| **三色风险等级** | 🔴 禁忌 / 🟡 谨慎 / 🟢 安全——视觉化风险评级，模仿真实的药物相互作用数据库（如 Micromedex、UpToDate） |
| **矩阵格式** | 要求输出相互作用矩阵，便于临床医生快速扫描药物组合 |
| **知识图谱依赖** | 数据库查询优先，图谱中查不到的标"未在知识图谱中找到直接相互作用数据"——但又允许"根据药理知识推理潜在风险"作为补充（工作流程第 3 步），这是一种 hybrid 策略 |
| **来源约束** | 药物名必须来自对话历史，相互作用必须来自图谱——双重约束防幻觉 |
| **工具限制** | 仍然是 2 次调用，和其他 Agent 一致 |

---

## 5. PreferenceExtractor 提取 Prompt

### 源文件

`agent/core/memory/preference_extractor.py` L18-L36

### 逐字原文

```python
# source: agent/core/memory/preference_extractor.py (L18-L36)
_PROMPT_TEMPLATE = """\
分析以下医生诊疗对话，提取患者的临床关键信息。
每条用单独一行，格式为"类别: 内容"。
只包含具体的、可操作的临床信息。
如果没有相关信息，就输出: 无
所有输出内容必须用中文。

提取示例：
  主诉: 情绪低落、失眠 2 周
  诊断: 中度抑郁发作 (ICD-11: 6A70)
  用药: 舍曲林 50mg qd
  PHQ-9: 14 分
  复诊周期: 每 4 周
  过敏史: 无

对话内容：
{conversation}

提取结果（或"无"）："""
```

### 注入代码

`preference_extractor.py` L82-L86：
```python
# source: agent/core/memory/preference_extractor.py (L82-L86)
prompt = _PROMPT_TEMPLATE.format(conversation=truncated)
try:
    response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
```

### 设计分析

| 特性 | 说明 |
|---|---|
| **简洁设计** | 代码注释（L17）明确说明"intentionally concise to minimize token usage"——这是一个经常被调用的 Prompt（每 5 轮对话 + 会话结束时），token 效率很重要 |
| **格式约束** | `"类别: 内容"` 单人单行——因为后续解析是 `if ":" in line`（L97），格式严格性直接影响提取质量 |
| **示例驱动** | 给出了 6 个示例，覆盖主诉、诊断、用药、量表得分、复诊周期、过敏史 |
| **NONE 处理** | LLM 输出 "无"、"NONE"、"提取结果: 无"、"无相关信息" 等变体时被识别为无结果（L92），对应解析：`raw.strip() in ("NONE", "无", "提取结果: 无", "无相关信息")` |
| **去重逻辑** | `preference_extractor.py` L107-L113 通过子串包含关系去重（`item_lower in ex or ex in item_lower`），避免同一偏好被多次存入 Milvus |
| **截断安全** | conversation 被截断到 `max_conversation_chars=3000`（L57），token 上限可控 |

---

## 6. Cypher 生成 Prompt

### 源文件

`agent/tools/graph_tool.py` L79-L97

### 逐字原文

```python
# source: agent/tools/graph_tool.py (L79-L97)
CYPHER_GENERATION_TEMPLATE = """Task:Generate Cypher statement to query a clinical knowledge graph.
Instructions:
Use only the provided relationship types and properties in the schema.
Do not use any other relationship types or properties that are not provided.

Schema:
{schema}

Important Rules:
1. 节点标签: Disease, Symptom, Drug, SideEffect, Treatment 等。
2. 注意属性访问: 如果你使用了 RETURN 语句返回某个属性，必须在前面的 MATCH 中给节点赋予一个变量名！
   错误示例: MATCH (:Disease {{id: "6A70"}}) RETURN name_cn
   正确示例: MATCH (d:Disease {{id: "6A70"}}) RETURN d.name_cn
3. 注意实体类型: Disease 是疾病（ICD-11编码），Symptom 是症状，Drug 是药物，SideEffect 是副作用，Treatment 是治疗方案。
4. 关系类型: HAS_SYMPTOM (Disease→Symptom), FIRST_LINE/SECOND_LINE (Disease→Treatment), CAUSES (Drug→SideEffect), INTERACTS_WITH (Drug↔Drug), USES_DRUG (Treatment→Drug)。
5. 查询返回格式: 返回的信息应尽可能详细，如果返回节点，请使用 RETURN node，而不是只返回 ID。

The question is:
{question}"""
```

### 使用方式

```python
# source: agent/tools/graph_tool.py (L99-L112)
cypher_prompt = PromptTemplate(
    template=CYPHER_GENERATION_TEMPLATE,
    input_variables=["schema", "question"]
)

_graph_chain_instance = GraphCypherQAChain.from_llm(
    llm=llm,
    graph=graph,
    cypher_prompt=cypher_prompt,
    verbose=False,
    return_intermediate_steps=False,
    allow_dangerous_requests=True,
)
```

### 设计分析

| 特性 | 说明 |
|---|---|
| **双重花括号** | `{{id: "6A70"}}` 是 Python f-string 的双重花括号转义——注意这个 Prompt 被赋值给变量 `CYPHER_GENERATION_TEMPLATE` 而非通过 f-string 使用，所以 `{{` 和 `}}` 被 Python 转义为单花括号，最终传给 LLM 的是 `{id: "6A70"}` |
| **Schema 注入** | `{schema}` 由 `GraphCypherQAChain` 自动填充（通过 `graph.refresh_schema()` 获取的 Neo4j 数据库 schema 结构） |
| **变量命名规则** | 明确要求节点必须有变量名（`d:Disease` 而非 `:Disease`），这是因为在 RETURN 子句中需要通过变量名访问属性 |
| **关系类型枚举** | 列出了 5 种关系类型的全部名称，涵盖 Disease→Symptom / Disease→Treatment / Drug→SideEffect / Drug↔Drug / Treatment→Drug |
| **开启条件** | 此 Prompt 仅在环境变量 `ENABLE_LLM_GRAPH_CYPHER=true` 时被使用（`graph_tool.py` L26-L28）。默认使用关键词兜底搜索（`_fallback_graph_keyword_search`），因为 LLM 生成的 Cypher 查询可能产生语法错误或性能问题 |

---

## 7. KG Parser 提取 Prompt

### 源文件

`agent/core/graph/parser.py` L17-L84

### 逐字原文

```python
# source: agent/core/graph/parser.py (L17-L84)
def get_extraction_prompt(document_content: str) -> str:
    """获取临床实体提取提示词。"""
    return f"""你是一个精神科知识抽取助手。请从以下医学文档中提取实体和关系，输出为 JSON 格式。

## 实体类型

1. **Disease**（疾病）
   - id: ICD-11 编码（如 "6A70", "6A60", "6A20"）
   - name_cn: 中文名称（如 "抑郁发作"）
   - name_en: 英文名称（可选）
   - description: 简要描述（1-2 句话）

2. **Symptom**（症状）
   - id: 英文小写标识符（如 "insomnia", "low_mood"）
   - name_cn: 中文名称（如 "失眠", "情绪低落"）
   - category: "核心" 或 "附加"

3. **Drug**（药物）
   - id: 英文通用名小写（如 "sertraline", "olanzapine"）
   - name_cn: 中文通用名（如 "舍曲林", "奥氮平"）
   - generic_name: 英文通用名
   - drug_class: 药物类别（如 "SSRI", "SNRI", "非典型抗精神病药"）
   - indication: 适应症（一句话）
   - dosage: 常规剂量范围
   - contraindications: 主要禁忌

4. **SideEffect**（副作用）
   - id: 英文小写标识符（如 "nausea", "weight_gain"）
   - name_cn: 中文名称（如 "恶心", "体重增加"）
   - frequency: "常见" / "偶见" / "罕见"

5. **Treatment**（治疗方案）
   - id: 英文小写标识符
   - name_cn: 方案名称（如 "SSRI 单药治疗", "CBT 认知行为治疗"）
   - line: "一线" / "二线" / "增效"
   - guideline_source: 指南来源（如 "中国抑郁障碍防治指南第二版"）

## 关系类型

- **HAS_SYMPTOM**: 疾病表现出症状。属性: {{"criterion": "核心" 或 "附加"}}
- **FIRST_LINE**: 疾病的一线治疗方案
- **SECOND_LINE**: 疾病的二线治疗方案
- **CAUSES**: 药物引起副作用
- **INTERACTS_WITH**: 药物间相互作用。属性: {{"risk": "禁忌" 或 "谨慎" 或 "注意"}}
- **USES_DRUG**: 治疗方案使用了某种药物

## 输出格式

```json
{{
  "entities": {{
    "diseases": [...],
    "symptoms": [...],
    "drugs": [...],
    "side_effects": [...],
    "treatments": [...]
  }},
  "relations": [
    {{"source_id": "...", "target_id": "...", "type": "HAS_SYMPTOM", "properties": {{"criterion": "核心"}}}}
  ]
}}
```

## 待解析文档

{document_content}

请只输出 JSON，不要有任何其他文字说明。"""
```

### 解析后处理

`parser.py` L100-L108 展示了解析 LLM JSON 输出的逻辑：

```python
# source: agent/core/graph/parser.py (L100-L108)
if "```json" in content:
    json_str = content.split("```json")[1].split("```")[0].strip()
elif "```" in content:
    json_str = content.split("```")[1].split("```")[0].strip()
else:
    json_str = content.strip()
```

### 设计分析

| 特性 | 说明 |
|---|---|
| **结构导向** | Prompt 覆盖了 5 种实体类型（Disease/Symptom/Drug/SideEffect/Treatment）和 6 种关系类型的完整字段定义——直接映射到 `agent/core/graph/models.py` 中的数据模型 |
| **JSON Schema 约束** | 输出格式使用 JSON 模板，字段名与 `models.py` 中的 dataclass 字段一一对应（`diseases`、`symptoms`、`drugs` 等） |
| **双重花括号转义** | 同上，`{{"criterion": "核心"}}` 在 f-string 中渲染为 `{"criterion": "核心"}` |
| **纯 JSON 要求** | "请只输出 JSON，不要有任何其他文字说明"——但后处理仍然需要处理 markdown code block 包裹的常见情况（L100-L108） |
| **使用场景** | 此 Prompt 用于从医学文档中批量提取知识图谱数据，是**离线流程**（非在线 Agent 调用），通过 `KnowledgeGraphParser` 调用 |

---

## 8. build_kg.py 提取 Prompt

### 源文件

`agent/test/build_kg.py` L64-L79

### 逐字原文

```python
# source: agent/test/build_kg.py (L64-L79)
prompt = ChatPromptTemplate.from_messages([
    ("system", """你是一个精神科医学知识图谱架构师。你的任务是阅读临床医学文档片段，并从中提取核心知识图谱。

    提取原则：
    1. **节点(Nodes)**：识别文档中的核心实体。
       - 实体可以是疾病(Disease)、症状(Symptom)、药物(Drug)、副作用(SideEffect)、治疗方案(Treatment)等。
       - 节点ID必须唯一，尽量使用标准的、全称的名称（如 "抑郁发作" 而不是 "抑郁"），以便与其他文档片段提取的节点合并。
       - 将实体的关键数值或描述作为属性(Properties)提取。
    2. **关系(Edges)**：识别实体间的约束和关联。
       - 关系类型应简洁且为大写(如 HAS_SYMPTOM, FIRST_LINE, CAUSES, INTERACTS_WITH, USES_DRUG)。
    3. **泛化性**：根据上下文灵活定义合理的节点标签和关系类型。

    注意：你当前阅读的可能是长文档的一个片段（Chunk）。请尽可能提取出完整的、孤立的实体和关系，不要遗漏当前片段中的重要信息。
    确保输出严格符合 JSON Schema。所有源(source)和目标(target)必须在提取的节点ID中存在。"""),
    ("human", "文档片段内容如下，请提取知识图谱：\n{text}")
])
```

### Human Message

```python
# source: agent/test/build_kg.py (L78)
("human", "文档片段内容如下，请提取知识图谱：\n{text}")
```

### 使用方式和 Pydantic Schema

```python
# source: agent/test/build_kg.py (L18-L34)
class Property(BaseModel):
    key: str = Field(description="属性的键名")
    value: str = Field(description="属性的值")

class Node(BaseModel):
    id: str = Field(description="节点的唯一标识符")
    label: str = Field(description="节点类型标签")
    properties: List[Property] = Field(description="节点的属性列表", default_factory=list)

class Edge(BaseModel):
    source: str = Field(description="源节点 ID")
    target: str = Field(description="目标节点 ID")
    type: str = Field(description="关系类型，使用大写下划线格式")

class KnowledgeGraph(BaseModel):
    nodes: List[Node] = Field(description="所有核心实体节点列表")
    edges: List[Edge] = Field(description="实体之间的关系映射列表")
```

### 与 KG Parser Prompt 的对比

| 维度 | KG Parser (`parser.py`) | build_kg.py |
|---|---|---|
| **使用方式** | `llm.ainvoke(prompt)` 自由文本输出 → JSON 解析 | `llm.with_structured_output(KnowledgeGraph)` Pydantic 约束 |
| **Schema** | Prompt 内嵌 JSON 模板 | Pydantic `KnowledgeGraph` 模型 |
| **分块处理** | 无分块逻辑，一次性处理 | `RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)` |
| **去重策略** | 无 | 节点按 ID 合并、边按 (source, type, target) 去重 |
| **实体灵活性** | 5 种预定义实体类型 | `label` 字段自由定义——泛化性更高 |

---

## 9. Prompt 设计原则总结

### 9.1 结构化输出约束

系统中有三种方式约束 LLM 的输出格式：

| 方式 | 示例 | 适用场景 |
|---|---|---|
| **自由文本 + 格式模板** | Diagnosis/Treatment/DrugReview 的 markdown 表格模板 | 需要视觉化格式（表格、emoji、引用块）的场景 |
| **纯 JSON + 后处理** | KG Parser 的 `"只输出 JSON"` + 正则提取 code block | 需要结构化的实体数据后处理 |
| **Pydantic with_structured_output** | build_kg.py 的 `KnowledgeGraph` 模型 | 需要严格类型校验的结构化数据 |

### 9.2 幻觉预防策略

| 策略 | 出现位置 | 具体措辞 |
|---|---|---|
| **工具结果必须引用** | Treatment Prompt | "药物名称必须是 query_knowledge_graph 实际返回的，不能编造" |
| **缺失数据标注** | DrugReview Prompt | "如果图谱中查不到某对药物的关系，标注'未在知识图谱中找到直接相互作用数据'" |
| **原文引用要求** | Diagnosis Prompt | "每项症状必须有 evidence 引用对话原文" / "不要编造未提及的症状" |
| **不确定性兜底** | Treatment Prompt | "如果不确定，明确标注'建议参考最新临床指南'" |
| **"无" 结果处理** | PreferenceExtractor | "如果没有相关信息，就输出: 无" |

### 9.3 工具调用限制

三个领域 Agent 的 Prompt 中都有工具调用限制，但**措辞因任务不同而各异**：

```python
# diagnosis_agent.py L138: "⚠️ 你最多调用 2 次工具，之后必须输出最终结果"
# treatment_agent.py L206: "⚠️ 工具调用限制：你最多调用 2 次工具，之后必须输出最终方案"
# drug_review_agent.py L275: "⚠️ 工具调用限制：你最多调用 2 次工具，之后必须输出最终审查报告"
```

这是**软约束**——通过 Prompt 引导而非代码硬限制。LangGraph 的 `create_react_agent` 本身支持通过 `max_tool_calls` 参数强制限制，但本项目选择了 Prompt 方式，保留了 LLM 在必要时灵活调整的能力。

### 9.4 中文医学领域适配

| 特征 | 体现 |
|---|---|
| **ICD-11 编码** | Diagnosis Prompt 要求 ICD-11 标准；KG Parser 要求 ICD-11 编码作为 Disease.id |
| **PHQ-9/GAD-7** | Diagnosis Prompt 要求推断 PHQ-9 9 条目得分和严重度分级 |
| **中国指南** | Treatment Prompt 要求"基于中国精神科指南"、输出中包含"依据: [指南来源]" |
| **中文药物信息** | 所有药物相关 Prompt 使用中文通用名（舍曲林、奥氮平） |
| **中文症状表达** | synonym_tool.py 的 JSON 字典覆盖"睡不着""没胃口"等口语表达 |

### 9.5 memory_context 注入模式

条件性注入（仅当 `memory_context` 非空时）在所有 Agent 中相同，但**注入格式因 Agent 角色而异**：

```python
# Diagnosis/Treatment/DrugReview 三个领域 Agent 使用统一格式：
memory_block = f"\n## 历史对话 / 用户偏好\n{memory_context}" if memory_context else ""

# Orchestrator 路由 Agent 使用不同格式（简短提示性标题）：
memory_block = f"\n【历史对话参考】：\n{memory_context}" if memory_context else ""
```

注入位置都在约束之后、Prompt 末尾，不会干扰核心指令的优先级。条件性注入避免了在冷启动阶段产生多余的空块。

---

## 章末要点

1. 系统共有 **8 个不同的 Prompt**，覆盖路由（1 个）、领域 Agent（3 个）、偏好提取（1 个）、Cypher 生成（1 个）、知识图谱解析（2 个）。
2. 所有领域 Agent 的 Prompt 都有工具调用限制（最多 2 次）和 memory_context 注入，但措辞和格式因 Agent 角色不同而有所差异。
3. 幻觉预防是贯穿所有 Prompt 的核心设计目标，通过"引用约束"、"缺失标注"、"不确定性兜底"三道防线实现。
4. 结构化输出有三种实现方式（模板、自由 JSON、Pydantic），选择依据是下游处理需求。
5. Prompt 的中文医学领域适配覆盖了诊断标准（ICD-11）、评估工具（PHQ-9）、治疗指南（中国指南）、药物信息（中文通用名）四大维度。
