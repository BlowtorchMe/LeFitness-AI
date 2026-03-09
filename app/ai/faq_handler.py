"""
FAQ handler: DB-based RAG via pgvector (same store as faq_indexer).
"""
import asyncio
import os
from typing import Optional, Dict, Any

from haystack.utils import Secret
from haystack.components.embedders import OpenAITextEmbedder
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever

from app.config import settings

EMBEDDING_DIMENSION = 1536


def _to_libpq_conn_str(url: str) -> str:
    """
    Convert SQLAlchemy-style URL -> libpq-style URL.
    Example:
      postgresql+psycopg2://user:pass@host:5432/db
    becomes:
      postgresql://user:pass@host:5432/db
    """
    if not url:
        return url
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


def _ensure_pg_conn_str() -> None:
    # Prefer explicit PG_CONN_STR if set
    if os.environ.get("PG_CONN_STR"):
        return

    db_url = getattr(settings, "database_url", None)
    if db_url:
        os.environ["PG_CONN_STR"] = _to_libpq_conn_str(db_url)


def _retrieve_answer_sync(question: str) -> Optional[Dict[str, Any]]:
    _ensure_pg_conn_str()

    if not settings.openai_api_key:
        return None

    question = (question or "").strip()
    if not question:
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

        doc0 = docs[0]
        score = getattr(doc0, "score", None)

        try:
            min_score = float(os.environ.get("FAQ_MIN_SCORE", "0.78"))
        except ValueError:
            min_score = 0.78

        if score is not None and score < min_score:
            return None

        meta = doc0.meta or {}
        answer = meta.get("answer")
        if not answer:
            return None

        video_link = meta.get("video_link") or None
        return {"answer": answer, "video_link": video_link}

    except Exception:
        return None


class FAQHandler:
    async def get_answer(self, question: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _retrieve_answer_sync, question)