"""
Facebook Messenger API integration (wrapper around Meta API)
"""
from app.integrations.meta_api import MetaAPI
from typing import Dict, List, Optional


class MessengerAPI:
    """Handles Facebook Messenger interactions"""
    
    def __init__(self):
        # Always use real MetaAPI
        self.meta_api = MetaAPI()
    
    def send_message(self, recipient_id: str, message: str) -> Dict[str, any]:
        """Send message via Messenger"""
        return self.meta_api.send_messenger_message(recipient_id, message)
    
    def send_quick_replies(
        self,
        recipient_id: str,
        message: str,
        quick_replies: List[Dict]
    ) -> Dict[str, any]:
        """
        Send message with quick reply buttons (up to 13 buttons)
        
        Args:
            recipient_id: Facebook user ID
            message: Message text
            quick_replies: List of quick reply options
                Example: [{"content_type": "text", "title": "Yes", "payload": "YES"},
                         {"content_type": "text", "title": "No", "payload": "NO"}]
        
        Returns:
            Dict with send result
        """
        if not self.meta_api.access_token:
            error_msg = "META_ACCESS_TOKEN not set - cannot send messages"
            print(f"[ERROR] {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
        
        url = f"{self.meta_api.base_url}/me/messages"
        
        # Format quick replies
        formatted_replies = []
        for reply in quick_replies[:13]:  # Max 13 quick replies
            formatted_replies.append({
                "content_type": reply.get("content_type", "text"),
                "title": reply.get("title", ""),
                "payload": reply.get("payload", reply.get("title", ""))
            })
        
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "text": message,
                "quick_replies": formatted_replies
            },
            "messaging_type": "RESPONSE"
        }
        
        print(f"[SEND QUICK REPLIES] Sending to {recipient_id}: {message[:50]}...")
        response = self.meta_api._make_request("POST", url, payload)
        if response.get("success"):
            message_id = response.get("data", {}).get("message_id")
            print(f"[SEND QUICK REPLIES] Success! Message ID: {message_id}")
            return {
                "success": True,
                "message_id": message_id
            }
        else:
            print(f"[SEND QUICK REPLIES] Failed! {response.get('error')}")
        return response
    
    def send_button_template(
        self,
        recipient_id: str,
        text: str,
        buttons: List[Dict]
    ) -> Dict[str, any]:
        """
        Send message with button template (up to 3 buttons)
        
        Args:
            recipient_id: Facebook user ID
            text: Message text
            buttons: List of button options
                Example: [{"type": "postback", "title": "Book Now", "payload": "BOOK_NOW"},
                         {"type": "web_url", "title": "View Website", "url": "https://..."}]
        
        Returns:
            Dict with send result
        """
        if not self.meta_api.access_token:
            error_msg = "META_ACCESS_TOKEN not set - cannot send messages"
            print(f"[ERROR] {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
        
        url = f"{self.meta_api.base_url}/me/messages"
        
        # Format buttons (max 3)
        formatted_buttons = []
        for button in buttons[:3]:
            btn = {
                "type": button.get("type", "postback"),
                "title": button.get("title", "")
            }
            
            if button.get("type") == "postback":
                btn["payload"] = button.get("payload", button.get("title", ""))
            elif button.get("type") == "web_url":
                btn["url"] = button.get("url", "")
            elif button.get("type") == "phone_number":
                btn["payload"] = button.get("payload", "")
            
            formatted_buttons.append(btn)
        
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": text,
                        "buttons": formatted_buttons
                    }
                }
            },
            "messaging_type": "RESPONSE"
        }
        
        print(f"[SEND BUTTON TEMPLATE] Sending to {recipient_id}: {text[:50]}...")
        response = self.meta_api._make_request("POST", url, payload)
        if response.get("success"):
            message_id = response.get("data", {}).get("message_id")
            print(f"[SEND BUTTON TEMPLATE] Success! Message ID: {message_id}")
            return {
                "success": True,
                "message_id": message_id
            }
        else:
            print(f"[SEND BUTTON TEMPLATE] Failed! {response.get('error')}")
        return response
    
    def send_generic_template(
        self,
        recipient_id: str,
        elements: List[Dict]
    ) -> Dict[str, any]:
        """
        Send generic template (for time slots, etc.)
        
        Args:
            recipient_id: Facebook user ID
            elements: List of template elements (max 10)
        """
        if not self.meta_api.access_token:
            error_msg = "META_ACCESS_TOKEN not set - cannot send messages"
            print(f"[ERROR] {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
        
        url = f"{self.meta_api.base_url}/me/messages"
        
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": elements[:10]  # Max 10 elements
                    }
                }
            },
            "messaging_type": "RESPONSE"
        }
        
        print(f"[SEND GENERIC TEMPLATE] Sending to {recipient_id}")
        response = self.meta_api._make_request("POST", url, payload)
        if response.get("success"):
            message_id = response.get("data", {}).get("message_id")
            print(f"[SEND GENERIC TEMPLATE] Success! Message ID: {message_id}")
            return {
                "success": True,
                "message_id": message_id
            }
        else:
            print(f"[SEND GENERIC TEMPLATE] Failed! {response.get('error')}")
        return response

