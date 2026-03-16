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


def _doc_id_for_faq(faq_id: int) -> str:
    return f"faq:{faq_id}"


def _faq_to_document(row: FAQ) -> Document:
    content = f"{row.question} {row.answer}".strip()
    meta = {"faq_id": row.id, "answer": row.answer, "video_link": row.video_link or ""}
    return Document(id=_doc_id_for_faq(row.id), content=content, meta=meta)


def _get_store(recreate_table: bool = False) -> PgvectorDocumentStore:
    return PgvectorDocumentStore(
        recreate_table=recreate_table,
        search_strategy="hnsw",
        embedding_dimension=EMBEDDING_DIMENSION,
    )


def _get_embedder() -> OpenAIDocumentEmbedder:
    return OpenAIDocumentEmbedder(
        api_key=Secret.from_token(settings.openai_api_key),
        model=settings.openai_embedding_model,
    )


def _delete_all_docs_for_faq(store: PgvectorDocumentStore, faq_id: int, keep_doc_id: str | None = None) -> int:
    docs = store.filter_documents(
        filters={"field": "meta.faq_id", "operator": "==", "value": faq_id}
    )
    doc_ids = [d.id for d in docs if d.id and d.id != keep_doc_id]
    if not doc_ids:
        return 0
    store.delete_documents(doc_ids)
    return len(doc_ids)


def _load_faq_documents() -> List[Document]:
    db = SessionLocal()
    try:
        rows = db.query(FAQ).order_by(FAQ.id).all()
        return [_faq_to_document(row) for row in rows]
    finally:
        db.close()


def upsert_faq_embedding(faq: FAQ) -> Dict[str, Any]:
    """
    Embed and upsert a single FAQ row. Also removes old duplicate docs for the same faq_id.
    """
    _ensure_pg_conn_str()
    if not settings.openai_api_key:
        return {"success": False, "count": 0, "error": "OPENAI_API_KEY not set"}
    try:
        store = _get_store(recreate_table=False)
        embedder = _get_embedder()
        embedded = embedder.run(documents=[_faq_to_document(faq)])
        out_docs = embedded.get("documents") or []
        if not out_docs:
            return {"success": False, "count": 0, "error": "Embedding failed: no documents produced"}
        store.write_documents(out_docs, policy=DuplicatePolicy.OVERWRITE)
        deleted = _delete_all_docs_for_faq(store, faq.id, keep_doc_id=_doc_id_for_faq(faq.id))
        return {"success": True, "count": len(out_docs), "deleted": deleted, "error": None}
    except Exception as e:
        return {"success": False, "count": 0, "error": str(e)}


def delete_faq_embeddings(faq_id: int) -> Dict[str, Any]:
    """
    Delete all embedding docs tied to a FAQ id (stable-id and legacy docs).
    """
    _ensure_pg_conn_str()
    try:
        store = _get_store(recreate_table=False)
        deleted = _delete_all_docs_for_faq(store, faq_id)
        return {"success": True, "count": deleted, "error": None}
    except Exception as e:
        return {"success": False, "count": 0, "error": str(e)}


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
        store = _get_store(recreate_table=recreate_table)
        embedder = _get_embedder()
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
