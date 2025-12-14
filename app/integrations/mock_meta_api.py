"""
Mock Meta API for testing without real Facebook/Instagram accounts
"""
from typing import Dict, Optional
import json
from datetime import datetime


class MockMetaAPI:
    """Mock implementation of Meta API for testing"""
    
    def __init__(self):
        self.base_url = "https://graph.facebook.com/v18.0"
        self.access_token = "mock_token"
        self.verify_token = "mock_verify_token"
        self._mock_users = {}  # Store mock user data
    
    def verify_webhook(self, mode: str, token: str, challenge: str) -> bool:
        """Verify webhook (always returns True in mock mode)"""
        return token == self.verify_token
    
    def send_messenger_message(self, recipient_id: str, message: str) -> Dict:
        """Mock sending a message - just logs it"""
        print(f"[MOCK] Sending message to {recipient_id}: {message}")
        return {
            "success": True,
            "message_id": f"mock_msg_{datetime.now().timestamp()}",
            "recipient_id": recipient_id
        }
    
    def get_user_profile(self, user_id: str, platform: str = "facebook") -> Dict:
        """Get mock user profile"""
        # Return mock profile if exists, otherwise create default
        if user_id not in self._mock_users:
            self._mock_users[user_id] = {
                "id": user_id,
                "first_name": "Test",
                "last_name": "User",
                "name": "Test User",
                "email": f"test_{user_id}@example.com",
                "profile_pic": None
            }
        
        user = self._mock_users[user_id].copy()
        
        if platform == "instagram":
            user["username"] = user.get("first_name", "testuser").lower()
            # Instagram has limited fields
            return {"username": user["username"]}
        
        return user
    
    def update_mock_user(self, user_id: str, **kwargs):
        """Update mock user data for testing"""
        if user_id not in self._mock_users:
            self._mock_users[user_id] = {"id": user_id}
        self._mock_users[user_id].update(kwargs)
    
    def get_mock_user(self, user_id: str) -> Optional[Dict]:
        """Get mock user data"""
        return self._mock_users.get(user_id)
    
    def list_mock_users(self) -> Dict:
        """List all mock users"""
        return self._mock_users


class MockMessengerAPI:
    """Mock implementation of Messenger API for testing"""
    
    def __init__(self):
        self.meta_api = MockMetaAPI()
        self._sent_messages = []  # Store sent messages for testing
    
    def send_message(self, recipient_id: str, message: str) -> Dict:
        """Mock sending a message"""
        result = self.meta_api.send_messenger_message(recipient_id, message)
        self._sent_messages.append({
            "type": "text",
            "recipient_id": recipient_id,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
        return result
    
    def send_quick_replies(
        self,
        recipient_id: str,
        message: str,
        quick_replies: list
    ) -> Dict:
        """Mock sending quick replies"""
        print(f"[MOCK] Sending quick replies to {recipient_id}:")
        print(f"  Message: {message}")
        print(f"  Options: {[r.get('title') for r in quick_replies]}")
        
        self._sent_messages.append({
            "type": "quick_replies",
            "recipient_id": recipient_id,
            "message": message,
            "quick_replies": quick_replies,
            "timestamp": datetime.now().isoformat()
        })
        
        return {"success": True, "message_id": f"mock_quick_{datetime.now().timestamp()}"}
    
    def send_button_template(
        self,
        recipient_id: str,
        text: str,
        buttons: list
    ) -> Dict:
        """Mock sending button template"""
        print(f"[MOCK] Sending button template to {recipient_id}:")
        print(f"  Text: {text}")
        print(f"  Buttons: {[b.get('title') for b in buttons]}")
        
        self._sent_messages.append({
            "type": "button_template",
            "recipient_id": recipient_id,
            "text": text,
            "buttons": buttons,
            "timestamp": datetime.now().isoformat()
        })
        
        return {"success": True, "message_id": f"mock_button_{datetime.now().timestamp()}"}
    
    def send_generic_template(
        self,
        recipient_id: str,
        elements: list
    ) -> Dict:
        """Mock sending generic template"""
        print(f"[MOCK] Sending generic template to {recipient_id}")
        self._sent_messages.append({
            "type": "generic_template",
            "recipient_id": recipient_id,
            "elements": elements,
            "timestamp": datetime.now().isoformat()
        })
        return {"success": True, "message_id": f"mock_generic_{datetime.now().timestamp()}"}
    
    def get_sent_messages(self, recipient_id: Optional[str] = None) -> list:
        """Get all sent messages (for testing)"""
        if recipient_id:
            return [m for m in self._sent_messages if m.get("recipient_id") == recipient_id]
        return self._sent_messages
    
    def clear_sent_messages(self):
        """Clear sent messages history"""
        self._sent_messages = []

