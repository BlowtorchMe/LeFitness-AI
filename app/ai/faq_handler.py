"""
FAQ handler: DB-based RAG via pgvector (same store as faq_indexer).
"""
import asyncio, os, time, logging
from typing import Optional, Dict, Any

from haystack.utils import Secret
from haystack.components.embedders import OpenAITextEmbedder
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever

from app.config import settings

EMBEDDING_DIMENSION = 1536

logger = logging.getLogger(__name__)

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
    if os.environ.get("PG_CONN_STR"):
        return

    db_url = getattr(settings, "database_url", None)
    if db_url:
        os.environ["PG_CONN_STR"] = _to_libpq_conn_str(db_url)


# ---------------------------------------------------------------------------
# Module-level singletons — skapas EN GÅNG vid uppstart, återanvänds sedan
# ---------------------------------------------------------------------------
_store = None
_embedder = None
_retriever = None


def _get_components():
    """Lazy-init: bygg store/embedder/retriever första gången, återanvänd sedan."""
    global _store, _embedder, _retriever
    if _store is not None:
        return _store, _embedder, _retriever
    _ensure_pg_conn_str()
    init_start = time.perf_counter()
    _store = PgvectorDocumentStore(
        recreate_table=False,
        search_strategy="hnsw",
        embedding_dimension=EMBEDDING_DIMENSION,
    )
    _embedder = OpenAITextEmbedder(
        api_key=Secret.from_token(settings.openai_api_key),
        model=settings.openai_embedding_model,
    )
    _retriever = PgvectorEmbeddingRetriever(document_store=_store)
    print(f"FAQ components initialized (one-time) in {(time.perf_counter() - init_start) * 1000:.1f} ms")
    return _store, _embedder, _retriever


def _retrieve_answer_sync(question: str) -> Optional[Dict[str, Any]]:
    total_start = time.perf_counter()
    print("FAQ handler was called")

    if not settings.openai_api_key:
        return None

    question = (question or "").strip()
    if not question:
        return None

    try:
        store, embedder, retriever = _get_components()

        embed_start = time.perf_counter()
        out = embedder.run(text=question)
        print("FAQ embedder.run took", (time.perf_counter() - embed_start) * 1000, "ms")

        embedding = out.get("embedding")
        if not embedding:
            return None

        retrieve_start = time.perf_counter()
        result = retriever.run(query_embedding=embedding, top_k=1)
        print("FAQ retriever.run took", (time.perf_counter() - retrieve_start) * 1000, "ms")

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
        print("FAQ total _retrieve_answer_sync took", (time.perf_counter() - total_start) * 1000, "ms")
        return {"answer": answer, "video_link": video_link}

    except Exception:
        logger.exception("FAQ retrieval failed")
        return None


class FAQHandler:
    async def get_answer(self, question: str) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _retrieve_answer_sync, question)