# Clinical CDS 部署指南

本文档说明如何将 Clinical CDS 部署到生产环境：前端部署到 Cloudflare Pages，后端部署到 Railway。

## 架构

```
用户浏览器 → Cloudflare Pages (Vue 前端)
                  ↓ POST /api/chat
           Railway (FastAPI 后端)
                  ↓
       Redis + Milvus + Neo4j (Railway 附加服务)
```

---

## 一、Cloudflare Pages（前端）

### 方式 A：命令行直接上传

```powershell
cd front/clinical_cds

# 首次使用需登录（会弹出浏览器）
npx wrangler login

# 构建
npm run build

# 上传 dist 目录
npx wrangler pages deploy dist
```

部署后 Cloudflare 会分配域名：`https://<项目名>.pages.dev`

### 方式 B：Git 自动部署（推荐）

1. 打开 [Cloudflare Dashboard](https://dash.cloudflare.com)
2. 左侧菜单 → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**
3. 选择仓库 `xingdayup/PsyConsult`，点击 **Begin setup**
4. 构建配置：

| 字段 | 值 |
|------|-----|
| Production branch | `master` |
| Build command | `cd front/clinical_cds && npm install && npm run build` |
| Build output directory | `front/clinical_cds/dist` |

5. 点击 **Save and Deploy**

6. 部署完成后，进入 Settings → Environment Variables → 添加：

| Variable | Value |
|----------|-------|
| `VITE_API_BASE_URL` | `https://你的Railway域名.up.railway.app` |

7. 回到 **Deployments** → 点击最新的 deployment → **Retry deployment** 使变量生效。

---

## 二、Railway（后端）

### 1. 一键部署

项目根目录已包含 Railway 所需的文件：
- `Procfile` — 启动命令
- `requirements.txt` — Python 依赖

1. 打开 [Railway](https://railway.app) → **New Project** → **Deploy from GitHub**
2. 选择仓库 `xingdayup/PsyConsult`
3. Railway 会自动检测 `Procfile` 和 `requirements.txt` 并开始构建

### 2. 配置环境变量

在 Railway 项目的 **Variables** 标签页中添加：

```env
# LLM 配置（必填）
LLM_API_KEY=你的DeepSeek_API_Key
BASE_URL=https://api.deepseek.com/v1
MODEL=deepseek-v4-flash
DASHSCOPE_API_KEY=你的DashScope_API_Key

# Redis
REDIS_URL=redis://<Railway-Redis-Host>:6379
REDIS_TTL=1800

# Milvus
MILVUS_HOST=<Railway-Milvus-Host>
MILVUS_PORT=19530

# Neo4j
NEO4J_URI=bolt://<Railway-Neo4j-Host>:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<你的Neo4j密码>

# CORS（填前端域名）
CORS_ORIGINS=https://<你的站点>.pages.dev

# 安全（可选，设了前端就要带对应 Token）
API_AUTH_TOKEN=

# 日志
LOG_LEVEL=INFO
```

### 3. 添加基础服务

在 Railway 项目中点击 **+ New** 分别添加：

| 服务 | Railway 名称 | 说明 |
|------|-------------|------|
| Redis | **Add Redis** | 短期会话记忆 |
| 向量数据库 | 暂不支持 Milvus | 需用外部 Milvus 或替换为 pgvector |

> Milvus 不在 Railway Marketplace 中。两个替代方案：
> - 用 [Zilliz Cloud](https://zilliz.com)（托管的 Milvus，有免费额度）
> - 或在 Railway 上用 **PostgreSQL + pgvector** 替代（需要修改 `app/infra/cache.py` 和 `agent/core/memory/long_term.py`）

Neo4j 同样不在 Railway Marketplace，使用 [Neo4j AuraDB](https://neo4j.com/cloud/aura/) 免费版。

### 4. 获取服务连接信息

部署完成后，Railway 会分配域名：`https://<项目名>.up.railway.app`

此时后端聊天接口为：`POST https://<项目名>.up.railway.app/api/chat`

---

## 三、验证部署

```powershell
# 测试后端健康
curl https://<Railway域名>.up.railway.app/api/chat `
  -H "Content-Type: application/json" `
  -H "X-User-Id: doctor_001" `
  -d '{"query":"患者情绪低落失眠两周","session_id":"test"}'
```

打开前端 URL，输入患者症状，应看到流式多 Agent 响应。

---

## 四、GitHub 仓库地址

https://github.com/xingdayup/PsyConsult
