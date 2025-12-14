"""
FAQ database handler
"""
from typing import Optional, Dict, List
from app.database.database import get_db
from sqlalchemy.orm import Session


class FAQHandler:
    """Handles FAQ queries and answers"""
    
    def __init__(self):
        # In-memory FAQ for now - will be replaced with database
        self.faq_database = {
            "opening hours": "We're open [to be configured]",
            "hours": "We're open [to be configured]",
            "price": "Our membership prices are [to be configured]",
            "prices": "Our membership prices are [to be configured]",
            "cost": "Our membership prices are [to be configured]",
            "parking": "We have parking available [to be configured]",
            "group training": "Our group training schedule is [to be configured]",
            "pt": "Personal training setup is available [to be configured]",
            "personal trainer": "Personal training setup is available [to be configured]",
            "babies": "Rules for babies at the gym: [to be configured]",
            "children": "Rules for children at the gym: [to be configured]",
            "equipment": "We have [to be configured] equipment available"
        }
    
    async def get_answer(self, question: str) -> Optional[str]:
        """
        Get FAQ answer for a question
        
        Args:
            question: Customer question
        
        Returns:
            FAQ answer if found, None otherwise
        """
        question_lower = question.lower()
        
        # Simple keyword matching - can be enhanced with semantic search
        for keyword, answer in self.faq_database.items():
            if keyword in question_lower:
                return answer
        
        return None
    
    async def add_faq(self, question: str, answer: str) -> bool:
        """Add a new FAQ entry"""
        # TODO: Implement database storage
        self.faq_database[question.lower()] = answer
        return True
    
    async def update_faq(self, question: str, answer: str) -> bool:
        """Update an existing FAQ entry"""
        # TODO: Implement database storage
        if question.lower() in self.faq_database:
            self.faq_database[question.lower()] = answer
            return True
        return False
    
    async def list_faqs(self) -> List[Dict[str, str]]:
        """List all FAQ entries"""
        return [{"question": k, "answer": v} for k, v in self.faq_database.items()]

