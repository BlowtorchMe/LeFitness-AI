"""
Translate user messages between English and Swedish for storing both in DB.
"""
from typing import Optional

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None

_MAX_CHARS = 4500


def translate_text(text: str, from_lang: str, to_lang: str) -> Optional[str]:
    """Translate text from one language to the other. from_lang/to_lang in ('en','sv')."""
    if not text or from_lang == to_lang:
        return text
    if GoogleTranslator is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        if len(text) <= _MAX_CHARS:
            return GoogleTranslator(source=from_lang, target=to_lang).translate(text=text)
        parts = []
        while text:
            chunk = text[:_MAX_CHARS]
            if len(text) > _MAX_CHARS:
                last_break = chunk.rfind("\n")
                if last_break > _MAX_CHARS // 2:
                    chunk = chunk[: last_break + 1]
                    text = text[last_break + 1 :].lstrip()
                else:
                    text = text[_MAX_CHARS:].lstrip()
            else:
                text = ""
            if chunk:
                parts.append(GoogleTranslator(source=from_lang, target=to_lang).translate(text=chunk))
        return "\n".join(parts) if parts else None
    except Exception:
        return None
