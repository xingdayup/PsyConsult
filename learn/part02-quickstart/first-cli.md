# 05｜第一次 CLI：直接敲专家组的门

## 学习目标

不经过接待窗口和医生工作台，直接从命令行提交一个虚构病例，验证专家组、模型与资料能力是否能够工作。

## 生活类比：内部试诊

门诊开放前，工作人员会拿一份虚构病例直接请专家讨论。没有前台、没有网页，若此时失败，问题大概率就在专家排班、模型钥匙或资料柜，而不是展示界面。

## 图解

```text
PowerShell
   │ 虚构病例 + user + session
   ▼
专家组入口
   ├─ 判断从哪一步开始
   ├─ 领域分析
   └─ 查询可用资料
   ▼
终端打印完整结果
```

## 分步骤体验

先确认已完成环境页并激活 `.venv`。

**用途：** 进入专家组目录，提交一次虚构病例。  
**预期：** 终端显示用户问题，随后打印 AI 结果；还会显示会话状态或资料能力是否可用。

```powershell
Set-Location agent
python main.py --query "虚构病例：患者近两周情绪低落、失眠、兴趣下降。请列出需补充的信息和鉴别方向。" --user doctor_demo --session demo_cli_001
```

保持相同 `--user` 和 `--session` 再问一轮。

**用途：** 验证 Redis 可用时同一会话能延续上下文。  
**预期：** 系统能结合上一轮病例回答；若日志提示 Checkpoint 关闭，则会按无状态方式运行。

```powershell
python main.py --query "补充：既往无躁狂或轻躁狂史。还缺哪些安全风险信息？" --user doctor_demo --session demo_cli_001
Set-Location ..
```

不要用真实病例，也不要为了“更真实”加入身份信息。

## 项目真实实现

[`agent/main.py`](../../agent/main.py) 接收：

- `--query`：本轮问题；
- `--user`：用户标识；
- `--session`：会话标识，并作为 Checkpoint 的 `thread_id`。

CLI 每轮只提交新的 `HumanMessage`。Redis Checkpoint 可用时，历史由图恢复；图入口会先经过历史压缩节点。消息超过 16 条才触发压缩，旧消息被摘要，最近 8 条保留。Redis 不可用时，图从协调者直接开始并退化为无状态。

## 源码二刷

二刷 [`agent/main.py`](../../agent/main.py) 时只追四个变量：`args.query`、`user_id`、`session_id`、`state`。然后跳到：

1. [`agent/core/workflow/state.py`](../../agent/core/workflow/state.py)：状态字典有哪些键；
2. [`agent/core/workflow/checkpointer.py`](../../agent/core/workflow/checkpointer.py)：会话如何保存；
3. [`agent/core/workflow/graph_manager.py`](../../agent/core/workflow/graph_manager.py)：入口和节点如何连接。

把它们理解为 Python 字典、异步函数和流程图即可。

## 面试背板

> 我先用 CLI 验证核心推理层，把页面和 HTTP 排除在外。CLI 将 `session_id` 作为 Checkpoint 的 `thread_id`；Redis 可用时相同会话恢复历史并经过压缩入口，不可用时退化为无状态单轮执行。这种验证顺序能快速缩小故障范围。

## 常见问题

**终端等待很久是死机吗？** 不一定，模型和资料查询都有网络时延。结合日志判断是否仍在运行。

**第二轮没记住第一轮怎么办？** 检查 Redis Stack 是否运行、两次 `--session` 是否完全一致以及 Checkpoint 日志。

**CLI 为什么不像网页那样逐字显示？** 当前单次 CLI 主要等待完整图结果；流式展示由 API 和工作台负责。

## 自测

1. CLI 验证时绕过了哪两层？
2. `--session` 在内部变成什么？
3. Redis 不可用时图入口有何变化？
4. 什么时候触发历史压缩？

## 导航

- 上一页：[环境准备](environment.md)
- 下一页：[第一次 API](first-api.md)
- 相关源码：[`agent/main.py`](../../agent/main.py)
