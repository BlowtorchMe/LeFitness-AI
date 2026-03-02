"""
FAQ handler: DB-based RAG via pgvector (same store as faq_indexer).
"""
import asyncio
import os
from typing import Optional

from haystack.utils import Secret
from haystack.components.embedders import OpenAITextEmbedder
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever

from app.config import settings

EMBEDDING_DIMENSION = 1536


def _ensure_pg_conn_str() -> None:
    if not os.environ.get("PG_CONN_STR") and getattr(settings, "database_url", None):
        os.environ["PG_CONN_STR"] = settings.database_url


def _retrieve_answer_sync(question: str) -> Optional[str]:
    _ensure_pg_conn_str()
    if not settings.openai_api_key:
        return None
    try:
        store = PgvectorDocumentStore(
            recreate_table=False,
            search_strategy="hnsw",
            embedding_dimension=EMBEDDING_DIMENSION,
        )
        embedder = OpenAITextEmbedder(
            api_key=Secret.from_token(settings.openai_api_key),
            model=settings.openai_embedding_model,
        )
        retriever = PgvectorEmbeddingRetriever(document_store=store)
        out = embedder.run(text=question)
        embedding = out.get("embedding")
        if not embedding:
            return None
        result = retriever.run(query_embedding=embedding, top_k=1)
        docs = result.get("documents") or []
        if not docs:
            return None
        meta = docs[0].meta or {}
        answer = (meta.get("answer") or "").strip()
        video = (meta.get("video_link") or "").strip()

        if video and video not in answer:
            return f"{answer.rstrip()}\n\n[Video]({video})"

        return answer

    except Exception:
        return None


class FAQHandler:
    """Handles FAQ queries via DB-backed pgvector RAG."""

    async def get_answer(self, question: str) -> Optional[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _retrieve_answer_sync, question.strip() or "")
