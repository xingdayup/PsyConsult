"""基于 LLM 的精神科知识图谱实体提取解析器。"""

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_community.chat_models import ChatTongyi

from config import get_settings
from .models import Disease, Symptom, Drug, SideEffect, Treatment, Relation

logger = logging.getLogger(__name__)


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


class KnowledgeGraphParser:
    """精神科知识图谱解析器。"""

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        settings = get_settings()
        self.llm = llm or ChatTongyi(**settings.get_model_config())

    async def parse_text(self, text: str) -> dict[str, list[Any]]:
        prompt = get_extraction_prompt(text)
        logger.info("Extracting clinical entities from document...")
        response = await self.llm.ainvoke(prompt)
        content = response.content

        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()

            data = json.loads(json_str)
            result = self._convert_to_models(data)

            logger.info(
                "Extraction: %d diseases, %d symptoms, %d drugs, %d side_effects, %d treatments, %d relations",
                len(result.get("diseases", [])),
                len(result.get("symptoms", [])),
                len(result.get("drugs", [])),
                len(result.get("side_effects", [])),
                len(result.get("treatments", [])),
                len(result.get("relations", [])),
            )
            return result

        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM JSON: %s", e)
            raise

    async def parse_file(self, file_path: str | Path) -> dict[str, list[Any]]:
        file_path = Path(file_path)
        logger.info("Parsing file: %s", file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return await self.parse_text(content)

    def _convert_to_models(self, data: dict) -> dict[str, list[Any]]:
        entities = data.get("entities", {})
        relations_data = data.get("relations", [])

        result = {
            "diseases": [Disease(**d) for d in entities.get("diseases", [])],
            "symptoms": [Symptom(**s) for s in entities.get("symptoms", [])],
            "drugs": [Drug(**d) for d in entities.get("drugs", [])],
            "side_effects": [SideEffect(**s) for s in entities.get("side_effects", [])],
            "treatments": [Treatment(**t) for t in entities.get("treatments", [])],
            "relations": [
                Relation(
                    source_id=r["source_id"],
                    target_id=r["target_id"],
                    relation_type=r["type"],
                    properties=r.get("properties", {}),
                )
                for r in relations_data
            ],
        }
        return result
