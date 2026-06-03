"""临床症状同义词映射工具。
将医患口语化表达映射为标准 ICD-11 术语，同时标注对应量表条目。
"""
import os
import json
from langchain_core.tools import tool

_SYNONYMS = None


def _load_synonyms():
    global _SYNONYMS
    if _SYNONYMS is not None:
        return _SYNONYMS
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "symptom_synonyms.json")
    with open(path, "r", encoding="utf-8") as f:
        _SYNONYMS = json.load(f)
    return _SYNONYMS


@tool
def query_synonyms(phrase: str) -> str:
    """查询口语化症状描述对应的标准医学术语和 ICD-11 编码。
    当需要将患者的通俗表达（如"睡不着""没胃口"）映射为标准术语时调用。
    """
    synonyms = _load_synonyms()
    phrase_lower = phrase.strip().lower()

    # 精确匹配
    if phrase_lower in synonyms:
        return json.dumps(synonyms[phrase_lower], ensure_ascii=False)

    # 部分匹配（口语短语包含关键词）
    matches = []
    for key, value in synonyms.items():
        if key in phrase_lower or phrase_lower in key:
            matches.append(value)

    if matches:
        return json.dumps(matches, ensure_ascii=False)
    return json.dumps({"term": phrase, "icd11": None, "message": "未找到匹配的标准术语"}, ensure_ascii=False)
