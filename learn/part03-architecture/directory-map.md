# 10｜目录地图：把仓库当成一栋门诊楼

## 学习目标

看到需求或故障时，能先进入正确目录，而不是在整个仓库搜索碰运气；同时识别容易混淆的测试、配置与扩展代码。

## 生活类比：楼层指示牌

门诊楼的指示牌不会介绍每台设备，只告诉你挂号处、诊室、档案室在哪里。目录地图也一样：先确定职责区域，再进入房间看具体文件。本页不做文件百科。

## 图解

### 先画人话图

```text
门诊大厅
├─ 医生工作台区
├─ 接待窗口区
├─ 专家诊室区
│  ├─ 协调室
│  ├─ 诊断室
│  ├─ 治疗室
│  └─ 药审室
├─ 资料设施区
├─ 模拟病例库
└─ 学习手册区
```

### 再给技术图

```text
PsyConsult/
├─ front/clinical_cds/       # 医生工作台
├─ app/                      # 接待窗口与流式服务
│  ├─ router/                # HTTP 入口
│  ├─ schemas/               # 外部输入形状
│  ├─ service/               # 请求编排
│  ├─ infra/                 # 缓存、日志
│  └─ test/                  # pytest 主测试
├─ agent/                    # 专家组
│  ├─ agents/                # 协调、诊断、治疗、药审
│  ├─ core/workflow/         # 状态图、Checkpoint、压缩
│  ├─ core/memory/           # 长期事实
│  ├─ core/graph/            # 图谱接入
│  ├─ core/mcp/              # MCP 管理器（未接主图）
│  ├─ tools/                 # 领域工具
│  ├─ mcp_servers/           # MCP 示例服务（未接主图）
│  └─ test/                  # 手工实验脚本
├─ docker/                   # 本地资料服务
├─ mock_data/                # 虚构材料
└─ learn/                    # 学习文档
```

## 分步骤体验

用四类任务练习定位：

1. API 缺少身份头：先去 `app/router/`；
2. 诊断后没有进入治疗：先去 `agent/core/workflow/`；
3. 指南检索没有结果：先看 `agent/tools/`、Milvus 和 `mock_data/`；
4. 页面不逐段更新：先看 `front/clinical_cds/`，再沿响应追到 `app/service/`。

定位顺序是“职责目录 → 入口文件 → 调用关系”，不要先阅读所有文件。

## 项目真实实现

几个必须记住的目录事实：

- pytest 主套件位于 [`app/test/`](../../app/test/)，根目录 [`pytest.ini`](../../pytest.ini) 指向这里；
- [`agent/test/`](../../agent/test/) 多为会调用外部服务的手工脚本，不应当作离线单元测试套件；
- [`agent/config/settings.py`](../../agent/config/settings.py) 与 [`app/app_config/settings.py`](../../app/app_config/settings.py) 是两个 Settings 类；
- [`agent/core/mcp/`](../../agent/core/mcp/) 虽有 `MCPManager`，但聊天服务和主图没有实例化它；
- 前端主要交互目前集中在 [`front/clinical_cds/src/App.vue`](../../front/clinical_cds/src/App.vue)。

## 源码二刷

二刷时用“入口—核心—出口”三点法：

| 区域 | 入口 | 核心 | 出口 |
|---|---|---|---|
| API | `app_main.py` | `chat_service.py` | SSE `data:` |
| Agent | `main.py` / 图调用 | `graph_manager.py`、`agents/` | 状态更新 |
| 工作台 | `main.ts` | `App.vue` 的 `sendQuery` | 页面消息 |

只会 Python 时，先精读 API 与 Agent；前端只追请求和流读取函数。

## 面试背板

> 仓库按 UI、API、Agent 和基础设施分区。测试也有明确边界：`app/test` 是 pytest 主套件，`agent/test` 是外部服务实验脚本。配置有两个独立 Settings。MCP 代码位于 core 和示例服务目录，但主图未引用，因此我会把它描述为扩展预留而非当前能力。

## 常见问题

**为什么有两个测试目录？** 它们用途不同，一个是自动化主套件，一个是手工/集成实验。

**为什么有两个 Settings？** Agent 与 API 读取的字段和职责不同，当前设计不应随意合并。

**看到 MCP 文件就能说项目用了 MCP 吗？** 不能。必须检查主入口是否实例化、连接并把工具注册进图。

## 自测

1. 修改身份校验应先看哪个目录？
2. 自动化 pytest 与手工 Agent 脚本分别在哪里？
3. 如何证明 MCP 没接主图？
4. 只会 Python 时，前端先读哪个函数？

## 导航

- 上一页：[请求流](request-flow.md)
- 下一页：[设计取舍](design-tradeoffs.md)
- 返回：[Part 03 入口](index.md)
