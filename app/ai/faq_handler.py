"""
FAQ database handler
"""
from typing import Optional, Dict, List
from app.database.database import get_db
from sqlalchemy.orm import Session


class FAQHandler:
    """Handles FAQ queries and answers"""
    
    def __init__(self):
        # In-memory FAQ - keyword match injects this into the AI prompt
        self.faq_database = {
            "opening hours": "We are open 5:00–23:00. Staff present 10:00–19:00 (Mon–Thu), 10:00–17:00 (Fri), 10:00–15:00 (Sat–Sun). Members can enter digitally when no staff is present.",
            "hours": "We are open 5:00–23:00. Staff present 10:00–19:00 (Mon–Thu), 10:00–17:00 (Fri), 10:00–15:00 (Sat–Sun). Members can enter digitally when no staff is present.",
            "price": "Membership: 5990 SEK/year (1-year fixed), 6990 SEK/year (non-binding, 2 months notice), 599 SEK/month (1-year fixed), 699 SEK/month (non-binding, 2 months notice).",
            "prices": "Membership: 5990 SEK/year (1-year fixed), 6990 SEK/year (non-binding, 2 months notice), 599 SEK/month (1-year fixed), 699 SEK/month (non-binding, 2 months notice).",
            "cost": "Membership: 5990 SEK/year (1-year fixed), 6990 SEK/year (non-binding, 2 months notice), 599 SEK/month (1-year fixed), 699 SEK/month (non-binding, 2 months notice).",
            "parking": "We have free parking on our private parking lots.",
            "group training": "We offer Physical Fitness, Upper Body, Booty Builders, Yoga, and Taekwondo.",
            "pt": "We offer personal training for individuals and in smaller groups.",
            "personal trainer": "We offer personal training for individuals and in smaller groups.",
            "babies": "Kids in a crib or buggy are welcome beside you while you train. Kids who can move around on their own are not allowed. Age limit at the gym is 18.",
            "children": "Kids in a crib or buggy are welcome beside you while you train. Kids who can move around on their own are not allowed. Age limit at the gym is 18.",
            "equipment": "We use equipment brands such as Gym80, Primal, Booty Builder, and more. We have towel service and lockers for rent, and in-house smoothies with protein, kreatin, and other supplements.",
            "machines": "Our equipment includes brands like Gym80, Primal, Booty Builder, and more.",
            "brands": "We use Gym80, Primal, Booty Builder, and other quality brands.",
            "classes": "We offer Physical Fitness, Upper Body, Booty Builders, Yoga, and Taekwondo.",
            "yoga": "We offer Yoga among our group classes.",
            "smoothies": "We serve in-house smoothies with protein, kreatin, and other supplements and support all major nutrition brands.",
            "nutrition": "We support all major nutrition brands and serve in-house smoothies with protein, kreatin, and other supplements.",
            "towel": "We have towel service available.",
            "lockers": "We have lockers for rent.",
            "age": "The age limit at the gym is 18. Kids in a crib or buggy are welcome beside you; kids who can move on their own are not allowed.",
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

