"""
FAQ indexer: load FAQs from DB -> build Documents -> embed -> write to pgvector.
Run: python -m app.faq_indexer (from project root).
Requires: CREATE EXTENSION vector; on the DB (Neon supports this).
"""
import os
from typing import List, Dict, Any

from haystack.dataclasses import Document
from haystack.utils import Secret
from haystack.components.embedders import OpenAIDocumentEmbedder
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack.document_stores.types import DuplicatePolicy

from app.config import settings
from app.database.database import SessionLocal
from app.models.faq import FAQ

EMBEDDING_DIMENSION = 1536


def _ensure_pg_conn_str() -> None:
    if not os.environ.get("PG_CONN_STR") and getattr(settings, "database_url", None):
        os.environ["PG_CONN_STR"] = settings.database_url


def _load_faq_documents() -> List[Document]:
    db = SessionLocal()
    try:
        rows = db.query(FAQ).order_by(FAQ.id).all()
        docs = []
        for row in rows:
            content = f"{row.question} {row.answer}".strip()
            meta = {"faq_id": row.id, "answer": row.answer, "video_link": row.video_link or ""}
            docs.append(Document(content=content, meta=meta))
        return docs
    finally:
        db.close()


def run_indexer(recreate_table: bool = False) -> Dict[str, Any]:
    """
    Load FAQs from DB, embed with OpenAI, write to pgvector.
    Returns dict with success, count, error.
    """
    _ensure_pg_conn_str()
    if not settings.openai_api_key:
        return {"success": False, "count": 0, "error": "OPENAI_API_KEY not set"}
    documents = _load_faq_documents()
    if not documents:
        return {"success": True, "count": 0, "error": None}
    try:
        store = PgvectorDocumentStore(
            recreate_table=recreate_table,
            search_strategy="hnsw",
            embedding_dimension=EMBEDDING_DIMENSION,
        )
        embedder = OpenAIDocumentEmbedder(
            api_key=Secret.from_token(settings.openai_api_key),
            model=settings.openai_embedding_model,
        )
        embedded = embedder.run(documents=documents)
        out_docs = embedded.get("documents") or []
        if out_docs:
            store.write_documents(out_docs, policy=DuplicatePolicy.OVERWRITE)
        return {"success": True, "count": len(out_docs), "error": None}
    except Exception as e:
        return {"success": False, "count": 0, "error": str(e)}


if __name__ == "__main__":
    result = run_indexer(recreate_table=True)
    if result["success"]:
        print(f"Indexed {result['count']} FAQ(s).")
    else:
        print(f"Error: {result.get('error')}")
        exit(1)
