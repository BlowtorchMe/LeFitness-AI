"""
META (Facebook/Instagram) API integration
"""
import requests
from app.config import settings
from typing import Dict, Optional, List


class MetaAPI:
    """Handles META platform integrations"""
    
    def __init__(self):
        self.app_id = settings.meta_app_id
        self.app_secret = settings.meta_app_secret
        self.access_token = settings.meta_access_token
        self.base_url = "https://graph.facebook.com/v18.0"
    
    def create_ad(self, ad_data: Dict) -> Dict[str, any]:
        """
        Create an advertisement via META Ads Manager
        
        Args:
            ad_data: Advertisement data (campaign, ad set, ad details)
        
        Returns:
            Dict with ad creation result
        """
        # TODO: Implement full ad creation flow
        # This is a placeholder - actual implementation requires:
        # 1. Create Campaign
        # 2. Create Ad Set
        # 3. Create Ad Creative
        # 4. Create Ad
        
        try:
            # Example: Create ad creative
            creative_url = f"{self.base_url}/act_{self.app_id}/adcreatives"
            response = requests.post(
                creative_url,
                params={"access_token": self.access_token},
                json=ad_data
            )
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "creative_id": response.json().get("id")
                }
            else:
                return {
                    "success": False,
                    "error": response.text
                }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def send_messenger_message(self, recipient_id: str, message: str) -> Dict[str, any]:
        """
        Send message via Messenger API
        
        Args:
            recipient_id: Facebook user ID
            message: Message text
        
        Returns:
            Dict with send result
        """
        if not self.access_token:
            error_msg = "META_ACCESS_TOKEN not set - cannot send messages"
            print(f"[ERROR] {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
        
        url = f"{self.base_url}/me/messages"
        
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": message},
            "messaging_type": "RESPONSE"
        }
        
        try:
            print(f"[SEND MESSAGE] Sending to {recipient_id}: {message[:50]}...")
            response = requests.post(
                url,
                params={"access_token": self.access_token},
                json=payload
            )
            
            print(f"[SEND MESSAGE] Response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                message_id = result.get("message_id")
                print(f"[SEND MESSAGE] Success! Message ID: {message_id}")
                return {
                    "success": True,
                    "message_id": message_id
                }
            else:
                error_text = response.text
                print(f"[SEND MESSAGE] Failed! Status {response.status_code}: {error_text}")
                return {
                    "success": False,
                    "error": error_text,
                    "status_code": response.status_code
                }
        
        except Exception as e:
            error_msg = str(e)
            print(f"[SEND MESSAGE] Exception: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
    
    def get_user_profile(self, user_id: str, platform: str = "facebook") -> Dict[str, any]:
        """
        Get user profile information from META API
        
        Args:
            user_id: Facebook/Instagram user ID
            platform: "facebook" or "instagram"
        
        Returns:
            Dict with user profile info (name, email, etc.)
        """
        try:
            if platform == "instagram":
                # Instagram uses different endpoint
                url = f"{self.base_url}/{user_id}"
                # Instagram has limited fields available
                fields = "username"  # Instagram only provides username by default
            else:
                # Facebook Messenger
                url = f"{self.base_url}/{user_id}"
                # Facebook provides more fields
                fields = "first_name,last_name,email,profile_pic"
            
            response = self._make_request("GET", url, {"fields": fields})
            
            if response.get("success"):
                data = response.get("data", {})
                
                # Format response consistently
                profile = {
                    "id": user_id,
                    "first_name": data.get("first_name") or data.get("username", "").split()[0] if data.get("username") else "",
                    "last_name": data.get("last_name", ""),
                    "full_name": f"{data.get('first_name', '')} {data.get('last_name', '')}".strip() or data.get("username", ""),
                    "email": data.get("email", ""),
                    "username": data.get("username", ""),
                    "profile_pic": data.get("profile_pic", "")
                }
                
                return profile
            
            return {}
        
        except Exception as e:
            return {}
    
    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """
        Verify webhook for META platform
        
        Args:
            mode: Verification mode
            token: Verification token
            challenge: Challenge string
        
        Returns:
            Challenge string if verified, None otherwise
        """
        # Check mode and token match
        if mode != "subscribe":
            print(f"[VERIFY] Invalid mode: {mode} (expected 'subscribe')")
            return None
        
        if not settings.meta_verify_token:
            print("[VERIFY] META_VERIFY_TOKEN not set in environment")
            return None
        
        if token != settings.meta_verify_token:
            print(f"[VERIFY] Token mismatch: received '{token}', expected '{settings.meta_verify_token}'")
            return None
        
        print("[VERIFY] Verification successful")
        return challenge
    
    def _make_request(self, method: str, url: str, payload: Dict = None) -> Dict[str, any]:
        """
        Internal method to make API requests
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: API endpoint URL
            payload: Request payload (for POST) or query params (for GET)
        
        Returns:
            Dict with response data
        """
        if not self.access_token:
            error_msg = "META_ACCESS_TOKEN not set - cannot make API requests"
            print(f"[ERROR] {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
        
        try:
            params = {"access_token": self.access_token}
            
            if method.upper() == "POST":
                response = requests.post(
                    url,
                    params=params,
                    json=payload or {}
                )
            else:
                # For GET, merge payload into params
                if payload:
                    params.update(payload)
                response = requests.get(url, params=params)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "data": response.json()
                }
            else:
                error_text = response.text
                print(f"[API REQUEST] Failed! Status {response.status_code}: {error_text}")
                return {
                    "success": False,
                    "error": error_text,
                    "status_code": response.status_code
                }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

