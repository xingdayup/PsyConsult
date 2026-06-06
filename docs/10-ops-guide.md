# 后端运维指南

后端通过 cloudflared 隧道暴露到公网，架构如下：

```
用户浏览器 → Cloudflare CDN → cloudflared 隧道 → 你的电脑 uvicorn :5001
```

---

## 1. 启动

### 终端 1：启动后端

```powershell
cd E:\000WORK\项目1\clinical_cds
python -m uvicorn app.app_main:app --host 0.0.0.0 --port 5001
```

### 终端 2：启动隧道

```powershell
cloudflared tunnel --url http://localhost:5001
```

启动后隧道会输出公网地址，如 `https://xxx.trycloudflare.com`。

---

## 2. 停止

```powershell
# 关掉上面两个终端窗口即可
# 或者找到进程杀掉
tasklist | findstr "uvicorn\|cloudflared"
taskkill /PID <进程ID> /F
```

---

## 3. 注册为 Windows 服务（开机自启 + 崩溃重启）

### 安装 NSSM

```powershell
winget install nssm
```

### 注册后端服务

```powershell
nssm install ClinicalCDS-Backend "E:\000WORK\学习文档\cloud_agent\.venv\Scripts\python.exe" "-m uvicorn app.app_main:app --host 0.0.0.0 --port 5001"
nssm set ClinicalCDS-Backend AppDirectory "E:\000WORK\项目1\clinical_cds"
nssm set ClinicalCDS-Backend Start SERVICE_AUTO_START
nssm set ClinicalCDS-Backend AppStdout "E:\000WORK\项目1\clinical_cds\logs\service.log"
nssm set ClinicalCDS-Backend AppStderr "E:\000WORK\项目1\clinical_cds\logs\service_error.log"
nssm start ClinicalCDS-Backend
```

### 注册隧道服务

```powershell
nssm install ClinicalCDS-Tunnel "C:\Users\%USERNAME%\.cloudflared\cloudflared.exe" "tunnel --url http://localhost:5001"
nssm set ClinicalCDS-Tunnel Start SERVICE_AUTO_START
nssm start ClinicalCDS-Tunnel
```

### 服务管理命令

```powershell
nssm status ClinicalCDS-Backend     # 查看状态
nssm restart ClinicalCDS-Backend    # 重启
nssm stop ClinicalCDS-Backend       # 停止
nssm remove ClinicalCDS-Backend confirm  # 删除服务
```

---

## 4. 日志

| 日志 | 路径 | 说明 |
|------|------|------|
| 后端应用 | `logs/backend.log` | RotatingFileHandler，5MB 轮转，保留 5 个 |
| 后端服务 | `logs/service.log` | NSSM 注册后才产生 |
| 隧道日志 | NSSM 捕获到 Windows 事件查看器 | `eventvwr.msc` → Windows 日志 → 应用程序 |

### 实时查看

```powershell
Get-Content logs/backend.log -Tail 30 -Wait
```

### 关键日志事件

```text
event=agent_system_init step=complete     # 启动成功
event=sse_emit kind=status                # 状态变更
event=agent_update node=xxx               # Agent 节点完成
event=chat_step step=sse_complete         # 请求完成
```

---

## 5. 更新代码

```powershell
cd E:\000WORK\项目1\clinical_cds
git pull origin master
pip install -r requirements.txt
# 如果装了 NSSM 服务：
nssm restart ClinicalCDS-Backend
# 否则重新运行 uvicorn
```

---

## 6. 健康检查

```powershell
# 本地
curl http://127.0.0.1:5001/api/chat -H "Content-Type: application/json" -H "X-User-Id: doctor_001" -d '{"query":"测试","session_id":"1"}'

# 公网（替换为实际隧道地址）
curl https://xxx.trycloudflare.com/api/chat -H "Content-Type: application/json" -H "X-User-Id: doctor_001" -d '{"query":"测试","session_id":"1"}'
```

---

## 7. 隧道 URL 固定

快速隧道每次重启 URL 会变。要固定，需要：

1. 在 Cloudflare 绑定一个自有域名（几块钱/年）
2. 创建 named tunnel：
   ```powershell
   cloudflared tunnel login
   cloudflared tunnel create psyconsult
   cloudflared tunnel route dns psyconsult api.你的域名.com
   cloudflared tunnel run --url http://localhost:5001 psyconsult
   ```
3. 隧道 URL 变为 `https://api.你的域名.com`，重启不变

---

## 8. 故障排查

| 症状 | 检查 |
|------|------|
| 前端 401 | `API_AUTH_TOKEN` 和前端 `VITE_API_AUTH_TOKEN` 不一致 |
| 后端起不来 | `agent/.env` 里的 API Key 是否有效 |
| 隧道不通 | `netstat -ano \| findstr ":5001"` 确认 uvicorn 在跑 |
| Milvus/Neo4j 不可用 | `docker compose -f docker/docker-compose.yml ps` 检查容器 |
| 端口被占 | `netstat -ano \| findstr ":5001"` 找 PID 然后 `taskkill /PID xxx /F` |
