"""精神科知识图谱实体的数据模型。"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Disease:
    """疾病实体（ICD-11）。"""
    id: str                                    # icd11_code, e.g. "6A70"
    name_cn: str                               # 中文名, e.g. "抑郁发作"
    name_en: str = ""                          # 英文名
    description: str = ""                      # 简要描述


@dataclass
class Symptom:
    """症状实体。"""
    id: str                                    # unique id, e.g. "insomnia"
    name_cn: str                               # 中文名, e.g. "失眠"
    category: Literal["核心", "附加"] = "核心"   # 核心症状 vs 附加症状


@dataclass
class Drug:
    """药物实体。"""
    id: str                                    # generic name, e.g. "sertraline"
    name_cn: str                               # 中文通用名, e.g. "舍曲林"
    generic_name: str = ""                     # 英文通用名
    drug_class: str = ""                       # 药物类别, e.g. "SSRI"/"SNRI"/"非典型抗精神病药"
    indication: str = ""                       # 适应症
    dosage: str = ""                           # 剂量范围
    contraindications: str = ""                # 禁忌


@dataclass
class SideEffect:
    """药物副作用实体。"""
    id: str                                    # unique id
    name_cn: str                               # 中文名, e.g. "恶心"
    frequency: Literal["常见", "偶见", "罕见"] = "常见"


@dataclass
class Treatment:
    """治疗方案实体。"""
    id: str                                    # unique id
    name_cn: str                               # 方案名称, e.g. "SSRI 单药治疗"
    line: Literal["一线", "二线", "增效"] = "一线"
    guideline_source: str = ""                 # 指南来源


@dataclass
class Relation:
    """实体间的关系。"""
    source_id: str
    target_id: str
    relation_type: Literal[
        "HAS_SYMPTOM",         # Disease → Symptom
        "FIRST_LINE",          # Disease → Treatment
        "SECOND_LINE",         # Disease → Treatment
        "CAUSES",              # Drug → SideEffect
        "INTERACTS_WITH",      # Drug ↔ Drug
        "USES_DRUG",           # Treatment → Drug
    ]
    properties: dict = field(default_factory=dict)
    # HAS_SYMPTOM: {"criterion": "核心"|"附加"}
    # INTERACTS_WITH: {"risk": "禁忌"|"谨慎"|"注意"}
