import asyncio
import sys
import os

# 确保能正确导入 app 模块
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.append(PROJECT_DIR)

from infra.cache import semantic_cache

# 预设的临床 QA 列表 (高频标准诊疗问题)
PRESET_QA = [
    {
        "query": "抑郁发作的 ICD-11 诊断标准是什么？",
        "response": "### 抑郁发作 ICD-11 诊断标准 (6A70)\n\n**核心症状（至少 2 条，持续 ≥2 周）**：\n1. 抑郁心境（情绪低落）\n2. 兴趣或快感减退\n3. 精力减退或疲乏\n\n**附加症状（核心+附加需 ≥5 条）**：\n4. 注意力减退\n5. 自我评价低或自责自罪\n6. 无望感\n7. 睡眠障碍\n8. 食欲改变伴体重变化\n9. 精神运动性改变\n10. 自杀观念或行为"
    },
    {
        "query": "舍曲林的常用剂量和副作用是什么？",
        "response": "### 舍曲林 (Sertraline) - SSRI 类\n\n**剂量**：起始 50mg/d，最大 200mg/d\n**适应症**：抑郁障碍、强迫症、惊恐障碍\n**常见副作用**：恶心、腹泻、失眠、性功能障碍\n**禁忌**：禁止与 MAOIs 联用（需 14 天洗脱期）"
    },
    {
        "query": "PHQ-9 评分怎么分级？",
        "response": "### PHQ-9 严重度分级\n\n- 0-4 分：无抑郁\n- 5-9 分：轻度\n- 10-14 分：中度\n- 15-19 分：中重度\n- 20-27 分：重度\n\n共 9 个条目，每项 0-3 分，总分 0-27。"
    },
    {
        "query": "SSRI 和 SNRI 有什么区别？",
        "response": "### SSRI vs SNRI\n\n**SSRI**（选择性 5-HT 再摄取抑制剂）：舍曲林、帕罗西汀、氟西汀。主要作用于 5-HT 系统。\n\n**SNRI**（5-HT 和 NE 再摄取抑制剂）：文拉法辛、度洛西汀。同时作用于 5-HT 和 NE 系统，对疼痛症状可能更有效。\n\n两者均为抑郁障碍一线药物，选择取决于患者具体症状和耐受性。"
    }
]

async def preload_cache():
    print("🔄 开始预热 L1 语义缓存...")
    await semantic_cache.initialize()
    
    for item in PRESET_QA:
        query = item["query"]
        response = item["response"]
        print(f"注入缓存 -> Query: '{query}'")
        
        # 调用 set_cache 将问题向量化并写入 Milvus 语义缓存集合
        await semantic_cache.set_cache(query, response)
        
    print("✅ 缓存预热完成！")

if __name__ == "__main__":
    asyncio.run(preload_cache())
