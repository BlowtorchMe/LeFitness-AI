"""
FAQ handler: DB-based RAG via pgvector (same store as faq_indexer).
"""
import asyncio
import os
import logging
from time import perf_counter
from typing import Optional

from haystack.utils import Secret
from haystack.components.embedders import OpenAITextEmbedder
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever

from app.config import settings
EMBEDDING_DIMENSION = 1536
logger = logging.getLogger(__name__)


def _ensure_pg_conn_str() -> None:
    if not os.environ.get("PG_CONN_STR") and getattr(settings, "database_url", None):
        os.environ["PG_CONN_STR"] = settings.database_url


def _retrieve_answer_sync(question: str) -> Optional[str]:
    _ensure_pg_conn_str()
    if not settings.openai_api_key:
        return None
    try:
        t0 = perf_counter()
        store = PgvectorDocumentStore(
            recreate_table=False,
            search_strategy="hnsw",
            embedding_dimension=EMBEDDING_DIMENSION,
        )
        t1 = perf_counter()
        embedder = OpenAITextEmbedder(
            api_key=Secret.from_token(settings.openai_api_key),
            model=settings.openai_embedding_model,
        )
        retriever = PgvectorEmbeddingRetriever(document_store=store)
        out = embedder.run(text=question)
        t2 = perf_counter()
        embedding = out.get("embedding")
        if not embedding:
            return None
        result = retriever.run(query_embedding=embedding, top_k=1)
        t3 = perf_counter()
        docs = result.get("documents") or []
        if not docs:
            return None
        doc = docs[0]
        answer = doc.meta.get("answer")
        logger.info(
            "faq_retrieve_timing store=%.3f embed=%.3f retrieve=%.3f",
            t1 - t0,
            t2 - t1,
            t3 - t2,
        )
        if not answer:
            return None
        return answer
    except Exception:
        logger.exception("faq_retrieve_failed")
        return None


class FAQHandler:
    """Handles FAQ queries via DB-backed pgvector RAG."""

    async def get_answer(self, question: str) -> Optional[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _retrieve_answer_sync, question.strip() or "")
