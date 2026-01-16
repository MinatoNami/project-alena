"""
Pytest configuration and fixtures for Google Calendar MCP tests
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import os
import sys

# Add app directory to path for imports
app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
sys.path.insert(0, app_dir)


@pytest.fixture
def mock_service():
    """Mock Google Calendar API service"""
    service = MagicMock()
    return service


@pytest.fixture
def mock_credentials():
    """Mock Google OAuth credentials"""
    creds = MagicMock()
    creds.valid = True
    creds.expired = False
    creds.refresh_token = None
    return creds


@pytest.fixture
def mock_calendar_client(mock_service):
    """Mock calendar client with mocked service"""
    with patch("calendar_client.build") as mock_build:
        mock_build.return_value = mock_service
        with patch("calendar_client.os.path.exists", return_value=False):
            with patch("builtins.open", create=True):
                with patch("calendar_client.pickle.dump"):
                    with patch("calendar_client.InstalledAppFlow") as mock_flow:
                        mock_flow_instance = MagicMock()
                        mock_flow_instance.run_local_server.return_value = MagicMock(
                            valid=True
                        )
                        mock_flow.from_client_secrets_file.return_value = (
                            mock_flow_instance
                        )

                        from calendar_client import GoogleCalendarClient

                        client = GoogleCalendarClient(
                            credentials_path="test_credentials.json"
                        )
                        client.service = mock_service

                        yield client


@pytest.fixture
def sample_event():
    """Sample event data for testing"""
    return {
        "id": "event123",
        "summary": "Test Event",
        "description": "This is a test event",
        "start": {"dateTime": "2025-01-20T14:00:00Z", "timeZone": "UTC"},
        "end": {"dateTime": "2025-01-20T15:00:00Z", "timeZone": "UTC"},
        "attendees": [{"email": "attendee@example.com", "responseStatus": "accepted"}],
        "htmlLink": "https://www.google.com/calendar/event?eid=event123",
    }


@pytest.fixture
def multiple_events(sample_event):
    """Multiple sample events for list testing"""
    event2 = sample_event.copy()
    event2["id"] = "event456"
    event2["summary"] = "Another Event"

    event3 = sample_event.copy()
    event3["id"] = "event789"
    event3["summary"] = "Third Event"

    return [sample_event, event2, event3]
