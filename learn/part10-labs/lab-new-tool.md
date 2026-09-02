# Lab 1｜新增一个确定性工具，并真正接进主链路

本实验新增“明确安全风险词提示”工具作为工程练习。它只识别文本里明确出现的词，输出结构化升级提示；它不是风险量表、不是诊断器，也未经过临床验证。重点不是词表，而是工具从测试到 Agent 可达的完整证据链。

## 学习目标

- 先写纯逻辑和注册测试，再写实现；
- 把确定性规则与 LLM 解释分开；
- 验证工具加入 `DiagnosisAgentNode.tools`；
- 运行回归与 import 检查；
- 设计只撤销本实验改动的回滚路径。

## 类比：新设备不能只放进仓库

设备本体对应工具函数，设备接口对应 LangChain `@tool`，科室设备清单对应 `self.tools`，医生何时使用对应 system prompt，从接待入口跑通则对应集成测试。缺一项都可能让功能不可达。

## 图：四层证据

```mermaid
flowchart LR
  P[纯函数规则] --> T[@tool 契约]
  T --> R[Agent 注册]
  R --> G[图/API 可达]
  P -.单测.-> E[证据]
  T -.契约测.-> E
  R -.注册测.-> E
  G -.回归/冒烟.-> E
```

## 真实实现

> 以下是待你在实验分支实施的方案，不是当前仓库已有能力。

### 0. 确认基线

**目的：记录改动前后端测试与语法状态，避免把旧故障算到新工具。**

```powershell
python -m pytest -q
python -m compileall -q agent app
```

**目的：确认工作区已有改动，后续只回滚自己的实验文件。**

```powershell
git status --short
```

### 1. RED：先写行为测试

计划新增 `app/test/test_safety_tool.py`。先定义一个不依赖模型的纯函数 `_assess(text)`：

```python
def test_assess_detects_explicit_signal():
    result = _assess("患者明确说准备服用大量药物伤害自己")
    assert result["risk"] == "urgent"
    assert result["requires_human_assessment"] is True
    assert result["matched_signals"]


def test_assess_does_not_label_common_insomnia_as_urgent():
    result = _assess("患者近两周入睡困难")
    assert result["risk"] == "not_detected"
```

再定义注册测试，mock `ChatOpenAI` 和 `create_react_agent`，避免联网：

```python
def test_diagnosis_agent_registers_safety_tool(monkeypatch):
    # 先替换 Agent 构造中的模型和 ReAct 工厂
    node = DiagnosisAgentNode()
    assert "assess_safety_red_flags" in {tool.name for tool in node.tools}
```

**目的：确认测试是因模块/功能不存在而红，而不是环境或语法问题。**

```powershell
python -m pytest -q app/test/test_safety_tool.py
```

### 2. GREEN：最小工具

计划新增 `agent/tools/safety_tool.py`：

```python
import json
from langchain_core.tools import tool

URGENT_SIGNALS = ("结束生命", "自杀计划", "服用大量药物", "伤害他人")


def _assess(text: str) -> dict:
    matched = [s for s in URGENT_SIGNALS if s in text]
    return {
        "risk": "urgent" if matched else "not_detected",
        "matched_signals": matched,
        "requires_human_assessment": bool(matched),
        "notice": "仅提示明确文本线索，不替代专业风险评估。",
    }


@tool
def assess_safety_red_flags(text: str) -> str:
    """识别文本中明确陈述的紧急安全线索。"""
    return json.dumps(_assess(text), ensure_ascii=False)
```

限制必须写清：未命中只表示词表没检测到，不能输出“安全”；命中也不是诊断结论，只能升级人工评估。

### 3. 小步接 Agent

在 `diagnosis_agent.py` 导入并加入：

```python
self.tools = [
    query_synonyms,
    query_knowledge_graph,
    query_vector_db,
    assess_safety_red_flags,
]
```

随后只做最小 prompt 补充：有明确安全线索时调用工具并提示人工升级；不得自动下医嘱或声称完成风险评估。不要为了一个工具同时改路由、状态、前端和存储。

### 4. 验证

**目的：先验证本实验的行为、负例和 Agent 注册。**

```powershell
python -m pytest -q app/test/test_safety_tool.py
```

**目的：确认新增 import 与 Python 语法可加载。**

```powershell
python -m compileall -q agent app
python -c "import app.app_main; print('ok')"
```

**目的：检查没有破坏既有安全、SSE 和日志契约。**

```powershell
python -m pytest -q
```

**目的：审查实验只触及计划文件，且没有空白错误。**

```powershell
git diff --check
git diff -- agent/tools/safety_tool.py agent/agents/diagnosis_agent.py app/test/test_safety_tool.py
```

### 5. 可回滚

最稳妥做法是把“测试+工具+注册”做成一个独立提交，需要撤销时 `git revert <commit>`。若尚未提交，只恢复你本实验确认过的文件；不要运行 `reset --hard`。新增文件与 Agent import 必须成对撤销，否则会留下导入错误。

## 源码二刷

从 `DiagnosisAgentNode.__call__()` 看 `inner_agent` 使用的是构造时传入的 `self.tools`，确认工具不是只 import。再看 custom stream：工具调用名如何变成 `agent_tool_call` SSE。最后从 `/api/chat` 逆向确认诊断路由可到这个节点，但不要把“模型可能选择工具”写成确定每次都会调用。

## 面试背板

> 我新增工具时先把确定性规则抽成纯函数，写正反例；再测 Tool 契约与 Agent 注册，避免孤立代码。实现只提示明确文本线索，不把未命中当安全，也不替代临床评估。接入后跑 import、全量 pytest 和 diff 检查，并用独立提交保证整体回滚。

## 常见误解

- **“关键词工具能完成自伤风险评估。”** 它只能提示明确文本词，能力非常有限。
- **“注册后每次必调用。”** ReAct 是否调用仍由模型决策。
- **“只测命中即可。”** 负例能保护最低限度误报边界。
- **“改 prompt 等于实现工具。”** 确定性行为需要代码和契约。
- **“回滚只删工具文件。”** Agent import 与测试也必须一致处理。

## 自测

1. 为什么先测 `_assess`，再测 `@tool`？
2. 如何离线实例化 `DiagnosisAgentNode` 而不调用真实 LLM？
3. 这个实验可以声称什么，绝不能声称什么？
4. 哪个测试能发现工具没有注册？
5. 回滚最小文件集合是什么？

## 导航

- [实战总览](./index.md)
- [下一实验：MCP 接入 Agent](./lab-mcp-agent.md)
- [安全门禁](../part09-security-troubleshooting/security-gates.md)
