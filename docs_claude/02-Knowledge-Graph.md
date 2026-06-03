# 02 - 知识图谱

## 为什么要用知识图谱？

精神科诊疗知识天然是"关系"——疾病表现出症状、药物引起副作用、药物和药物之间有相互作用。

用表格存：三张表 JOIN 才能查到"抑郁的核心症状有哪些"。用图存：从"抑郁"节点顺着 `HAS_SYMPTOM` 箭头走一步就查到了。

这就是为什么选 Neo4j——它把数据存成节点和箭头，查询就是顺着箭头走。

## 存了什么

### 5 种实体

```
Disease     疾病         id=6A70, name_cn=抑郁发作, description=...
Symptom     症状         id=insomnia, name_cn=失眠, category=核心
Drug        药物         id=sertraline, name_cn=舍曲林, drug_class=SSRI
SideEffect  副作用       id=nausea, name_cn=恶心, frequency=常见
Treatment   治疗方案      id=ssri_mono, name_cn=SSRI单药治疗, line=一线
```

### 6 种关系

```
关系                            方向              属性
HAS_SYMPTOM         疾病 → 症状                criterion: "核心"或"附加"
FIRST_LINE          疾病 → 治疗方案
SECOND_LINE         疾病 → 治疗方案
CAUSES              药物 → 副作用
INTERACTS_WITH      药物 ↔ 药物                risk: "禁忌"/"谨慎"/"注意"
USES_DRUG           治疗方案 → 药物
```

### 一个具体的图

```
                 ┌──────────┐
                 │  6A70    │
                 │ 抑郁发作  │
                 └────┬─────┘
        ┌─────────┬───┼───┬─────────┐
        │HAS_      │   │HAS_       │FIRST_
        │SYMPTOM   │   │SYMPTOM    │LINE
        │(核心)    │   │(核心)     │
        ▼          │   ▼          ▼
  ┌──────────┐     │ ┌──────────┐ ┌──────────────┐
  │ insomnia │     │ │low_mood  │ │ ssri_mono    │
  │  失眠    │     │ │ 情绪低落 │ │ SSRI单药治疗  │
  └──────────┘     │ └──────────┘ └──────┬───────┘
                   │                    │USES_DRUG
                   │                    ▼
                   │              ┌──────────────┐
                   │              │ sertraline   │
                   │              │   舍曲林      │
                   │              └──┬────┬──────┘
                   │           CAUSES│    │CAUSES
                   │                ▼    ▼
                   │           ┌──────┐ ┌──────────┐
                   │           │nausea│ │sexual_dys│
                   │           │ 恶心 │ │ 性功能障碍│
                   │           └──────┘ └──────────┘
```

## 怎么查

用 Cypher 语言，语法类似"把你要找的图案画出来"：

```cypher
-- 抑郁的核心症状有哪些？
MATCH (d:Disease {id:'6A70'})-[r:HAS_SYMPTOM]->(s:Symptom)
WHERE r.criterion = '核心'
RETURN s.name_cn

-- 舍曲林和帕罗西汀能联用吗？
MATCH (a:Drug {id:'sertraline'})-[r:INTERACTS_WITH]->(b:Drug {id:'paroxetine'})
RETURN r.risk
-- 返回: "禁忌"
```

你不需要手写 Cypher——Agent 里的 `GraphCypherQAChain` 会自动把自然语言翻译成 Cypher。Agent 问"抑郁的核心症状有哪些"，LLM 自动生成上面的查询。

如果 LLM 生成的 Cypher 语法错误，系统有兜底方案：`_fallback_graph_keyword_search` 用关键词直接在节点和关系里做 `CONTAINS` 搜索，保证几乎总能返回点什么。

## 怎么构建

```
mock_data/
├── icd11_depression.md      抑郁障碍 ICD-11 标准
├── icd11_bipolar.md         双相障碍
├── icd11_anxiety.md         焦虑障碍
├── icd11_schizophrenia.md   精神分裂症
├── icd11_ocd.md             强迫症
├── psychiatric_drugs.md     精神科药物手册
└── china_guidelines.md      中国精神科指南摘要
```

这些 Markdown 文档 → `test/build_kg.py` 脚本 → LLM 逐块提取实体和关系 → 输出 JSON → 导入 Neo4j。

`build_kg.py` 做的事：
1. 用 `RecursiveCharacterTextSplitter` 把长文档切成块（chunk_size=2000）
2. 每块发给 LLM，提示词是"你是一个精神科医学知识图谱架构师，请从文档中提取 Disease/Symptom/Drug 等实体和关系"
3. 收集所有块的输出，按 node_id 去重
4. 用 Cypher `MERGE` 命令写入 Neo4j（`MERGE` = 没有就创建、有就复用，所以反复跑不产生重复数据）

数据模型定义在 `core/graph/models.py`，LLM 提取解析器在 `core/graph/parser.py`，批量导入器在 `core/graph/ingestor.py`。

## 图谱和向量检索的分工

| 查什么 | 用哪个 |
|--------|--------|
| 精确的关系——"舍曲林有哪些副作用"、"抑郁的核心症状有几条" | Neo4j 知识图谱 |
| 大段描述——"抑郁障碍防治指南中关于维持期治疗的建议" | Milvus 向量 RAG |

同一个问题"舍曲林的副作用"，图谱返回枚举列表（恶心/腹泻/失眠/性功能障碍），RAG 返回药品说明书原文段。两者互补。

## 下一步

- RAG 检索系统：→ `03-RAG-and-Tools.md`
- Mock 数据详解：→ `06-Mock-Data.md`
