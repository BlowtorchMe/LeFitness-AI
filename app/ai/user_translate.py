"""
Translate user messages between English and Swedish for storing both in DB.
"""
from typing import Optional

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None


def translate_text(text: str, from_lang: str, to_lang: str) -> Optional[str]:
    """Translate text from one language to the other. from_lang/to_lang in ('en','sv')."""
    if not text or from_lang == to_lang:
        return text
    if GoogleTranslator is None:
        return None
    try:
        return GoogleTranslator(source=from_lang, target=to_lang).translate(text=text)
    except Exception:
        return None
