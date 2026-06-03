"""用于数据库操作的 Neo4j 客户端。"""

import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from config import get_settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """用于知识图谱操作的异步 Neo4j 客户端。
    
    示例：
        client = Neo4jClient()
        await client.connect()
        
        # 执行查询
        result = await client.execute_query(
            "MATCH (n:Product) RETURN n.id, n.name"
        )
        
        await client.close()
    """
    
    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        """初始化 Neo4j 客户端。
        
        参数：
            uri: Neo4j Bolt URI。如果为 None，则使用 settings.neo4j_uri。
            user: Neo4j 用户名。如果为 None，则使用 settings.neo4j_user。
            password: Neo4j 密码。如果为 None，则使用 settings.neo4j_password。
            database: 数据库名称。如果为 None，则使用 settings.neo4j_database。
        """
        settings = get_settings()
        self.uri = uri or settings.neo4j_uri
        self.user = user or settings.neo4j_user
        self.password = password or settings.neo4j_password
        self.database = database or settings.neo4j_database
        
        self._driver: AsyncDriver | None = None
    
    async def connect(self) -> None:
        """建立到 Neo4j 的连接。"""
        self._driver = AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password)
        )
        await self._driver.verify_connectivity()
        logger.info("Connected to Neo4j at %s", self.uri)
    
    async def close(self) -> None:
        """关闭 Neo4j 连接。"""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")
    
    async def execute_query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """执行 Cypher 查询。
        
        参数：
            query: Cypher 查询字符串。
            parameters: 查询参数。
            
        返回：
            作为字典列表的结果记录。
            
        引发：
            RuntimeError: 如果未连接到 Neo4j。
        """
        if not self._driver:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")
        
        async with self._driver.session(database=self.database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records
    
    async def create_constraints(self) -> None:
        """为实体 ID 创建唯一性约束。"""
        constraints = [
            ("Disease", "id"),
            ("Symptom", "id"),
            ("Drug", "id"),
            ("SideEffect", "id"),
            ("Treatment", "id"),
        ]
        
        for label, property_name in constraints:
            query = (
                f"CREATE CONSTRAINT {label.lower()}_{property_name} "
                f"IF NOT EXISTS FOR (n:{label}) "
                f"REQUIRE n.{property_name} IS UNIQUE"
            )
            try:
                await self.execute_query(query)
                logger.debug("Created constraint for %s.%s", label, property_name)
            except Exception as e:
                logger.warning("Constraint creation skipped for %s: %s", label, e)
        
        logger.info("Neo4j constraints created/verified")
    
    async def clear_database(self) -> None:
        """清除所有节点和关系。谨慎使用！"""
        query = "MATCH (n) DETACH DELETE n"
        await self.execute_query(query)
        logger.warning("All nodes and relationships deleted from Neo4j")
    
    async def get_stats(self) -> dict[str, int]:
        """获取数据库统计信息。
        
        返回：
            包含节点和关系计数的字典。
        """
        stats = {}
        
        # 按标签统计节点数
        node_query = """
        MATCH (n)
        RETURN labels(n)[0] as label, count(n) as count
        """
        node_results = await self.execute_query(node_query)
        for record in node_results:
            stats[f"nodes_{record['label']}"] = record["count"]
        
        # 按类型统计关系数
        rel_query = """
        MATCH ()-[r]->()
        RETURN type(r) as type, count(r) as count
        """
        rel_results = await self.execute_query(rel_query)
        for record in rel_results:
            stats[f"rels_{record['type']}"] = record["count"]
        
        return stats
