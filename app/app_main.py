import sys
import os

# 将 agent 目录加入 sys.path
AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.app_config.settings import settings
from app.router import chat
from app.service.chat_service import init_agent_system

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    await init_agent_system()
    yield
    # 关闭时清理
    pass

app = FastAPI(title="Clinical Decision Support System API", lifespan=lifespan)

# 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat.router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.app_main:app", host="0.0.0.0", port=5000, reload=True)
