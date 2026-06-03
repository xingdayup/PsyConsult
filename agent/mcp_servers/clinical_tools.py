"""临床 MCP 工具服务器。
提供量表计分和药物说明书查询功能。
"""
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ClinicalToolsServer")

# ==============================================================================
# 量表计分规则
# ==============================================================================
SCALE_SCORING = {
    "PHQ-9": {
        "items": 9,
        "severity": [
            (0, 4, "无抑郁"),
            (5, 9, "轻度"),
            (10, 14, "中度"),
            (15, 19, "中重度"),
            (20, 27, "重度"),
        ],
    },
    "GAD-7": {
        "items": 7,
        "severity": [
            (0, 4, "无焦虑"),
            (5, 9, "轻度"),
            (10, 14, "中度"),
            (15, 21, "重度"),
        ],
    },
}


@mcp.tool()
def calculate_scale_score(scale_type: str, answers: str) -> str:
    """计算心理量表得分和严重度分级。

    Args:
        scale_type: 量表类型，支持 "PHQ-9" 或 "GAD-7"
        answers: 逗号分隔的分数列表，如 "2,2,1,0,2,1,2,0,1"
    """
    if scale_type not in SCALE_SCORING:
        return json.dumps({"status": "error", "message": f"不支持的量表类型: {scale_type}"}, ensure_ascii=False)

    config = SCALE_SCORING[scale_type]
    try:
        scores = [int(x.strip()) for x in answers.split(",")]
    except ValueError:
        return json.dumps({"status": "error", "message": "answers 必须为逗号分隔的整数"}, ensure_ascii=False)

    if len(scores) != config["items"]:
        return json.dumps(
            {"status": "error", "message": f"{scale_type} 需要 {config['items']} 个分数，实际收到 {len(scores)} 个"},
            ensure_ascii=False)

    total = sum(scores)
    severity = "未知"
    for low, high, label in config["severity"]:
        if low <= total <= high:
            severity = label
            break

    return json.dumps({
        "status": "success",
        "data": {
            "scale_type": scale_type,
            "scores": scores,
            "total": total,
            "severity": severity,
        }
    }, ensure_ascii=False)


@mcp.tool()
def query_drug_label(drug_name: str) -> str:
    """查询精神科药物的说明书信息，包括适应症、剂量、禁忌和主要副作用。

    Args:
        drug_name: 药物通用名或商品名，如 "舍曲林" "帕罗西汀"
    """
    # 当前使用 mock 数据，后续可对接真实药物数据库
    mock_drugs = {
        "舍曲林": {
            "indication": "抑郁障碍、强迫症、惊恐障碍",
            "dosage": "起始 50mg/d，最大 200mg/d",
            "contraindications": "禁止与 MAOIs 联用",
            "side_effects": "恶心、腹泻、失眠、性功能障碍",
            "class": "SSRI",
        },
        "帕罗西汀": {
            "indication": "抑郁障碍、广泛性焦虑障碍、社交焦虑障碍",
            "dosage": "起始 20mg/d，最大 50mg/d",
            "contraindications": "禁止与 MAOIs 联用",
            "side_effects": "嗜睡、体重增加、性功能障碍、撤药综合征",
            "class": "SSRI",
        },
        "文拉法辛": {
            "indication": "抑郁障碍、广泛性焦虑障碍",
            "dosage": "起始 75mg/d，最大 225mg/d",
            "contraindications": "未控制的高血压",
            "side_effects": "恶心、失眠、血压升高、撤药综合征",
            "class": "SNRI",
        },
        "奥氮平": {
            "indication": "精神分裂症、双相躁狂发作",
            "dosage": "起始 5-10mg/d，最大 20mg/d",
            "contraindications": "窄角型青光眼",
            "side_effects": "体重增加、嗜睡、血糖升高、血脂异常",
            "class": "非典型抗精神病药",
        },
    }

    drug_lower = drug_name.strip().lower()
    for name, info in mock_drugs.items():
        if name in drug_lower or drug_lower in name:
            return json.dumps({"status": "success", "data": info}, ensure_ascii=False)

    return json.dumps({"status": "not_found", "message": f"未找到药物 '{drug_name}' 的说明书"}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
