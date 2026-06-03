
import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


class MCPManager:
    """MCP 服务器连接和工具发现的管理器。
    
    该类处理：
    - 加载 MCP 服务器配置
    - 建立与多个 MCP 服务器的连接
    - 从所有服务器发现和聚合工具
    - 资源清理
    
    示例：
        manager = MCPManager("config/mcp_servers.json")
        await manager.connect()
        tools = await manager.get_tools()
        # 与 agent 一起使用工具
        await manager.close()
    """
    
    def __init__(self, config_path: str | Path) -> None:
        """使用配置初始化 MCP 管理器。
        
        参数：
            config_path: MCP 服务器配置 JSON 文件的路径。
        """
        self.config_path = Path(config_path)
        self._client: MultiServerMCPClient | None = None
        self._tools: list[BaseTool] | None = None
        self._servers_config: dict[str, Any] | None = None
    
    def _load_config(self) -> dict[str, Any]:
        """从 JSON 文件加载 MCP 服务器配置。

        返回：
            包含 mcpServers 配置的字典。

        引发：
            FileNotFoundError: 如果配置文件不存在。
            json.JSONDecodeError: 如果配置文件是无效的 JSON。
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"MCP config not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        self._servers_config = config.get("mcpServers", {})
        logger.info("Loaded %d MCP server configs", len(self._servers_config))
        return self._servers_config

    async def connect(self) -> None:
        """连接到所有配置的 MCP 服务器。

        加载配置并建立连接。
        自动发现工具。
        """
        if self._client is not None:
            logger.warning("MCPManager already connected")
            return

        servers_config = self._load_config()

        if not servers_config:
            logger.warning("No MCP servers configured")
            return

        self._client = MultiServerMCPClient(servers_config)
        self._tools = await self._client.get_tools()
        logger.info("Discovered %d tools from MCP servers", len(self._tools))

        for tool in self._tools:
            logger.debug("  - %s: %s", tool.name, tool.description)

    async def close(self) -> None:
        """关闭所有 MCP 连接并清理资源。

        注意：MultiServerMCPClient v0.1.0+ 管理其自身的生命周期；
        不需要显式调用 close。
        """
        if self._client is not None:
            self._client = None
            self._tools = None
            logger.info("MCP connections cleaned up")

    async def get_tools(self) -> list[BaseTool]:
        """返回已连接的 MCP 服务器中的所有工具。

        返回：
            LangChain BaseTool 对象的列表。

        引发：
            RuntimeError: 如果尚未调用 ``connect()``。
        """
        if self._tools is None:
            raise RuntimeError(
                "MCPManager is not connected. Call connect() before get_tools()."
            )
        return self._tools

    def get_tool_names(self) -> list[str]:
        """返回所有可用工具的名称。

        返回：
            工具名称字符串的列表。

        引发：
            RuntimeError: 如果尚未调用 ``connect()``。
        """
        if self._tools is None:
            raise RuntimeError("MCPManager is not connected. Call connect() first.")
        return [tool.name for tool in self._tools]

    def get_server_names(self) -> list[str]:
        """返回已配置的 MCP 服务器名称。

        返回：
            来自配置的服务器名称字符串列表。
        """
        if self._servers_config is None:
            self._load_config()
        return list(self._servers_config.keys()) if self._servers_config else []
