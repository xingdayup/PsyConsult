# 07. 部署与运维

## 模块解决的问题

这个项目的部署难点不是前端，而是后端和数据库。前端可以静态部署到 Cloudflare Pages；后端需要能公网访问，并且要连到 Redis、Milvus、Neo4j。

## 当前部署形态

```text
用户浏览器
  -> https://psyconsult.pages.dev
  -> 后端 API 地址
  -> FastAPI / uvicorn
  -> Redis / Milvus / Neo4j
```

前端：Cloudflare Pages。  
后端：可通过 Cloudflare Tunnel 暴露本地 `localhost:5002`，也可以部署到服务器。  
数据库：本地 Docker 或未来迁移到云服务。

## 前端 API 地址

核心文件：`front/clinical_cds/src/App.vue`

```ts
const buildApiBaseUrl = import.meta.env.VITE_API_BASE_URL || ''
const apiBaseUrl = ref(
  import.meta.env.DEV
    ? buildApiBaseUrl || 'http://127.0.0.1:5000'
    : buildApiBaseUrl && !isLocalApiBaseUrl(buildApiBaseUrl)
      ? buildApiBaseUrl
      : productionApiFallback,
)
```

面试讲法：  
线上踩过一个坑：Cloudflare Pages 的环境变量没有稳定进入前端运行逻辑，所以前端增加了本地地址过滤和生产兜底，避免生产环境打到用户自己的 `127.0.0.1`。

## CORS 排障

后端必须允许前端域名：

```env
CORS_ORIGINS=https://psyconsult.pages.dev,http://localhost:5173,http://127.0.0.1:5173
```

检查预检：

```powershell
curl.exe -i -X OPTIONS https://你的后端地址/api/chat `
  -H "Origin: https://psyconsult.pages.dev" `
  -H "Access-Control-Request-Method: POST" `
  -H "Access-Control-Request-Headers: content-type,x-user-id"
```

期望看到：

```text
access-control-allow-origin: https://psyconsult.pages.dev
```

## SSE 后端检查

```powershell
curl.exe -N https://你的后端地址/api/chat `
  -H "Content-Type: application/json" `
  -H "X-User-Id: doctor_001" `
  -d "{\"query\":\"短\",\"session_id\":\"deploy_smoke\"}"
```

期望看到：

```text
data: {"status": "accepted", ...}
data: {"agent": "input_validation", ...}
data: {"done": true}
```

## 线上故障定位顺序

1. 前端 JS 是否包含正确 API 地址。
2. `/api/config` 是否有运行时配置。
3. 后端 `POST /api/chat` 是否能 curl 通。
4. CORS `OPTIONS` 是否返回 200。
5. 后端日志是否有 `chat_request_start` 和 `sse_emit`。
6. Redis/Milvus/Neo4j 是否启动。

## 服务器取舍

2 核 2GB 服务器适合：

- FastAPI 后端。
- Nginx/Caddy 反代。
- systemd 守护。
- 小规模 Demo。

不适合：

- 同时跑 Milvus、Neo4j、Redis 和 Python Agent。
- 大并发或本地大模型。

面试讲法：  
我评估过上云方案，2C2G 可以作为固定 API 入口，但不适合承载完整数据库栈。如果要完整自建 Milvus 和 Neo4j，至少需要 4C8G，更稳是 4C16G。

## 面试 Q&A

**Q：线上为什么前端可访问但聊天失败？**  
A：前端是静态站点，能打开不代表后端可用。聊天失败通常是 API 地址错误、CORS 预检失败、Tunnel 断开或数据库不可用。

**Q：你怎么定位 CORS 问题？**  
A：用 `OPTIONS` 请求模拟浏览器预检。如果 POST curl 能通但 OPTIONS 400，就是后端 CORS 没放行前端域名或后端进程没有重启加载新配置。

**Q：为什么不直接把数据库放前端？**  
A：浏览器不能也不应该直连 Redis、Milvus、Neo4j。所有数据库访问必须经过后端，后端负责鉴权、查询和格式化。

## 截图建议

- 截 Cloudflare Pages 部署页面和环境变量。
- 截 `VITE_API_BASE_URL` 或生产兜底逻辑。
- 截 `curl -i -X OPTIONS` 的成功结果。
- 截后端日志里的 `chat_request_start`、`sse_emit`。

