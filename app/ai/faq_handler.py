"""
FAQ handler: DB-based RAG via pgvector (same store as faq_indexer).
"""
import asyncio
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from typing import Optional, Sequence

from haystack.components.embedders import OpenAITextEmbedder
from haystack.utils import Secret
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore

from app.config import settings

EMBEDDING_DIMENSION = 1536
logger = logging.getLogger(__name__)
FAQ_DIRECT_RESPONSE_THRESHOLD = 0.6

DIRECT_FAQ_RULES = (
    (
        (
            r"\bopening hours\b",
            r"\bstaffed hours\b",
            r"\bopen\b.*\bhours\b",
            r"\bwhat time\b.*\bopen\b",
            r"\bwhen are you open\b",
        ),
        "LE Fitness is open 5:00 to 23:00 every day. Staff are available 10:00 to 19:00 Monday to Thursday, 10:00 to 17:00 Friday, and 10:00 to 15:00 Saturday and Sunday.",
        "LE Fitness har öppet 5:00 till 23:00 varje dag. Personal finns på plats 10:00 till 19:00 måndag till torsdag, 10:00 till 17:00 fredag och 10:00 till 15:00 lördag och söndag.",
    ),
    (
        (
            r"\bprice\b",
            r"\bprices\b",
            r"\bcost\b",
            r"\bmembership\b",
            r"\bmemberships\b",
            r"\bmonthly\b",
        ),
        "Our memberships are 5990 SEK/year fixed, 6990 SEK/year non-binding, 599 SEK/month fixed, and 699 SEK/month non-binding.",
        "Våra medlemskap kostar 5990 SEK/år bundet, 6990 SEK/år obundet, 599 SEK/månad bundet och 699 SEK/månad obundet.",
    ),
    (
        (
            r"\bparking\b",
            r"\bpark\b",
        ),
        "We have free parking on our private parking lots.",
        "Vi har gratis parkering på våra privata parkeringsplatser.",
    ),
    (
        (
            r"\bclasses\b",
            r"\bclass\b",
            r"\bgroup training\b",
            r"\bgroup classes\b",
        ),
        "We offer Physical Fitness, Upper Body, Booty Builders, Yoga, and Taekwondo classes.",
        "Vi erbjuder klasserna Physical Fitness, Upper Body, Booty Builders, Yoga och Taekwondo.",
    ),
    (
        (
            r"\bpersonal training\b",
            r"\bpt\b",
            r"\btrainer\b",
        ),
        "Yes, we offer personal training for individuals and smaller groups.",
        "Ja, vi erbjuder personlig träning för individer och mindre grupper.",
    ),
    (
        (
            r"\bequipment\b",
            r"\bmachines\b",
            r"\bfree weights\b",
            r"\bweights\b",
        ),
        "We have equipment from Gym80, Primal, Booty Builder, and more, including free weights and strength machines.",
        "Vi har utrustning från Gym80, Primal, Booty Builder och fler, inklusive fria vikter och styrkemaskiner.",
    ),
    (
        (
            r"\btowel\b",
            r"\blocker\b",
            r"\blockers\b",
        ),
        "We offer towel service and lockers for rent.",
        "Vi erbjuder handduksservice och skåp att hyra.",
    ),
    (
        (
            r"\b(8\s*[-–]\s*18|8\s+to\s+18)\b",
            r"\bunder\s+18\b",
            r"\bchildren\b.*\bservices?\b",
            r"\bservices?\b.*\bchildren\b",
            r"\bkids\b.*\bservices?\b",
            r"\bservices?\b.*\bkids\b",
        ),
        "That's right. We don't offer training services for children under 18. Babies in a crib or buggy can stay beside you while you train, but children who move around on their own are not allowed.",
        "Det stämmer. Vi erbjuder inte träningstjänster för barn under 18 år. Bebisar i barnvagn kan vara bredvid dig medan du tränar, men barn som rör sig på egen hand är inte tillåtna.",
    ),
    (
        (
            r"\bage limit\b",
            r"\bchildren\b",
            r"\bkids\b",
            r"\bbaby\b",
            r"\bbabies\b",
        ),
        "The age limit is 18. Babies in a crib or buggy are welcome beside you while you train, but children who move around on their own are not allowed.",
        "Åldersgränsen är 18 år. Bebisar i barnvagn är välkomna bredvid dig när du tränar, men barn som rör sig på egen hand är inte tillåtna.",
    ),
)


@dataclass(frozen=True)
class FAQMatch:
    answer: str
    score: float
    video_link: Optional[str] = None
    answer_sv: Optional[str] = None
    gym_ids: tuple[int, ...] = ()


def _ensure_pg_conn_str() -> None:
    if not os.environ.get("PG_CONN_STR") and getattr(settings, "database_url", None):
        os.environ["PG_CONN_STR"] = settings.database_url


@lru_cache(maxsize=1)
def _get_document_store() -> PgvectorDocumentStore:
    _ensure_pg_conn_str()
    return PgvectorDocumentStore(
        recreate_table=False,
        search_strategy="hnsw",
        embedding_dimension=EMBEDDING_DIMENSION,
    )


@lru_cache(maxsize=1)
def _get_embedder() -> OpenAITextEmbedder:
    return OpenAITextEmbedder(
        api_key=Secret.from_token(settings.openai_api_key),
        model=settings.openai_embedding_model,
    )


@lru_cache(maxsize=1)
def _get_retriever() -> PgvectorEmbeddingRetriever:
    return PgvectorEmbeddingRetriever(document_store=_get_document_store())


def _warm_components_sync() -> bool:
    if not settings.openai_api_key:
        return False
    try:
        t0 = perf_counter()
        _get_document_store()
        embedder = _get_embedder()
        _get_retriever()
        embedder.run(text="warmup")
        logger.info("faq_warmup_timing init=%.3f", perf_counter() - t0)
        return True
    except Exception:
        logger.exception("faq_warmup_failed")
        return False


def _get_direct_match(question: str) -> Optional[FAQMatch]:
    normalized = " ".join((question or "").strip().lower().split())
    if not normalized:
        return None
    for patterns, answer, answer_sv in DIRECT_FAQ_RULES:
        if any(re.search(pattern, normalized) for pattern in patterns):
            return FAQMatch(answer=answer, answer_sv=answer_sv, score=1.0)
    return None


def _detect_gym_from_question(question: str) -> Optional[int]:
    q = (question or "").strip().lower()

    if "värmdö" in q or "varmdo" in q:
        return 2

    if "täby" in q or "taby" in q:
        return 1

    return None


def _match_for_selected_gym(gym_ids: Sequence[int], selected_gym_id: Optional[int]) -> bool:
    if not gym_ids:
        return True
    if selected_gym_id is None:
        return False
    return selected_gym_id in gym_ids


def _retrieve_match_sync(question: str, selected_gym_id: Optional[int] = None) -> Optional[FAQMatch]:
    _ensure_pg_conn_str()

    detected_gym_id = _detect_gym_from_question(question)
    effective_gym_id = detected_gym_id if detected_gym_id is not None else selected_gym_id

    if not settings.openai_api_key:
        direct_match = _get_direct_match(question)
        if direct_match and _match_for_selected_gym(direct_match.gym_ids, effective_gym_id):
            logger.info("faq_direct_keyword_match score=1.000")
            return direct_match
        return None

    try:
        t0 = perf_counter()
        embedder = _get_embedder()
        retriever = _get_retriever()
        t1 = perf_counter()

        out = embedder.run(text=question)
        t2 = perf_counter()

        embedding = out.get("embedding")
        if not embedding:
            direct_match = _get_direct_match(question)
            if direct_match and _match_for_selected_gym(direct_match.gym_ids, effective_gym_id):
                return direct_match
            return None

        result = retriever.run(query_embedding=embedding, top_k=5)
        t3 = perf_counter()
        docs = result.get("documents") or []
        for i, doc in enumerate(docs):
            logger.info(
                "faqdoc%s score=%.3f content=%r answer=%r gym_ids=%r meta=%r",
                i,
                float(getattr(doc, "score", 0.0) or 0.0),
                getattr(doc, "content", "")[:200],
                doc.meta.get("answer"),
                doc.meta.get("gym_ids"),
                doc.meta,
            )

        logger.info(
            "faq_debug question=%r selected_gym=%s detected_gym=%s effective_gym=%s docs=%s",
            question,
            selected_gym_id,
            detected_gym_id,
            effective_gym_id,
            len(docs),
        )

        logger.info(
            "faq_retrieve_timing cached_init=%.3f embed=%.3f retrieve=%.3f score=%.3f selected_gym=%s detected_gym=%s effective_gym=%s",
            t1 - t0,
            t2 - t1,
            t3 - t2,
            float(getattr(docs[0], "score", 0.0) or 0.0) if docs else 0.0,
            selected_gym_id,
            detected_gym_id,
            effective_gym_id,
        )

        for doc in docs:
            answer = doc.meta.get("answer")
            score = float(getattr(doc, "score", 0.0) or 0.0)
            video_link = doc.meta.get("video_link") or None
            gym_ids = tuple(int(gym_id) for gym_id in (doc.meta.get("gym_ids") or []) if gym_id)

            if (
                answer
                and score >= FAQ_DIRECT_RESPONSE_THRESHOLD
                and _match_for_selected_gym(gym_ids, effective_gym_id)
            ):
                return FAQMatch(
                    answer=answer,
                    score=score,
                    video_link=video_link,
                    gym_ids=gym_ids,
                )

        direct_match = _get_direct_match(question)
        if direct_match and _match_for_selected_gym(direct_match.gym_ids, effective_gym_id):
            logger.info("faq_direct_keyword_match score=1.000")
            return direct_match

        return None
    except Exception:
        logger.exception("faq_retrieve_failed")
        direct_match = _get_direct_match(question)
        if direct_match and _match_for_selected_gym(direct_match.gym_ids, effective_gym_id):
            return direct_match
        return None


class FAQHandler:
    """Handles FAQ queries via DB-backed pgvector RAG."""

    async def get_match(self, question: str, selected_gym_id: Optional[int] = None) -> Optional[FAQMatch]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            _retrieve_match_sync,
            question.strip() or "",
            selected_gym_id,
        )

    async def get_answer(self, question: str, selected_gym_id: Optional[int] = None) -> Optional[str]:
        match = await self.get_match(question, selected_gym_id=selected_gym_id)
        return match.answer if match else None

    @staticmethod
    def warmup() -> bool:
        return _warm_components_sync()