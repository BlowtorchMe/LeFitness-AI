"""
Streamlit Chat Interface (User-side emulator)
Run with: streamlit run streamlit_chat.py
"""
import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database.database import SessionLocal
from app.services.lead_service import LeadService
from app.integrations.mock_meta_api import MockMessengerAPI
from app.webhooks.meta_webhook import (
    handle_messaging_event,
    handle_optin_event,
    handle_postback,
    messenger_api,
)
from app.models.conversation import ConversationChannel

st.set_page_config(
    page_title="LE Fitness Chat",
    page_icon=None,
    layout="centered"  # disable wide mode by default
)

# Messenger-like CSS (clean, no emojis)
st.markdown(
    """
    <style>
    body { background: #f0f2f5; }
    .chat-shell {
        max-width: 960px;
        margin: 0 auto;
    }
    .chat-header {
        background: #0084ff;
        color: #fff;
        padding: 12px 16px;
        border-radius: 12px 12px 0 0;
        font-weight: 600;
        font-size: 16px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
    }
    .chat-window {
        background: #e5e5ea;
        padding: 16px;
        border-radius: 0 0 12px 12px;
        min-height: 520px;
        box-shadow: 0 8px 20px rgba(0,0,0,0.08);
    }
    .stChatMessage {
        padding: 4px 0;
    }
    .stChatMessage div[data-testid="stChatMessageContent"] {
        padding: 8px 12px;
        border-radius: 16px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.06);
    }
    .stChatMessage[data-testid="stChatMessage-user"] div[data-testid="stChatMessageContent"] {
        background: #0084ff;
        color: #fff;
        margin-left: 30%;
    }
    .stChatMessage[data-testid="stChatMessage-assistant"] div[data-testid="stChatMessageContent"] {
        background: #fff;
        color: #1c1e21;
        margin-right: 30%;
    }
    .quick-replies {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 6px;
    }
    .quick-button {
        background: #fff;
        border: 1px solid #d1d5db;
        border-radius: 16px;
        padding: 8px 12px;
        color: #0084ff;
        font-size: 13px;
        cursor: pointer;
        width: 100%;
    }
    .quick-button:hover { background: #f0f2f5; }
    .action-row {
        display: flex;
        gap: 8px;
        margin-top: 6px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize session state
if "test_user_id" not in st.session_state:
    st.session_state.test_user_id = "test_user_1"


def main():
    st.markdown(
        "<div style='height: 8px;'></div>",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        test_user_id = st.text_input(
            "User ID",
            value=st.session_state.test_user_id,
            key="test_user_input",
            label_visibility="collapsed",
            placeholder="Enter user ID to start",
        )
        st.session_state.test_user_id = test_user_id

    with col2:
        if st.button("Start Chat", use_container_width=True, type="primary"):
            if not test_user_id:
                st.warning("Enter user ID first")
            else:
                from app.integrations.mock_meta_api import MockMetaAPI

                mock_meta = MockMetaAPI()
                mock_meta.update_mock_user(
                    test_user_id,
                    first_name="Test",
                    last_name="User",
                    name="Test User",
                    email=f"{test_user_id}@example.com",
                )
                mock_event = {
                    "sender": {"id": test_user_id},
                    "optin": {"ref": "test_ad"},
                }
                try:
                    import asyncio

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        handle_optin_event(mock_event, ConversationChannel.MESSENGER)
                    )
                    loop.close()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")

    with col3:
        if st.button("Clear", use_container_width=True):
            messenger_api.clear_sent_messages()
            st.rerun()

    st.markdown("---")

    db = SessionLocal()
    try:
        lead_service = LeadService(db)
        lead = (
            lead_service.get_lead_by_messenger_id(test_user_id)
            if test_user_id
            else None
        )

        sent_messages = messenger_api.get_sent_messages(test_user_id) if test_user_id else []

        # Lead info at top
        if lead:
            with st.container():
                st.markdown(
                    f"""
                    <div style="background:#0e1624;border:1px solid #1f2a3a;border-radius:10px;padding:12px 14px;margin-bottom:10px;">
                        <div style="font-weight:700;color:#e4e6eb;">Lead: {lead.name or 'N/A'}</div>
                        <div style="color:#b0b3b8;font-size:13px;">Email: {lead.email or 'N/A'} | Phone: {lead.phone or 'N/A'}</div>
                        <div style="color:#b0b3b8;font-size:13px;">Status: {lead.status.value} | State: {lead.conversation_state} | Messages: {lead.message_count}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        if not sent_messages and not lead:
            st.info("Click 'Start Chat' to begin conversation. If nothing appears, confirm USE_MOCK_APIS=true and TEST_MODE=true in .env and restart backend.")
        else:
            for msg in sent_messages[-30:]:
                msg_type = msg.get("type")
                if msg_type == "text":
                    with st.chat_message("assistant"):
                        st.write(msg.get("message", ""))

                elif msg_type == "quick_replies":
                    with st.chat_message("assistant"):
                        st.write(msg.get("message", ""))
                        replies = msg.get("quick_replies", [])
                        if replies:
                            cols = st.columns(min(len(replies), 3))
                            for idx, reply in enumerate(replies):
                                with cols[idx % 3]:
                                    if st.button(
                                        reply.get("title", ""),
                                        key=f"qr_{msg.get('timestamp', 0)}_{idx}_{reply.get('payload', '')}",
                                        use_container_width=True,
                                    ):
                                        import asyncio

                                        loop = asyncio.new_event_loop()
                                        asyncio.set_event_loop(loop)
                                        loop.run_until_complete(
                                            handle_postback(
                                                test_user_id,
                                                reply.get("payload"),
                                                ConversationChannel.MESSENGER,
                                            )
                                        )
                                        loop.close()
                                        st.rerun()

                elif msg_type == "button_template":
                    with st.chat_message("assistant"):
                        st.write(msg.get("text", ""))
                        for btn in msg.get("buttons", []):
                            if btn.get("type") == "postback":
                                if st.button(
                                    btn.get("title", ""),
                                    key=f"btn_{msg.get('timestamp', 0)}_{btn.get('payload', '')}",
                                    use_container_width=True,
                                ):
                                    import asyncio

                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    loop.run_until_complete(
                                        handle_postback(
                                            test_user_id,
                                            btn.get("payload"),
                                            ConversationChannel.MESSENGER,
                                        )
                                    )
                                    loop.close()
                                    st.rerun()
                            elif btn.get("type") == "web_url":
                                st.link_button(btn.get("title", ""), btn.get("url", "#"))

        user_message = st.chat_input("Type a message...", key="user_message_input")

        if user_message:
            with st.chat_message("user"):
                st.write(user_message)

            mock_event = {
                "sender": {"id": test_user_id},
                "message": {"text": user_message},
            }
            try:
                import asyncio

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    handle_messaging_event(
                        mock_event, ConversationChannel.MESSENGER
                    )
                )
                loop.close()
                st.rerun()
            except Exception as e:
                st.error(f"Error: {str(e)}")

        if lead:
            with st.expander("Lead Details"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Name:** {lead.name or 'N/A'}")
                    st.write(f"**Email:** {lead.email or 'N/A'}")
                    st.write(f"**Phone:** {lead.phone or 'N/A'}")
                with col2:
                    st.write(f"**Status:** {lead.status.value}")
                    st.write(f"**State:** {lead.conversation_state}")
                    st.write(f"**Messages:** {lead.message_count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

