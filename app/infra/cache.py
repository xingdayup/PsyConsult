from __future__ import annotations

from typing import Any

from app_config.settings import settings

COLLECTION_NAME = "qa_semantic_cache"
EMBEDDING_DIM = 1536
L1_SEMANTIC_DISTANCE_THRESHOLD = 0.08
MIN_SEMANTIC_CACHE_QUERY_LENGTH = 4


class SemanticCache:
    def __init__(self) -> None:
        self._client: Any = None
        self._embeddings: Any = None
        self._available: bool = False

    async def initialize(self) -> None:
        try:
            from pymilvus import MilvusClient
            from langchain_community.embeddings import DashScopeEmbeddings

            embedding_api_key = self._get_embedding_api_key()
            if not settings.enable_semantic_cache:
                print("SemanticCache disabled: ENABLE_SEMANTIC_CACHE=false")
                self._available = False
                return
            if not embedding_api_key:
                print(
                    "SemanticCache disabled: no DashScope embedding key. "
                    "Set DASHSCOPE_EMBEDDING_API_KEY or EMBEDDING_API_KEY to enable it."
                )
                self._available = False
                return

            connect_kwargs: dict[str, Any] = {
                "uri": f"http://{settings.milvus_host}:{settings.milvus_port}"
            }
            if settings.milvus_api_key:
                connect_kwargs["token"] = settings.milvus_api_key

            self._client = MilvusClient(**connect_kwargs)
            self._embeddings = DashScopeEmbeddings(
                model="text-embedding-v2",
                dashscope_api_key=embedding_api_key,
            )
            self._ensure_collection()
            self._available = True
        except Exception as exc:
            print(f"SemanticCache init failed: {exc}")
            self._available = False

    async def set_cache(
        self,
        query: str,
        response: str,
        user_id: str | None = None,
        scope: str = "public",
    ) -> None:
        if not self._available:
            return
        normalized = self._normalize(query)
        owner = user_id or ""
        cache_scope = "user" if owner else scope
        try:
            embedding = await self._embeddings.aembed_query(normalized)
            safe_norm = normalized.replace('"', '\\"')
            safe_scope = cache_scope.replace('"', '\\"')
            safe_owner = owner.replace('"', '\\"')
            delete_filter = (
                f'question_norm == "{safe_norm}" and scope == "{safe_scope}" and user_id == "{safe_owner}"'
            )
            self._client.delete(collection_name=COLLECTION_NAME, filter=delete_filter)
            self._client.insert(
                collection_name=COLLECTION_NAME,
                data=[
                    {
                        "question": query.strip(),
                        "question_norm": normalized,
                        "answer": response,
                        "scope": cache_scope,
                        "user_id": owner,
                        "enabled": 1,
                        "embedding": embedding,
                    }
                ],
            )
        except Exception as exc:
            print(f"SemanticCache set_cache failed: {exc}")

    async def get_cache(self, query: str, user_id: str) -> dict[str, Any] | None:
        if not self._available:
            return None
        normalized = self._normalize(query)
        safe_norm = normalized.replace('"', '\\"')
        safe_user = user_id.replace('"', '\\"')

        user_filter = (
            f'enabled == 1 and question_norm == "{safe_norm}" and scope == "user" and user_id == "{safe_user}"'
        )
        public_filter = (
            f'enabled == 1 and question_norm == "{safe_norm}" and scope == "public"'
        )
        user_exact = self._query_one(user_filter)
        if user_exact:
            return {
                "answer": user_exact["answer"],
                "matched_question": user_exact["question"],
                "level": "L1_EXACT",
                "distance": 0.0,
            }

        public_exact = self._query_one(public_filter)
        if public_exact:
            return {
                "answer": public_exact["answer"],
                "matched_question": public_exact["question"],
                "level": "L1_EXACT",
                "distance": 0.0,
            }

        if len("".join(normalized.split())) < MIN_SEMANTIC_CACHE_QUERY_LENGTH:
            return None

        try:
            query_embedding = await self._embeddings.aembed_query(normalized)
            scoped_filter = (
                f'enabled == 1 and (scope == "public" or (scope == "user" and user_id == "{safe_user}"))'
            )
            results = self._client.search(
                collection_name=COLLECTION_NAME,
                data=[query_embedding],
                filter=scoped_filter,
                limit=1,
                output_fields=["question", "answer", "scope", "user_id"],
            )
            if not results:
                return None
            hit = results[0][0] if results[0] else None
            if not hit:
                return None
            distance = float(hit.get("distance", 1.0))
            if distance > L1_SEMANTIC_DISTANCE_THRESHOLD:
                return None
            entity = hit.get("entity", {})
            return {
                "answer": entity.get("answer", ""),
                "matched_question": entity.get("question", ""),
                "level": "L1_SEMANTIC",
                "distance": distance,
            }
        except Exception as exc:
            print(f"SemanticCache get_cache failed: {exc}")
            return None

    @property
    def available(self) -> bool:
        return self._available

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.strip().lower().split())

    @staticmethod
    def _get_embedding_api_key() -> str | None:
        import os

        explicit_key = (
            settings.embedding_api_key
            or os.getenv("DASHSCOPE_EMBEDDING_API_KEY")
            or os.getenv("EMBEDDING_API_KEY")
        )
        if explicit_key:
            return explicit_key.strip()

        if settings.llm_api_key and settings.dashscope_api_key:
            return settings.dashscope_api_key.strip()

        base_url = (settings.base_url or "").lower()
        if "dashscope.aliyuncs.com" in base_url:
            return settings.dashscope_api_key.strip()
        return None

    def _query_one(self, filter_expr: str) -> dict[str, Any] | None:
        try:
            rows = self._client.query(
                collection_name=COLLECTION_NAME,
                filter=filter_expr,
                output_fields=["question", "answer", "scope", "user_id"],
                limit=1,
            )
            if rows:
                return rows[0]
            return None
        except Exception:
            return None

    def _ensure_collection(self) -> None:
        from pymilvus import DataType

        if self._client.has_collection(COLLECTION_NAME):
            return

        schema = self._client.create_schema()
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("question", DataType.VARCHAR, max_length=2048)
        schema.add_field("question_norm", DataType.VARCHAR, max_length=2048)
        schema.add_field("answer", DataType.VARCHAR, max_length=8192)
        schema.add_field("scope", DataType.VARCHAR, max_length=16)
        schema.add_field("user_id", DataType.VARCHAR, max_length=128)
        schema.add_field("enabled", DataType.INT8)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 256},
        )

        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
        )


semantic_cache = SemanticCache()
