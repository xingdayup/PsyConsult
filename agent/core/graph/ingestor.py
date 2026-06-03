"""精神科知识图谱 Neo4j 摄入器。"""

import logging
from .client import Neo4jClient
from .models import Disease, Symptom, Drug, SideEffect, Treatment, Relation

logger = logging.getLogger(__name__)


class KnowledgeGraphIngestor:
    """将精神科知识导入 Neo4j。"""

    def __init__(self, client: Neo4jClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    # 实体摄入
    # ------------------------------------------------------------------

    async def ingest_diseases(self, diseases: list[Disease]) -> int:
        if not diseases:
            return 0
        query = """
        UNWIND $items AS item
        MERGE (n:Disease {id: item.id})
        SET n.name_cn = item.name_cn, n.name_en = item.name_en,
            n.description = item.description, n.updated_at = datetime()
        RETURN count(n) AS count
        """
        result = await self.client.execute_query(query, {"items": [d.__dict__ for d in diseases]})
        count = result[0]["count"] if result else 0
        logger.info("Ingested %d diseases", count)
        return count

    async def ingest_symptoms(self, symptoms: list[Symptom]) -> int:
        if not symptoms:
            return 0
        query = """
        UNWIND $items AS item
        MERGE (n:Symptom {id: item.id})
        SET n.name_cn = item.name_cn, n.category = item.category, n.updated_at = datetime()
        RETURN count(n) AS count
        """
        result = await self.client.execute_query(query, {"items": [s.__dict__ for s in symptoms]})
        count = result[0]["count"] if result else 0
        logger.info("Ingested %d symptoms", count)
        return count

    async def ingest_drugs(self, drugs: list[Drug]) -> int:
        if not drugs:
            return 0
        query = """
        UNWIND $items AS item
        MERGE (n:Drug {id: item.id})
        SET n.name_cn = item.name_cn, n.generic_name = item.generic_name,
            n.drug_class = item.drug_class, n.indication = item.indication,
            n.dosage = item.dosage, n.contraindications = item.contraindications,
            n.updated_at = datetime()
        RETURN count(n) AS count
        """
        result = await self.client.execute_query(query, {"items": [d.__dict__ for d in drugs]})
        count = result[0]["count"] if result else 0
        logger.info("Ingested %d drugs", count)
        return count

    async def ingest_side_effects(self, side_effects: list[SideEffect]) -> int:
        if not side_effects:
            return 0
        query = """
        UNWIND $items AS item
        MERGE (n:SideEffect {id: item.id})
        SET n.name_cn = item.name_cn, n.frequency = item.frequency, n.updated_at = datetime()
        RETURN count(n) AS count
        """
        result = await self.client.execute_query(query, {"items": [s.__dict__ for s in side_effects]})
        count = result[0]["count"] if result else 0
        logger.info("Ingested %d side effects", count)
        return count

    async def ingest_treatments(self, treatments: list[Treatment]) -> int:
        if not treatments:
            return 0
        query = """
        UNWIND $items AS item
        MERGE (n:Treatment {id: item.id})
        SET n.name_cn = item.name_cn, n.line = item.line,
            n.guideline_source = item.guideline_source, n.updated_at = datetime()
        RETURN count(n) AS count
        """
        result = await self.client.execute_query(query, {"items": [t.__dict__ for t in treatments]})
        count = result[0]["count"] if result else 0
        logger.info("Ingested %d treatments", count)
        return count

    # ------------------------------------------------------------------
    # 关系摄入
    # ------------------------------------------------------------------

    async def ingest_relations(self, relations: list[Relation]) -> int:
        if not relations:
            return 0

        relations_by_type: dict[str, list[Relation]] = {}
        for rel in relations:
            relations_by_type.setdefault(rel.relation_type, []).append(rel)

        total = 0
        for rel_type, rels in relations_by_type.items():
            query = f"""
            UNWIND $relations AS rel
            MATCH (a {{id: rel.source_id}})
            MATCH (b {{id: rel.target_id}})
            MERGE (a)-[r:{rel_type}]->(b)
            SET r += rel.properties, r.updated_at = datetime()
            RETURN count(r) AS count
            """
            params = {"relations": [
                {"source_id": r.source_id, "target_id": r.target_id, "properties": r.properties}
                for r in rels
            ]}
            result = await self.client.execute_query(query, params)
            total += result[0]["count"] if result else 0

        logger.info("Ingested %d total relations", total)
        return total

    # ------------------------------------------------------------------
    # 批量导入
    # ------------------------------------------------------------------

    async def ingest_all(
        self,
        diseases: list[Disease] | None = None,
        symptoms: list[Symptom] | None = None,
        drugs: list[Drug] | None = None,
        side_effects: list[SideEffect] | None = None,
        treatments: list[Treatment] | None = None,
        relations: list[Relation] | None = None,
    ) -> dict[str, int]:
        await self.client.create_constraints()

        stats = {}
        stats["diseases"] = await self.ingest_diseases(diseases or [])
        stats["symptoms"] = await self.ingest_symptoms(symptoms or [])
        stats["drugs"] = await self.ingest_drugs(drugs or [])
        stats["side_effects"] = await self.ingest_side_effects(side_effects or [])
        stats["treatments"] = await self.ingest_treatments(treatments or [])
        stats["relations"] = await self.ingest_relations(relations or [])

        logger.info("Clinical KG ingestion complete: %s", stats)
        return stats
