"""
Minimal intent recognition for explicit control-flow decisions only.

Everything else should flow through the main LLM answer path instead of being
over-classified here.
"""
import re
from typing import Dict


class IntentRecognizer:
    """Recognizes only high-signal intents that change the workflow."""

    INTENT_PATTERNS = {
        "book": [
            r"\bi\s+want\s+to\s+book\b",
            r"\blet'?s\s+book\b",
            r"\bbook\s+(my|the|a|an)\b",
            r"\bmake\s+an?\s+appointment\b",
            r"\bschedule\s+(an?\s+)?(appointment|visit|trial)\b",
            r"\breserve\s+(a|an|my)\b",
            r"\bavailable\s+times?\b",
            r"\btime\s+slots?\b",
            r"\bwhen\s+can\s+i\s+come\b",
            r"\bbook\s+now\b",
        ],
        "cancel": [
            r"\bcancel\b",
            r"\breschedule\b",
            r"\bpostpone\b",
            r"\bcan'?t\s+make\s+it\b",
            r"\bwon'?t\s+be\s+able\b",
        ],
        "greeting": [
            r"\bhi\b", r"\bhello\b", r"\bhey\b", r"\bgood morning\b", r"\bgood afternoon\b",
        ],
        "goodbye": [
            r"\bbye\b", r"\bgoodbye\b", r"\bthanks\b", r"\bthank you\b", r"\bsee you\b",
        ],
        "overview": [
            r"\blearn\s+more\b",
            r"\bknow\s+more\b",
            r"\btell\s+me\s+more\b",
            r"\bask\s+(some|a\s+few)?\s*questions\b",
            r"\bhave\s+(some|a\s+few)\s+questions\b",
            r"\bquestions?\s+before\s+booking\b",
            r"\bbefore\s+booking\b.*\bquestions?\b",
            r"\bmore\s+about\s+(your|the)\s+(service|services|gym)\b",
            r"\bwhat\s+do\s+you\s+offer\b",
            r"\bwhat\s+services\s+do\s+you\s+have\b",
            r"\bwhat\s+kind\s+of\s+(services|training|classes)\b",
        ],
        "frustrated": [
            r"\bangry\b", r"\bfrustrated\b", r"\bdisappointed\b", r"\bupset\b",
            r"\bproblem\b", r"\bissue\b", r"\bcomplaint\b",
        ],
    }

    async def recognize(self, message: str) -> str:
        """Return explicit intent or 'unknown' for normal conversation."""
        message_lower = message.lower()
        intent_scores: Dict[str, int] = {}

        for intent, patterns in self.INTENT_PATTERNS.items():
            score = sum(1 for pattern in patterns if re.search(pattern, message_lower))
            if score > 0:
                intent_scores[intent] = score

        if intent_scores:
            return max(intent_scores, key=intent_scores.get)
        return "unknown"

    def get_confidence(self, message: str, intent: str) -> float:
        """Get confidence score for recognized intent."""
        message_lower = message.lower()
        patterns = self.INTENT_PATTERNS.get(intent, [])
        matches = sum(1 for pattern in patterns if re.search(pattern, message_lower))
        total_patterns = len(patterns)
        return matches / total_patterns if total_patterns > 0 else 0.0
