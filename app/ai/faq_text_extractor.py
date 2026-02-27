"""
Extract structured FAQ entries from free text using LLM.
Output matches FAQ schema (question, answer, video_link) for loading into DB or indexer.
"""
import json
import re
from typing import List

import openai

from app.config import settings
from app.models.faq import FAQSchema

EXTRACT_PROMPT = """Extract all FAQ entries from the text below. For each entry output:
- question: the question (exact or normalized)
- answer: the answer text
- video_link: URL if mentioned (e.g. "Video: https://..."), otherwise null

Return ONLY a JSON array of objects with keys question, answer, video_link. No other text.
Example: [{"question": "...", "answer": "...", "video_link": null}, ...]

Text:
"""
EXTRACT_MODEL = "gpt-4o-mini"


def extract_faqs_from_text(text: str) -> List[FAQSchema]:
    """
    Use LLM to extract question/answer/video_link from raw text.
    Returns list of FAQSchema; empty list if no API key or parsing fails.
    """
    if not settings.openai_api_key or not (text or "").strip():
        return []
    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=EXTRACT_MODEL,
            messages=[{"role": "user", "content": EXTRACT_PROMPT + text.strip()}],
            temperature=0.1,
        )
        content = (response.choices[0].message.content or "").strip()
        raw = _extract_json_array(content)
        if not raw:
            return []
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            q = (item.get("question") or "").strip()
            a = (item.get("answer") or "").strip()
            if not q or not a:
                continue
            try:
                out.append(FAQSchema(question=q, answer=a, video_link=item.get("video_link") or None))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _extract_json_array(content: str) -> List:
    content = content.strip()
    match = re.search(r"\[[\s\S]*\]", content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return []
