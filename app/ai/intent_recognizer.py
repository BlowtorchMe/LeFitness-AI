"""
Intent recognition for customer messages
"""
from typing import Dict, List
import re


class IntentRecognizer:
    """Recognizes customer intent from messages"""
    
    INTENT_PATTERNS = {
        "book": [
            r"book", r"appointment", r"schedule", r"reserve", r"visit",
            r"come in", r"tour", r"trial", r"free period"
        ],
        "cancel": [
            r"cancel", r"cancel", r"reschedule", r"change", r"postpone",
            r"can't make it", r"won't be able"
        ],
        "question": [
            r"what", r"when", r"where", r"how", r"why", r"hours",
            r"price", r"cost", r"parking", r"equipment", r"rules"
        ],
        "greeting": [
            r"hi", r"hello", r"hey", r"good morning", r"good afternoon"
        ],
        "goodbye": [
            r"bye", r"goodbye", r"thanks", r"thank you", r"see you"
        ],
        "frustrated": [
            r"angry", r"frustrated", r"disappointed", r"upset", r"problem",
            r"issue", r"complaint"
        ]
    }
    
    async def recognize(self, message: str) -> str:
        """
        Recognize intent from customer message
        
        Args:
            message: Customer message text
        
        Returns:
            Intent string (book, cancel, question, greeting, goodbye, frustrated, unknown)
        """
        message_lower = message.lower()
        
        # Check each intent pattern
        intent_scores: Dict[str, int] = {}
        
        for intent, patterns in self.INTENT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, message_lower):
                    score += 1
            if score > 0:
                intent_scores[intent] = score
        
        # Return intent with highest score, or "unknown"
        if intent_scores:
            return max(intent_scores, key=intent_scores.get)
        
        return "unknown"
    
    def get_confidence(self, message: str, intent: str) -> float:
        """Get confidence score for recognized intent"""
        message_lower = message.lower()
        patterns = self.INTENT_PATTERNS.get(intent, [])
        
        matches = sum(1 for pattern in patterns if re.search(pattern, message_lower))
        total_patterns = len(patterns)
        
        return matches / total_patterns if total_patterns > 0 else 0.0

