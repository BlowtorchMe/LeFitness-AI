"""
Google Calendar integration
"""
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from app.config import settings
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import json
import os
import uuid


class GoogleCalendar:
    """Handles Google Calendar integration"""
    
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    
    def __init__(self):
        self.calendar_id = settings.google_calendar_id
        self.service = None
        # Only authenticate if credentials are provided
        if settings.google_calendar_id and (getattr(settings, 'google_client_config', None) or settings.google_service_account):
            self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google Calendar API"""
        try:
            # Check if credentials file exists
            creds = None
            if os.path.exists('token.json'):
                creds = Credentials.from_authorized_user_file('token.json', self.SCOPES)
            
            # If there are no (valid) credentials available, let the user log in
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    # Use service account or OAuth flow
                    if hasattr(settings, 'google_service_account') and settings.google_service_account:
                        # Service account authentication
                        from google.oauth2 import service_account
                        
                        # Check if google_service_account is a file path or JSON string
                        service_account_data = settings.google_service_account
                        
                        # Try to parse as JSON first (for Vercel environment variables)
                        try:
                            service_account_info = json.loads(service_account_data)
                            # If successful, it's a JSON string
                            creds = service_account.Credentials.from_service_account_info(
                                service_account_info,
                                scopes=self.SCOPES
                            )
                        except (json.JSONDecodeError, TypeError):
                            # If not valid JSON, treat as file path (for local development)
                            if os.path.exists(service_account_data):
                                creds = service_account.Credentials.from_service_account_file(
                                    service_account_data,
                                    scopes=self.SCOPES
                                )
                            else:
                                raise Exception(f"Google service account not found: {service_account_data}")
                    elif getattr(settings, 'google_client_config', None):
                        # OAuth flow (for first-time setup)
                        try:
                            client_config = json.loads(settings.google_client_config) if isinstance(settings.google_client_config, str) else settings.google_client_config
                            flow = Flow.from_client_config(
                                client_config,
                                self.SCOPES
                            )
                            flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
                            auth_url, _ = flow.authorization_url(prompt='consent')
                            # In production, this should be handled via web flow
                            raise Exception(f"Please visit this URL to authorize: {auth_url}")
                        except json.JSONDecodeError:
                            raise Exception("Invalid Google client config JSON")
                    else:
                        raise Exception("No Google credentials provided")
                
                # Save credentials for next run (only if not using service account)
                # Service accounts don't need token.json, only OAuth credentials do
                from google.oauth2 import service_account as sa_module
                if not isinstance(creds, sa_module.Credentials):
                    # Only save OAuth credentials, not service account credentials
                    try:
                        with open('token.json', 'w') as token:
                            token.write(creds.to_json())
                    except (OSError, AttributeError):
                        # Ignore if can't write (e.g., in Vercel read-only filesystem)
                        pass
            
            self.service = build('calendar', 'v3', credentials=creds)
        
        except Exception as e:
            # Fallback: use API key if available
            if hasattr(settings, 'google_api_key') and settings.google_api_key:
                self.service = build('calendar', 'v3', developerKey=settings.google_api_key)
            else:
                # In test mode or when credentials are not configured, allow None service
                if settings.use_mock_apis or settings.test_mode:
                    self.service = None
                else:
                    raise Exception(f"Google Calendar authentication failed: {str(e)}")
    
    def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        description: str = "",
        attendee_email: Optional[str] = None,
        location: str = ""
    ) -> Dict[str, any]:
        """
        Create a calendar event
        
        Args:
            summary: Event title
            start_time: Start datetime
            end_time: End datetime (defaults to start_time + 1 hour)
            description: Event description
            attendee_email: Email to invite
            location: Event location
        
        Returns:
            Dict with event info and success status
        """
        if not end_time:
            end_time = start_time + timedelta(hours=1)
        
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': settings.timezone or 'UTC',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': settings.timezone or 'UTC',
            },
            'location': location,
        }
        
        # Add attendee if email provided
        # Google Calendar will automatically send email confirmation to attendees
        if attendee_email:
            event['attendees'] = [{'email': attendee_email}]
        
        try:
            event_result = self.service.events().insert(
                calendarId=self.calendar_id,
                body=event,
                sendUpdates='all' if attendee_email else 'none'  # 'all' sends email to all attendees automatically
            ).execute()
            
            return {
                "success": True,
                "event_id": event_result.get('id'),
                "html_link": event_result.get('htmlLink'),
                "event": event_result
            }
        
        except HttpError as e:
            return {
                "success": False,
                "error": str(e),
                "error_details": e.error_details if hasattr(e, 'error_details') else None
            }
    
    def get_available_slots(
        self,
        date: datetime,
        duration_minutes: int = 60,
        working_hours: tuple = (9, 18)  # 9 AM to 6 PM
    ) -> List[Dict]:
        """
        Get available time slots for a date
        
        Args:
            date: Date to check
            duration_minutes: Duration of each slot
            working_hours: Tuple of (start_hour, end_hour)
        
        Returns:
            List of available time slots
        """
        try:
            # If no calendar service configured, return mock slots for testing
            if not self.service:
                slots = []
                current_time = date.replace(hour=working_hours[0], minute=0, second=0)
                end_time = date.replace(hour=working_hours[1], minute=0, second=0)
                while current_time + timedelta(minutes=duration_minutes) <= end_time:
                    slot_start = current_time
                    slot_end = current_time + timedelta(minutes=duration_minutes)
                    slots.append({
                        "start": slot_start.isoformat(),
                        "end": slot_end.isoformat(),
                        "display": slot_start.strftime("%H:%M")
                    })
                    current_time += timedelta(minutes=30)
                return slots

            # Get all events for the day
            time_min = date.replace(hour=working_hours[0], minute=0, second=0).isoformat() + 'Z'
            time_max = date.replace(hour=working_hours[1], minute=0, second=0).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Generate all possible slots
            slots = []
            current_time = date.replace(hour=working_hours[0], minute=0, second=0)
            end_time = date.replace(hour=working_hours[1], minute=0, second=0)
            
            while current_time + timedelta(minutes=duration_minutes) <= end_time:
                slot_start = current_time
                slot_end = current_time + timedelta(minutes=duration_minutes)
                
                # Check if slot conflicts with existing events
                is_available = True
                for event in events:
                    event_start = datetime.fromisoformat(
                        event['start'].get('dateTime', event['start'].get('date'))
                    )
                    event_end = datetime.fromisoformat(
                        event['end'].get('dateTime', event['end'].get('date'))
                    )
                    
                    if not (slot_end <= event_start or slot_start >= event_end):
                        is_available = False
                        break
                
                if is_available:
                    slots.append({
                        "start": slot_start.isoformat(),
                        "end": slot_end.isoformat(),
                        "display": slot_start.strftime("%H:%M")
                    })
                
                current_time += timedelta(minutes=30)  # 30-minute intervals
            
            return slots
        
        except HttpError as e:
            return []
    
    def delete_event(self, event_id: str) -> Dict[str, any]:
        """Delete a calendar event"""
        try:
            self.service.events().delete(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            
            return {"success": True}
        
        except HttpError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def update_event(
        self,
        event_id: str,
        updates: Dict
    ) -> Dict[str, any]:
        """Update a calendar event"""
        try:
            # Get existing event
            event = self.service.events().get(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            
            # Apply updates
            event.update(updates)
            
            # Update event
            updated_event = self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            
            return {
                "success": True,
                "event": updated_event
            }
        
        except HttpError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def watch_calendar(
        self,
        webhook_url: str,
        expiration_hours: int = 24
    ) -> Dict[str, any]:
        """
        Set up push notifications for calendar changes
        Google Calendar will send notifications to webhook_url when events change
        
        Args:
            webhook_url: Your webhook endpoint URL (e.g., https://yourdomain.com/webhooks/calendar)
            expiration_hours: How long the watch should last (max 7 days)
        
        Returns:
            Dict with channel info and expiration
        """
        try:
            # Generate unique channel ID
            channel_id = str(uuid.uuid4())
            
            # Calculate expiration time (in milliseconds)
            expiration_ms = int((datetime.utcnow() + timedelta(hours=expiration_hours)).timestamp() * 1000)
            
            # Set up watch
            watch_request = {
                'id': channel_id,
                'type': 'web_hook',
                'address': webhook_url,
                'expiration': expiration_ms
            }
            
            channel = self.service.events().watch(
                calendarId=self.calendar_id,
                body=watch_request
            ).execute()
            
            return {
                "success": True,
                "channel_id": channel.get('id'),
                "resource_id": channel.get('resourceId'),
                "expiration": channel.get('expiration')
            }
        
        except HttpError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def stop_watch(self, channel_id: str, resource_id: str) -> Dict[str, any]:
        """Stop a calendar watch"""
        try:
            self.service.channels().stop(
                body={
                    'id': channel_id,
                    'resourceId': resource_id
                }
            ).execute()
            
            return {"success": True}
        
        except HttpError as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_recent_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        max_results: int = 50
    ) -> List[Dict]:
        """
        Get recent events from calendar
        
        Args:
            start_time: Start time to search from (defaults to 1 hour ago)
            end_time: End time to search to (defaults to 30 days from now)
            max_results: Maximum number of events to return
        
        Returns:
            List of event dictionaries
        """
        try:
            if not start_time:
                start_time = datetime.utcnow() - timedelta(hours=1)
            if not end_time:
                end_time = datetime.utcnow() + timedelta(days=30)
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_time.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            return events_result.get('items', [])
        
        except HttpError as e:
            return []
    
    def get_event_by_id(self, event_id: str) -> Optional[Dict]:
        """Get a specific event by ID"""
        try:
            event = self.service.events().get(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            return event
        except HttpError as e:
            return None

