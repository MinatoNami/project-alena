"""
Google Calendar API client wrapper
Handles authentication and calendar operations
"""

import os
import pickle
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class GoogleCalendarClient:
    """Client for interacting with Google Calendar API"""

    def __init__(
        self, credentials_path: Optional[str] = None, token_path: Optional[str] = None
    ):
        """
        Initialize the Google Calendar client

        Args:
            credentials_path: Path to credentials.json file
            token_path: Path to token cache file
        """
        # Hardcode secrets folder path relative to this module
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        secrets_dir = os.path.join(module_dir, "secrets")

        self.credentials_path = credentials_path or os.path.join(
            secrets_dir, "credentials.json"
        )
        self.token_path = token_path or os.path.join(secrets_dir, "token.json")
        self.timezone = os.getenv("CALENDAR_TIMEZONE", "UTC")
        self.service = None
        self._authenticate()

    def _authenticate(self) -> None:
        """Authenticate with Google Calendar API"""
        creds = None

        # Load token if it exists
        if os.path.exists(self.token_path):
            # Support both pickle and JSON token formats
            if self.token_path.endswith(".json"):
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            else:
                with open(self.token_path, "rb") as token:
                    creds = pickle.load(token)

        # If no valid credentials, create new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials for next run
            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            if self.token_path.endswith(".json"):
                with open(self.token_path, "w") as token:
                    token.write(creds.to_json())
            else:
                with open(self.token_path, "wb") as token:
                    pickle.dump(creds, token)

        self.service = build("calendar", "v3", credentials=creds)

    def list_events(
        self,
        calendar_id: str = "primary",
        start_date: str = None,
        end_date: str = None,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        List events from calendar within date range

        Args:
            calendar_id: Calendar ID (default: primary)
            start_date: Start date in ISO format (YYYY-MM-DD) in user's timezone
            end_date: End date in ISO format (YYYY-MM-DD) in user's timezone
            max_results: Maximum number of events to return

        Returns:
            List of events
        """
        try:
            from datetime import timedelta
            from zoneinfo import ZoneInfo

            # Get timezone offset from environment or use UTC
            tz_name = self.timezone if self.timezone != "UTC" else "UTC"

            # Convert dates to RFC3339 format if provided
            # Dates are provided in user's local timezone
            time_min = None
            time_max = None
            if start_date:
                # Handle both YYYY-MM-DD and full datetime strings
                # Strip 'Z' suffix if present and extract just the date part
                date_str = start_date.replace("Z", "").split("T")[0]
                # Parse as naive datetime in user's timezone
                date_obj = datetime.fromisoformat(date_str)
                # Subtract 1 day to expand search window
                date_obj = date_obj - timedelta(days=1)

                # Create timezone-aware datetime at midnight in user's timezone
                try:
                    tz = ZoneInfo(tz_name)
                    aware_dt = date_obj.replace(hour=0, minute=0, second=0, tzinfo=tz)
                except Exception:
                    # Fallback to UTC if timezone parsing fails
                    aware_dt = date_obj.replace(
                        hour=0, minute=0, second=0, tzinfo=ZoneInfo("UTC")
                    )

                # Convert to UTC
                utc_dt = aware_dt.astimezone(ZoneInfo("UTC"))
                time_min = utc_dt.isoformat().replace("+00:00", "Z")

            if end_date:
                # Handle both YYYY-MM-DD and full datetime strings
                # Strip 'Z' suffix if present and extract just the date part
                date_str = end_date.replace("Z", "").split("T")[0]
                # Parse as naive datetime in user's timezone
                date_obj = datetime.fromisoformat(date_str)
                # Add 1 day to expand search window
                date_obj = date_obj + timedelta(days=1)

                # Create timezone-aware datetime at end of day in user's timezone
                try:
                    tz = ZoneInfo(tz_name)
                    aware_dt = date_obj.replace(
                        hour=23, minute=59, second=59, tzinfo=tz
                    )
                except Exception:
                    # Fallback to UTC if timezone parsing fails
                    aware_dt = date_obj.replace(
                        hour=23, minute=59, second=59, tzinfo=ZoneInfo("UTC")
                    )

                # Convert to UTC
                utc_dt = aware_dt.astimezone(ZoneInfo("UTC"))
                time_max = utc_dt.isoformat().replace("+00:00", "Z")

            events_result = (
                self.service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                    timeZone=self.timezone,
                )
                .execute()
            )

            log_msg = f"Google Calendar API list query - calendarId={calendar_id}, timeMin={time_min}, timeMax={time_max}, results={len(events_result.get('items', []))} events"
            logger.info(log_msg)
            print(f"[CALENDAR_CLIENT] {log_msg}")

            events = events_result.get("items", [])
            return self._format_events(events)

        except HttpError as error:
            return {"error": f"API error: {error}"}

    def create_event(
        self,
        title: str,
        start_time: str,
        end_time: str,
        calendar_id: str = "primary",
        description: str = None,
        attendees: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new event in the calendar

        Args:
            title: Event title
            start_time: Start time in ISO format (YYYY-MM-DDTHH:MM:SS)
            end_time: End time in ISO format (YYYY-MM-DDTHH:MM:SS)
            calendar_id: Calendar ID (default: primary)
            description: Event description
            attendees: List of attendee emails

        Returns:
            Created event details
        """
        try:
            event = {
                "summary": title,
                "start": {"dateTime": start_time, "timeZone": self.timezone},
                "end": {"dateTime": end_time, "timeZone": self.timezone},
            }

            if description:
                event["description"] = description

            if attendees:
                event["attendees"] = [{"email": email} for email in attendees]

            created_event = (
                self.service.events()
                .insert(calendarId=calendar_id, body=event)
                .execute()
            )

            log_msg = f"Google Calendar API create event - calendarId={calendar_id}, eventId={created_event.get('id')}, summary={title}"
            logger.info(log_msg)
            print(f"[CALENDAR_CLIENT] {log_msg}")

            return self._format_event(created_event)

        except HttpError as error:
            return {"error": f"API error: {error}"}

    def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        title: str = None,
        description: str = None,
        start_time: str = None,
        end_time: str = None,
    ) -> Dict[str, Any]:
        """
        Update an existing event

        Args:
            event_id: ID of the event to update
            calendar_id: Calendar ID (default: primary)
            title: New event title
            description: New description
            start_time: New start time
            end_time: New end time

        Returns:
            Updated event details
        """
        try:
            # Get existing event
            event = (
                self.service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )

            log_msg = f"Google Calendar API get event - calendarId={calendar_id}, eventId={event_id}"
            logger.info(log_msg)
            print(f"[CALENDAR_CLIENT] {log_msg}")

            # Update fields if provided
            if title:
                event["summary"] = title
            if description is not None:
                event["description"] = description
            if start_time:
                event["start"] = {"dateTime": start_time, "timeZone": self.timezone}
            if end_time:
                event["end"] = {"dateTime": end_time, "timeZone": self.timezone}

            updated_event = (
                self.service.events()
                .update(calendarId=calendar_id, eventId=event_id, body=event)
                .execute()
            )

            log_msg = f"Google Calendar API update event - calendarId={calendar_id}, eventId={event_id}, summary={event.get('summary')}"
            logger.info(log_msg)
            print(f"[CALENDAR_CLIENT] {log_msg}")

            return self._format_event(updated_event)

        except HttpError as error:
            return {"error": f"API error: {error}"}

    def delete_event(
        self, event_id: str, calendar_id: str = "primary"
    ) -> Dict[str, str]:
        """
        Delete an event from the calendar

        Args:
            event_id: ID of the event to delete
            calendar_id: Calendar ID (default: primary)

        Returns:
            Confirmation message
        """
        try:
            self.service.events().delete(
                calendarId=calendar_id, eventId=event_id
            ).execute()

            log_msg = f"Google Calendar API delete event - calendarId={calendar_id}, eventId={event_id}"
            logger.info(log_msg)
            print(f"[CALENDAR_CLIENT] {log_msg}")

            return {"message": f"Event {event_id} deleted successfully"}

        except HttpError as error:
            return {"error": f"API error: {error}"}

    @staticmethod
    def _format_event(event: Dict[str, Any]) -> Dict[str, Any]:
        """Format a single event for response"""
        return {
            "id": event.get("id"),
            "summary": event.get("summary"),
            "description": event.get("description", ""),
            "start": event.get("start", {}).get("dateTime")
            or event.get("start", {}).get("date"),
            "end": event.get("end", {}).get("dateTime")
            or event.get("end", {}).get("date"),
            "attendees": [
                {"email": att.get("email"), "status": att.get("responseStatus")}
                for att in event.get("attendees", [])
            ],
            "link": event.get("htmlLink"),
        }

    @staticmethod
    def _format_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format multiple events for response"""
        return [GoogleCalendarClient._format_event(event) for event in events]
