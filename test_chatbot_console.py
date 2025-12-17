"""
Console-based chatbot tester
Simulates user messages and displays bot responses
Does not interfere with Facebook webhook integration
"""
import asyncio
import sys
import os
from datetime import datetime
from typing import List, Dict

# Force mock APIs BEFORE any imports that use them
from app.config import settings
settings.use_mock_apis = True
settings.test_mode = True

from app.webhooks.meta_webhook import handle_messaging_event, handle_optin_event
from app.models.conversation import ConversationChannel
from app.database.database import get_db, SessionLocal

# Store console messages for display
_console_messages: List[Dict] = []

# Store last quick replies/buttons shown to user (for number input conversion)
_last_quick_replies: List[Dict] = []
_last_buttons: List[Dict] = []


def create_mock_event(message_text: str, sender_id: str = "test_user_123", is_postback: bool = False, payload: str = "") -> dict:
    """Create a mock Facebook webhook event for testing"""
    if is_postback:
        # Create postback event (button click)
        return {
            "sender": {"id": sender_id},
            "recipient": {"id": "page_id"},
            "postback": {
                "payload": payload,
                "title": message_text  # Optional title
            },
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
    else:
        # Create text message event
        return {
            "sender": {"id": sender_id},
            "recipient": {"id": "page_id"},
            "message": {
                "mid": f"mid.{datetime.now().timestamp()}",
                "text": message_text,
                "is_echo": False  # Important: not an echo
            },
            "timestamp": int(datetime.now().timestamp() * 1000)
        }


def capture_bot_message(message_type: str, message: str, **kwargs):
    """Capture bot messages for console display"""
    _console_messages.append({
        "type": message_type,
        "message": message,
        "timestamp": datetime.now().isoformat(),
        **kwargs
    })


def display_bot_responses():
    """Display captured bot responses"""
    if not _console_messages:
        return
    
    for msg in _console_messages:
        msg_type = msg.get("type")
        message = msg.get("message", "")
        
        if msg_type == "text":
            print(f"Bot:   {message}")
        elif msg_type == "quick_replies":
            print(f"Bot:   {message}")
            replies = msg.get("quick_replies", [])
            if replies:
                print("  Options:")
                for i, reply in enumerate(replies, 1):
                    print(f"    {i}. {reply.get('title', '')}")
        elif msg_type == "button_template":
            print(f"Bot:   {message}")
            buttons = msg.get("buttons", [])
            if buttons:
                print("  Buttons:")
                for i, btn in enumerate(buttons, 1):
                    print(f"    {i}. {btn.get('title', '')}")
        elif msg_type == "generic_template":
            print(f"Bot:   {message}")
            elements = msg.get("elements", [])
            if elements:
                print("  Items:")
                for i, elem in enumerate(elements, 1):
                    print(f"    {i}. {elem.get('title', '')}")
    
    # Clear messages after displaying
    _console_messages.clear()


def setup_console_patching():
    """Setup console patching for messenger API"""
    from app.webhooks import meta_webhook
    from app.integrations import mock_meta_api
    
    # Store originals
    original_send = meta_webhook.messenger_api.send_message
    original_quick = meta_webhook.messenger_api.send_quick_replies
    original_button = meta_webhook.messenger_api.send_button_template
    original_get_profile = meta_webhook.meta_api.get_user_profile
    
    # Console-friendly replacements
    def console_send_message(recipient_id: str, message: str):
        if message and message.strip():  # Only capture non-empty messages
            capture_bot_message("text", message)
        return {"success": True, "message_id": "console_msg"}
    
    def console_send_quick_replies(recipient_id: str, message: str, quick_replies: List):
        global _last_quick_replies
        _last_quick_replies = quick_replies  # Store for number input conversion
        capture_bot_message("quick_replies", message, quick_replies=quick_replies)
        return {"success": True, "message_id": "console_quick"}
    
    def console_send_button_template(recipient_id: str, text: str, buttons: List):
        global _last_buttons
        _last_buttons = buttons  # Store for number input conversion
        capture_bot_message("button_template", text, buttons=buttons)
        return {"success": True, "message_id": "console_button"}
    
    def console_get_user_profile(user_id: str, platform: str = "facebook"):
        # Use mock API to avoid real API calls
        mock_api = mock_meta_api.MockMetaAPI()
        return mock_api.get_user_profile(user_id, platform)
    
    # Patch for this test
    meta_webhook.messenger_api.send_message = console_send_message
    meta_webhook.messenger_api.send_quick_replies = console_send_quick_replies
    meta_webhook.messenger_api.send_button_template = console_send_button_template
    meta_webhook.meta_api.get_user_profile = console_get_user_profile
    
    # Also patch ConversationFlow's messenger_api by patching the MessengerAPI class
    # This ensures any new instances created will use our console functions
    from app.integrations import messenger_api as messenger_api_module
    original_messenger_send = messenger_api_module.MessengerAPI.send_message
    original_messenger_quick = messenger_api_module.MessengerAPI.send_quick_replies
    original_messenger_button = messenger_api_module.MessengerAPI.send_button_template
    
    # Patch class methods so all instances use console functions (with self parameter)
    def patched_send_message(self, recipient_id: str, message: str):
        return console_send_message(recipient_id, message)
    
    def patched_send_quick_replies(self, recipient_id: str, message: str, quick_replies: List):
        return console_send_quick_replies(recipient_id, message, quick_replies)
    
    def patched_send_button_template(self, recipient_id: str, text: str, buttons: List):
        return console_send_button_template(recipient_id, text, buttons)
    
    messenger_api_module.MessengerAPI.send_message = patched_send_message
    messenger_api_module.MessengerAPI.send_quick_replies = patched_send_quick_replies
    messenger_api_module.MessengerAPI.send_button_template = patched_send_button_template
    
    return {
        "original_send": original_send,
        "original_quick": original_quick,
        "original_button": original_button,
        "original_get_profile": original_get_profile,
        "original_messenger_send": original_messenger_send,
        "original_messenger_quick": original_messenger_quick,
        "original_messenger_button": original_messenger_button
    }


def restore_console_patching(originals):
    """Restore original functions"""
    from app.webhooks import meta_webhook
    from app.integrations import messenger_api as messenger_api_module
    
    meta_webhook.messenger_api.send_message = originals["original_send"]
    meta_webhook.messenger_api.send_quick_replies = originals["original_quick"]
    meta_webhook.messenger_api.send_button_template = originals["original_button"]
    meta_webhook.meta_api.get_user_profile = originals["original_get_profile"]
    
    # Restore MessengerAPI class methods
    if "original_messenger_send" in originals:
        messenger_api_module.MessengerAPI.send_message = originals["original_messenger_send"]
        messenger_api_module.MessengerAPI.send_quick_replies = originals["original_messenger_quick"]
        messenger_api_module.MessengerAPI.send_button_template = originals["original_messenger_button"]


async def send_welcome_message(sender_id: str):
    """Send welcome message to simulate opt-in event (only if user doesn't exist)"""
    global _console_messages
    _console_messages = []
    
    try:
        # Check if user already exists - if so, don't send welcome, just continue conversation
        db = SessionLocal()
        from app.services.lead_service import LeadService
        lead_service = LeadService(db)
        existing_lead = lead_service.get_lead_by_messenger_id(sender_id)
        db.close()
        
        # If user exists, don't send welcome - just continue conversation
        if existing_lead:
            return
        
        originals = setup_console_patching()
        
        # Simulate opt-in event (like clicking an ad) - only for new users
        mock_optin_event = {
            "sender": {"id": sender_id},
            "recipient": {"id": "page_id"},
            "optin": {"ref": "console_test_ad"},
            "timestamp": int(datetime.now().timestamp() * 1000)
        }
        
        await handle_optin_event(mock_optin_event, ConversationChannel.MESSENGER)
        
        restore_console_patching(originals)
        
        # Display welcome message
        display_bot_responses()
        
    except Exception as e:
        print(f"✗ Error sending welcome: {e}")
        import traceback
        traceback.print_exc()


async def process_user_message(message: str, sender_id: str):
    """Process a user message and capture bot responses"""
    global _console_messages, _last_quick_replies, _last_buttons
    _console_messages = []  # Clear previous messages
    
    try:
        originals = setup_console_patching()
        
        # Check if user input is a number that corresponds to quick replies or buttons
        user_input_clean = message.strip()
        is_number = user_input_clean.isdigit()
        
        if is_number:
            num = int(user_input_clean)
            # Check if there are quick replies and number matches
            if _last_quick_replies and 1 <= num <= len(_last_quick_replies):
                number_index = num - 1  # Convert to 0-based index
                selected_reply = _last_quick_replies[number_index]
                payload = selected_reply.get("payload", "")
                if payload:
                    # Convert to postback event (simulate button click)
                    mock_event = create_mock_event(
                        selected_reply.get("title", message),
                        sender_id,
                        is_postback=True,
                        payload=payload
                    )
                    # Clear quick replies after selection
                    _last_quick_replies = []
                    await handle_messaging_event(mock_event, ConversationChannel.MESSENGER)
                    restore_console_patching(originals)
                    display_bot_responses()
                    return
            
            # Check if there are buttons and number matches
            elif _last_buttons and 1 <= num <= len(_last_buttons):
                number_index = num - 1
                selected_button = _last_buttons[number_index]
                payload = selected_button.get("payload", "")
                if payload:
                    # Convert to postback event (simulate button click)
                    mock_event = create_mock_event(
                        selected_button.get("title", message),
                        sender_id,
                        is_postback=True,
                        payload=payload
                    )
                    # Clear buttons after selection
                    _last_buttons = []
                    await handle_messaging_event(mock_event, ConversationChannel.MESSENGER)
                    restore_console_patching(originals)
                    display_bot_responses()
                    return
        
        # Regular text message (or number doesn't match any options)
        mock_event = create_mock_event(message, sender_id)
        await handle_messaging_event(mock_event, ConversationChannel.MESSENGER)
        
        restore_console_patching(originals)
        
        # Display responses
        display_bot_responses()
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


def print_banner():
    """Print welcome banner"""
    print("\n" + "="*60)
    print("  LE Fitness Chatbot - Console Tester")
    print("="*60)
    print("Type messages to test the chatbot")
    print("Commands:")
    print("  /new    - Start as new user (reset conversation)")
    print("  /user   - Show current user ID")
    print("  /quit   - Exit")
    print("")
    print("Note: This uses the same logic as Facebook webhook")
    print("      but displays responses in console instead of sending to Facebook")
    print("="*60 + "\n")


async def main():
    """Main console loop"""
    print_banner()
    
    sender_id = "test_user_123"
    print(f"Current test user ID: {sender_id}")
    print("Type '/new' to change user ID\n")
    
    # Check if user exists - if new, send welcome; if existing, continue conversation
    db = SessionLocal()
    from app.services.lead_service import LeadService
    lead_service = LeadService(db)
    existing_lead = lead_service.get_lead_by_messenger_id(sender_id)
    db.close()
    
    if not existing_lead:
        # New user - send welcome message
        await send_welcome_message(sender_id)
        print()  # Empty line after messages
    else:
        # Existing user - show continuation message
        print(f"Continuing conversation with: {existing_lead.name or sender_id}\n")
    
    while True:
        try:
            # Get user input
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            # Handle commands
            if user_input.lower() == "/quit":
                print("\nGoodbye!")
                break
            elif user_input.lower() == "/new":
                sender_id = f"test_user_{int(datetime.now().timestamp())}"
                print(f"\n✓ New user ID: {sender_id}")
                # Send welcome message for new user
                await send_welcome_message(sender_id)
                print()  # Empty line after messages
                continue
            elif user_input.lower() == "/user":
                print(f"\nCurrent user ID: {sender_id}\n")
                continue
            elif user_input.startswith("/"):
                print(f"Unknown command: {user_input}")
                print("Available: /new, /user, /quit\n")
                continue
            
            # Process message
            await process_user_message(user_input, sender_id)
            print()  # Empty line after response
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except EOFError:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\n✗ Unexpected error: {e}\n")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)

