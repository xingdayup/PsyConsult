# 04｜环境准备：先检查钥匙，再开门

## 学习目标

在 Windows PowerShell 中准备 Python 3.12、项目依赖、`agent/.env` 和本地资料服务；每条命令执行前都知道用途，执行后都知道预期现象。

## 生活类比：开门前的设备清单

门诊试营业前，要确认电源、电话、档案柜和门锁。开发环境也是如此：Python 是工作人员，依赖包是工具，`.env` 是钥匙串，Redis/Milvus/Neo4j 是不同资料柜。

## 图解

```text
Python 3.12 ──运行代码
agent/.env ──提供模型钥匙和连接地址
Docker ─────启动资料服务
  ├─ Redis：会话记录
  ├─ Milvus：相似资料
  └─ Neo4j：关系资料
```

## 分步骤体验

### 第 1 步：检查工具

**用途：** 确认当前终端能找到正确的软件。  
**预期：** Python 显示 3.12；Docker 与 Compose 返回版本号，不出现“找不到命令”。

```powershell
python --version
docker --version
docker compose version
```

### 第 2 步：创建独立 Python 环境

**用途：** 避免项目依赖污染系统 Python，并安装后端所需包。  
**预期：** 激活后命令行前出现 `(.venv)`；安装完成无红色错误。

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r agent\requirements.txt
```

### 第 3 步：创建本地配置

在 `agent/.env` 至少写入自己的模型密钥；不要使用下面的占位符真正调用，也不要提交文件：

```dotenv
DASHSCOPE_API_KEY=replace-with-your-own-key
REDIS_URL=redis://localhost:6379
MILVUS_HOST=localhost
MILVUS_PORT=19530
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123
# 配置此项后，API 才会强制 Bearer
API_AUTH_TOKEN=local-dev-token
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

**用途：** 检查配置文件没有被 Git 跟踪。  
**预期：** 命令无输出；若显示 `agent/.env`，立即停止并检查 `.gitignore`。

```powershell
git status --short -- agent/.env
```

### 第 4 步：启动资料服务

**用途：** 启动会话、向量资料和关系资料服务。  
**预期：** `docker compose ps` 中 Redis、Milvus、Neo4j 为运行状态；MySQL 也会启动，但当前聊天主链路不使用它。

```powershell
Set-Location docker
docker compose up -d
docker compose ps
Set-Location ..
```

### 第 5 步：做语法体检

**用途：** 在真正调用模型前发现 Python 语法错误。  
**预期：** 命令安静退出，返回码为 0。

```powershell
python -m compileall -q agent app
```

## 项目真实实现

配置定义见 [`agent/config/settings.py`](../../agent/config/settings.py) 和 [`app/app_config/settings.py`](../../app/app_config/settings.py)。它们是两个职责不同的 Settings 类，不要因为字段相似就合并。

[`docker/docker-compose.yml`](../../docker/docker-compose.yml) 当前启动 Redis Stack、Milvus、Neo4j 与 MySQL。Redis/Milvus 连接失败时，Checkpoint、缓存与长期记忆按设计跳过或退化；这不代表资料缺失对输出没有影响。

## 源码二刷

重点看默认值而不是背全部环境变量：

- [`agent/config/settings.py`](../../agent/config/settings.py)：模型和资料服务；
- [`app/app_config/settings.py`](../../app/app_config/settings.py)：API Token、跨域和缓存开关；
- [`agent/core/workflow/checkpointer.py`](../../agent/core/workflow/checkpointer.py)：Redis 不可用时为何返回 `None`；
- [`docker/docker-compose.yml`](../../docker/docker-compose.yml)：本地端口与镜像版本。

## 面试背板

> 项目把密钥放在不提交的 `agent/.env`，本地基础服务通过 Compose 启动。Redis/Milvus 不可用时相关能力优雅降级，避免单个外部依赖阻断单轮推理；但会话连续性和资料质量会受影响。开发前先做版本、配置、容器和语法四层检查。

## 常见问题

**为什么不用仓库文档中的旧绝对虚拟环境路径？** 那是其他机器路径，本机应新建 `.venv`。

**普通 Redis 可以吗？** Checkpoint 依赖 Redis Stack 提供的能力，按 Compose 中的镜像运行最稳妥。

**`API_AUTH_TOKEN` 必填吗？** 不是；非空时才强制 Bearer。但 `X-User-Id` 在 API 请求中始终必填。

## 自测

1. `.env`、Redis、Milvus、Neo4j 各扮演什么角色？
2. Redis 失败后哪项体验最明显受损？
3. 每组环境命令的预期结果是什么？

## 导航

- 上一页：[Part 02 入口](index.md)
- 下一页：[第一次 CLI](first-cli.md)
- 深入排障：[`learn/11-pitfalls/`](../11-pitfalls/README.md)
