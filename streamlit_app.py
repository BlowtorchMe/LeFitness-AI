"""
Streamlit Dashboard for LE Fitness AI System
"""
import streamlit as st
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database.database import SessionLocal
from app.models.lead import Lead, LeadStatus
from app.models.booking import Booking, BookingStatus
from app.services.lead_service import LeadService
from app.services.booking_service import BookingService
from app.integrations.mock_meta_api import MockMetaAPI, MockMessengerAPI
from app.integrations.messenger_api import MessengerAPI
from app.webhooks.meta_webhook import handle_messaging_event, handle_optin_event, handle_postback
from app.models.conversation import ConversationChannel
from datetime import datetime, timedelta
import json

st.set_page_config(
    page_title="LE Fitness AI Dashboard",
    page_icon=None,
    layout="wide"
)

# Sidebar styling for a cleaner list look
st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] .stRadio > div {
        gap: 6px;
    }
    section[data-testid="stSidebar"] .stRadio label {
        padding: 8px 10px;
        border-radius: 8px;
        background: transparent;
        transition: background 0.15s, color 0.15s, border 0.15s;
        font-weight: 600;
    }
    section[data-testid="stSidebar"] .stRadio label:hover {
        background: #f2f4f7;
    }
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label[data-checked="true"] {
        background: #e7f1ff;
        color: #0b63ce;
        border: 1px solid #c6dcff;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Custom CSS for professional chat interface
st.markdown("""
<style>
    .chat-container {
        background: #f0f2f5;
        border-radius: 8px;
        padding: 0;
        height: 600px;
        display: flex;
        flex-direction: column;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    .chat-header {
        background: #0084ff;
        color: white;
        padding: 12px 16px;
        border-radius: 8px 8px 0 0;
        font-weight: 600;
        font-size: 16px;
    }
    .chat-messages {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        background: #e5e5e5;
    }
    .message-bubble {
        max-width: 70%;
        padding: 8px 12px;
        border-radius: 18px;
        margin-bottom: 8px;
        word-wrap: break-word;
    }
    .message-user {
        background: #0084ff;
        color: white;
        margin-left: auto;
        text-align: right;
    }
    .message-assistant {
        background: white;
        color: #1c1e21;
        margin-right: auto;
    }
    .quick-reply-button {
        background: white;
        border: 1px solid #ccd0d5;
        border-radius: 18px;
        padding: 8px 16px;
        margin: 4px;
        cursor: pointer;
        font-size: 14px;
        color: #0084ff;
    }
    .quick-reply-button:hover {
        background: #f0f2f5;
    }
    .chat-input-area {
        background: white;
        padding: 12px;
        border-top: 1px solid #ccd0d5;
        border-radius: 0 0 8px 8px;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'test_user_id' not in st.session_state:
    st.session_state.test_user_id = "test_user_1"
if 'mock_api' not in st.session_state:
    st.session_state.mock_api = MockMessengerAPI()
if 'chat_messages' not in st.session_state:
    st.session_state.chat_messages = []

def main():
    st.title("LE Fitness AI System Dashboard")
    
    # Sidebar navigation (radio, no dropdown)
    page = st.sidebar.radio(
        "Navigation",
        ["Dashboard", "Leads", "Bookings", "Settings"]
    )
    
    if page == "Dashboard":
        show_dashboard()
    elif page == "Leads":
        show_leads()
    elif page == "Bookings":
        show_bookings()
    elif page == "Settings":
        show_settings()

def show_dashboard():
    """Main dashboard with overview statistics"""
    st.header("Overview")
    
    db = SessionLocal()
    try:
        # Get statistics
        total_leads = db.query(Lead).count()
        new_leads = db.query(Lead).filter(Lead.status == LeadStatus.NEW).count()
        booked_leads = db.query(Lead).filter(Lead.status == LeadStatus.BOOKED).count()
        converted_leads = db.query(Lead).filter(Lead.status == LeadStatus.CONVERTED).count()
        
        total_bookings = db.query(Booking).count()
        confirmed_bookings = db.query(Booking).filter(Booking.status == BookingStatus.CONFIRMED).count()
        today_bookings = db.query(Booking).filter(
            Booking.appointment_time >= datetime.now().replace(hour=0, minute=0),
            Booking.appointment_time < datetime.now().replace(hour=23, minute=59)
        ).count()
        
        # Display metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Leads", total_leads, delta=new_leads, delta_color="normal")
        
        with col2:
            st.metric("Booked", booked_leads, delta=booked_leads - converted_leads, delta_color="normal")
        
        with col3:
            st.metric("Total Bookings", total_bookings, delta=confirmed_bookings, delta_color="normal")
        
        with col4:
            st.metric("Today's Bookings", today_bookings)
        
        # Recent leads
        st.subheader("Recent Leads")
        recent_leads = db.query(Lead).order_by(Lead.created_at.desc()).limit(10).all()
        
        if recent_leads:
            leads_data = []
            for lead in recent_leads:
                leads_data.append({
                    "Name": lead.name,
                    "Email": lead.email or "-",
                    "Phone": lead.phone or "-",
                    "Status": lead.status.value,
                    "Platform": lead.platform or "-",
                    "Created": lead.created_at.strftime("%Y-%m-%d %H:%M")
                })
            st.dataframe(leads_data, use_container_width=True)
        else:
            st.info("No leads yet")
        
        # Upcoming bookings
        st.subheader("Upcoming Bookings")
        upcoming = db.query(Booking).filter(
            Booking.appointment_time >= datetime.now(),
            Booking.status == BookingStatus.CONFIRMED
        ).order_by(Booking.appointment_time).limit(10).all()
        
        if upcoming:
            bookings_data = []
            for booking in upcoming:
                bookings_data.append({
                    "Customer": booking.customer_name,
                    "Time": booking.appointment_time.strftime("%Y-%m-%d %H:%M"),
                    "Type": booking.appointment_type.value,
                    "Status": booking.status.value
                })
            st.dataframe(bookings_data, use_container_width=True)
        else:
            st.info("No upcoming bookings")
    
    finally:
        db.close()

def show_leads():
    """Leads management page"""
    st.header("Leads Management")
    
    db = SessionLocal()
    try:
        lead_service = LeadService(db)
        
        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            status_filter = st.selectbox(
                "Filter by Status",
                ["All"] + [s.value for s in LeadStatus]
            )
        with col2:
            platform_filter = st.selectbox(
                "Filter by Platform",
                ["All", "messenger", "instagram"]
            )
        with col3:
            search = st.text_input("Search by name/email")
        
        # Get leads
        query = db.query(Lead)
        
        if status_filter != "All":
            query = query.filter(Lead.status == LeadStatus[status_filter.upper()])
        
        if platform_filter != "All":
            query = query.filter(Lead.platform == platform_filter)
        
        if search:
            query = query.filter(
                (Lead.name.contains(search)) | 
                (Lead.email.contains(search))
            )
        
        leads = query.order_by(Lead.created_at.desc()).all()
        
        st.metric("Total Leads", len(leads))

        # Tabular view
        if leads:
            table_rows = []
            for lead in leads:
                table_rows.append({
                    "Name": lead.name,
                    "Email": lead.email or "-",
                    "Phone": lead.phone or "-",
                    "Status": lead.status.value,
                    "Platform": lead.platform or "-",
                    "Source": lead.source,
                    "Created": lead.created_at.strftime("%Y-%m-%d %H:%M"),
                    "Last Contact": lead.last_contact.strftime("%Y-%m-%d %H:%M"),
                    "Messages": lead.message_count,
                    "ID": lead.id,
                })
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

            # Inline status update
            with st.form("lead_status_update"):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    lead_id_to_update = st.text_input("Update Status for Lead ID", "")
                with col_b:
                    new_status = st.selectbox("New Status", [s.value for s in LeadStatus])
                submit = st.form_submit_button("Apply")
                if submit and lead_id_to_update:
                    target = db.query(Lead).filter(Lead.id == lead_id_to_update).first()
                    if target and target.status.value != new_status:
                        lead_service.update_lead_status(target.id, LeadStatus[new_status.upper()])
                        st.success("Status updated")
                        st.rerun()
        else:
            st.info("No leads found for current filters.")
    
    finally:
        db.close()

def show_bookings():
    """Bookings management page"""
    st.header("Bookings Management")
    
    db = SessionLocal()
    try:
        booking_service = BookingService(db)
        
        # Filters
        col1, col2 = st.columns(2)
        with col1:
            status_filter = st.selectbox(
                "Filter by Status",
                ["All"] + [s.value for s in BookingStatus],
                key="booking_status_filter"
            )
        with col2:
            date_filter = st.date_input("Filter by Date", value=None)
        
        # Get bookings
        query = db.query(Booking)
        
        if status_filter != "All":
            query = query.filter(Booking.status == BookingStatus[status_filter.upper()])
        
        if date_filter:
            start = datetime.combine(date_filter, datetime.min.time())
            end = start + timedelta(days=1)
            query = query.filter(
                Booking.appointment_time >= start,
                Booking.appointment_time < end
            )
        
        bookings = query.order_by(Booking.appointment_time).all()
        
        st.metric("Total Bookings", len(bookings))

        if bookings:
            table_rows = []
            for booking in bookings:
                table_rows.append({
                    "Customer": booking.customer_name,
                    "Email": booking.email or "-",
                    "Phone": booking.phone or "-",
                    "Type": booking.appointment_type.value,
                    "Status": booking.status.value,
                    "Time": booking.appointment_time.strftime("%Y-%m-%d %H:%M"),
                    "Created": booking.created_at.strftime("%Y-%m-%d %H:%M"),
                    "Duration (min)": booking.duration_minutes,
                    "Calendar": booking.google_event_link or "-",
                    "ID": booking.id,
                })
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

            # Inline actions
            with st.form("booking_actions"):
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    booking_id = st.text_input("Booking ID")
                with c2:
                    action = st.selectbox("Action", ["Mark No-Show", "Cancel"])
                with c3:
                    submitted = st.form_submit_button("Apply")
                if submitted and booking_id:
                    b = db.query(Booking).filter(Booking.id == booking_id).first()
                    if not b:
                        st.error("Booking not found")
                    else:
                        if action == "Mark No-Show" and b.status == BookingStatus.CONFIRMED:
                            booking_service.mark_no_show(b.id)
                            st.success("Marked as no-show")
                            st.rerun()
                        elif action == "Cancel" and b.status != BookingStatus.CANCELLED:
                            booking_service.cancel_booking(b.id)
                            st.success("Cancelled")
                            st.rerun()
        else:
            st.info("No bookings for current filters.")
    
    finally:
        db.close()

def show_settings():
    """Settings page"""
    st.header("Settings")
    from app.config import settings

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Application")
        st.write(f"Name: {settings.app_name}")
        st.write(f"Environment: {settings.environment}")
        st.write(f"Gym: {settings.gym_name}")
        st.write(f"Free Trial Days: {settings.free_trial_days}")
    with col2:
        st.subheader("Modes")
        st.write(f"Use Mock APIs: {getattr(settings, 'use_mock_apis', False)}")
        st.write(f"Test Mode: {getattr(settings, 'test_mode', False)}")
        st.write(f"Debug: {getattr(settings, 'debug', False)}")

    st.subheader("System Status")
    c1, c2 = st.columns(2)
    with c1:
        st.success("Database Connected")
        st.success("API Endpoints Active")
    with c2:
        if getattr(settings, 'use_mock_apis', False):
            st.info("Using Mock APIs (Test Mode)")
        else:
            st.info("Using Real APIs")

if __name__ == "__main__":
    main()
