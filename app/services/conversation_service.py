"""
Conversation service for saving messages to database
"""
from sqlalchemy.orm import Session
from app.models.conversation import Conversation, MessageDirection, ConversationChannel
from typing import Optional, Dict
from datetime import datetime


class ConversationService:
    """Service for managing conversation messages"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def save_message(
        self,
        lead_id: Optional[int],
        channel: ConversationChannel,
        direction: MessageDirection,
        message_text_en: Optional[str] = None,
        message_text_sv: Optional[str] = None,
        messenger_id: Optional[str] = None,
        phone_number: Optional[str] = None,
        intent: Optional[str] = None,
        ai_response: Optional[str] = None,
        faq_used: Optional[str] = None,
        needs_human: bool = False,
    ) -> Conversation:
        """Save a conversation message. At least one of message_text_en, message_text_sv required."""
        conversation = Conversation(
            lead_id=lead_id,
            channel=channel,
            direction=direction,
            message_text_en=message_text_en,
            message_text_sv=message_text_sv,
            messenger_id=messenger_id,
            phone_number=phone_number,
            intent=intent,
            ai_response=ai_response,
            faq_used=faq_used,
            needs_human=needs_human,
            created_at=datetime.utcnow()
        )
        
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        
        return conversation
    
    def get_conversation_history(
        self,
        lead_id: Optional[int] = None,
        messenger_id: Optional[str] = None,
        phone_number: Optional[str] = None,
        limit: int = 50
    ) -> list:
        """
        Get conversation history for a lead
        
        Args:
            lead_id: Lead ID
            messenger_id: Messenger ID
            phone_number: Phone number
            limit: Maximum number of messages to return
        
        Returns:
            List of Conversation objects
        """
        query = self.db.query(Conversation)
        
        if lead_id:
            query = query.filter(Conversation.lead_id == lead_id)
        elif messenger_id:
            query = query.filter(Conversation.messenger_id == messenger_id)
        elif phone_number:
            query = query.filter(Conversation.phone_number == phone_number)
        else:
            return []
        
        return query.order_by(Conversation.created_at.desc()).limit(limit).all()
    
    def get_conversation_history_for_ai(
        self,
        lead_id: Optional[int] = None,
        messenger_id: Optional[str] = None,
        phone_number: Optional[str] = None,
        limit: int = 20,
        lang: str = "en",
    ) -> list:
        """Get conversation history for AI. lang in ('en','sv') picks which text to use."""
        conversations = self.get_conversation_history(
            lead_id=lead_id,
            messenger_id=messenger_id,
            phone_number=phone_number,
            limit=limit
        )
        history = []
        for conv in reversed(conversations):
            if lang == "sv" and conv.message_text_sv:
                content = conv.message_text_sv
            elif conv.message_text_en:
                content = conv.message_text_en
            else:
                content = conv.message_text_sv or conv.message_text_en or ""
            if conv.direction == MessageDirection.INBOUND:
                history.append({"role": "user", "content": content})
            elif conv.direction == MessageDirection.OUTBOUND:
                history.append({"role": "assistant", "content": content})
        return history

