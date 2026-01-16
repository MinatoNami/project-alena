"""
Unit tests for GoogleCalendarClient
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import os
import sys

# Add app directory to path
app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
sys.path.insert(0, app_dir)

from calendar_client import GoogleCalendarClient


class TestGoogleCalendarClientAuthentication:
    """Tests for authentication functionality"""

    def test_authenticate_with_existing_valid_token(self, mock_credentials):
        """Test authentication using existing valid cached token"""
        with patch("calendar_client.os.path.exists", return_value=True):
            with patch("builtins.open", create=True) as mock_open:
                with patch(
                    "calendar_client.pickle.load", return_value=mock_credentials
                ):
                    with patch("calendar_client.build") as mock_build:
                        client = GoogleCalendarClient(
                            credentials_path="test_credentials.json"
                        )

                        assert client.service is not None
                        mock_build.assert_called_once()

    def test_authenticate_with_expired_token(self):
        """Test authentication with expired token that needs refresh"""
        expired_creds = MagicMock()
        expired_creds.valid = False
        expired_creds.expired = True
        expired_creds.refresh_token = "refresh_token"

        with patch("calendar_client.os.path.exists", return_value=True):
            with patch("builtins.open", create=True):
                with patch(
                    "calendar_client.pickle.load", return_value=expired_creds
                ):
                    with patch("calendar_client.pickle.dump"):
                        with patch.object(expired_creds, "refresh") as mock_refresh:
                            with patch("calendar_client.build") as mock_build:
                                client = GoogleCalendarClient(
                                    credentials_path="test_credentials.json"
                                )

                                mock_refresh.assert_called_once()
                                assert client.service is not None

    def test_authenticate_with_new_flow(self):
        """Test authentication with new OAuth flow"""
        mock_creds = MagicMock()
        mock_creds.valid = True

        with patch("calendar_client.os.path.exists", return_value=False):
            with patch("calendar_client.InstalledAppFlow") as mock_flow:
                mock_flow_instance = MagicMock()
                mock_flow_instance.run_local_server.return_value = mock_creds
                mock_flow.from_client_secrets_file.return_value = mock_flow_instance

                with patch("builtins.open", create=True):
                    with patch("calendar_client.pickle.dump"):
                        with patch("calendar_client.build") as mock_build:
                            client = GoogleCalendarClient(
                                credentials_path="test_credentials.json"
                            )

                            assert client.service is not None
                            mock_flow.from_client_secrets_file.assert_called_once()


class TestListEvents:
    """Tests for list_events functionality"""

    def test_list_events_success(self, mock_calendar_client, sample_event):
        """Test successfully listing events"""
        mock_calendar_client.service.events.return_value.list.return_value.execute.return_value = {
            "items": [sample_event]
        }

        events = mock_calendar_client.list_events(
            calendar_id="primary", start_date="2025-01-20", end_date="2025-01-27"
        )

        assert len(events) == 1
        assert events[0]["id"] == "event123"
        assert events[0]["summary"] == "Test Event"
        assert events[0]["description"] == "This is a test event"

    def test_list_events_multiple(self, mock_calendar_client, multiple_events):
        """Test listing multiple events"""
        mock_calendar_client.service.events.return_value.list.return_value.execute.return_value = {
            "items": multiple_events
        }

        events = mock_calendar_client.list_events(max_results=3)

        assert len(events) == 3
        assert events[0]["id"] == "event123"
        assert events[1]["id"] == "event456"
        assert events[2]["id"] == "event789"

    def test_list_events_empty_result(self, mock_calendar_client):
        """Test listing events when none exist"""
        mock_calendar_client.service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        events = mock_calendar_client.list_events()

        assert len(events) == 0

    def test_list_events_with_date_range(self, mock_calendar_client):
        """Test that date range parameters are properly formatted"""
        mock_calendar_client.service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        mock_calendar_client.list_events(
            start_date="2025-01-17", end_date="2025-01-24", max_results=5
        )

        mock_calendar_client.service.events.return_value.list.assert_called_once()
        call_kwargs = mock_calendar_client.service.events.return_value.list.call_args[1]
        assert call_kwargs["timeMin"] == "2025-01-17T00:00:00Z"
        assert call_kwargs["timeMax"] == "2025-01-24T23:59:59Z"
        assert call_kwargs["maxResults"] == 5

    def test_list_events_api_error(self, mock_calendar_client):
        """Test handling of API errors"""
        from googleapiclient.errors import HttpError

        mock_calendar_client.service.events.return_value.list.return_value.execute.side_effect = HttpError(
            Mock(status=401), b"Unauthorized"
        )

        result = mock_calendar_client.list_events()

        assert isinstance(result, dict)
        assert "error" in result


class TestCreateEvent:
    """Tests for create_event functionality"""

    def test_create_event_success(self, mock_calendar_client, sample_event):
        """Test successfully creating an event"""
        mock_calendar_client.service.events.return_value.insert.return_value.execute.return_value = (
            sample_event
        )

        event = mock_calendar_client.create_event(
            title="Test Event",
            start_time="2025-01-20T14:00:00",
            end_time="2025-01-20T15:00:00",
            description="This is a test event",
        )

        assert event["id"] == "event123"
        assert event["summary"] == "Test Event"
        assert event["description"] == "This is a test event"

    def test_create_event_with_attendees(self, mock_calendar_client):
        """Test creating an event with attendees"""
        expected_event = {
            "id": "event123",
            "summary": "Team Meeting",
            "description": "Team sync meeting",
            "start": {"dateTime": "2025-01-20T14:00:00Z"},
            "end": {"dateTime": "2025-01-20T15:00:00Z"},
            "attendees": [
                {"email": "alice@example.com", "responseStatus": "needsAction"},
                {"email": "bob@example.com", "responseStatus": "needsAction"},
            ],
            "htmlLink": "https://www.google.com/calendar/event?eid=event123",
        }

        mock_calendar_client.service.events.return_value.insert.return_value.execute.return_value = (
            expected_event
        )

        event = mock_calendar_client.create_event(
            title="Team Meeting",
            start_time="2025-01-20T14:00:00",
            end_time="2025-01-20T15:00:00",
            description="Team sync meeting",
            attendees=["alice@example.com", "bob@example.com"],
        )

        assert len(event["attendees"]) == 2
        assert event["attendees"][0]["email"] == "alice@example.com"

    def test_create_event_minimal(self, mock_calendar_client):
        """Test creating event with minimal parameters"""
        mock_event = {
            "id": "event123",
            "summary": "Quick Event",
            "start": {"dateTime": "2025-01-20T14:00:00Z"},
            "end": {"dateTime": "2025-01-20T15:00:00Z"},
            "attendees": [],
            "htmlLink": "https://www.google.com/calendar/event?eid=event123",
        }

        mock_calendar_client.service.events.return_value.insert.return_value.execute.return_value = (
            mock_event
        )

        event = mock_calendar_client.create_event(
            title="Quick Event",
            start_time="2025-01-20T14:00:00",
            end_time="2025-01-20T15:00:00",
        )

        assert event["id"] == "event123"
        assert event["summary"] == "Quick Event"

    def test_create_event_api_error(self, mock_calendar_client):
        """Test handling of API errors during event creation"""
        from googleapiclient.errors import HttpError

        mock_calendar_client.service.events.return_value.insert.return_value.execute.side_effect = HttpError(
            Mock(status=400), b"Bad Request"
        )

        result = mock_calendar_client.create_event(
            title="Test",
            start_time="2025-01-20T14:00:00",
            end_time="2025-01-20T15:00:00",
        )

        assert isinstance(result, dict)
        assert "error" in result


class TestUpdateEvent:
    """Tests for update_event functionality"""

    def test_update_event_title(self, mock_calendar_client, sample_event):
        """Test updating event title"""
        mock_calendar_client.service.events.return_value.get.return_value.execute.return_value = (
            sample_event
        )

        updated_event = sample_event.copy()
        updated_event["summary"] = "Updated Event"
        mock_calendar_client.service.events.return_value.update.return_value.execute.return_value = (
            updated_event
        )

        event = mock_calendar_client.update_event(
            event_id="event123", title="Updated Event"
        )

        assert event["summary"] == "Updated Event"

    def test_update_event_time(self, mock_calendar_client, sample_event):
        """Test updating event time"""
        mock_calendar_client.service.events.return_value.get.return_value.execute.return_value = (
            sample_event
        )

        updated_event = sample_event.copy()
        updated_event["start"] = {"dateTime": "2025-01-21T14:00:00Z"}
        updated_event["end"] = {"dateTime": "2025-01-21T15:00:00Z"}
        mock_calendar_client.service.events.return_value.update.return_value.execute.return_value = (
            updated_event
        )

        event = mock_calendar_client.update_event(
            event_id="event123",
            start_time="2025-01-21T14:00:00",
            end_time="2025-01-21T15:00:00",
        )

        assert event["start"] == "2025-01-21T14:00:00Z"

    def test_update_event_description(self, mock_calendar_client, sample_event):
        """Test updating event description"""
        mock_calendar_client.service.events.return_value.get.return_value.execute.return_value = (
            sample_event
        )

        updated_event = sample_event.copy()
        updated_event["description"] = "Updated description"
        mock_calendar_client.service.events.return_value.update.return_value.execute.return_value = (
            updated_event
        )

        event = mock_calendar_client.update_event(
            event_id="event123", description="Updated description"
        )

        assert event["description"] == "Updated description"

    def test_update_event_multiple_fields(self, mock_calendar_client, sample_event):
        """Test updating multiple event fields"""
        mock_calendar_client.service.events.return_value.get.return_value.execute.return_value = (
            sample_event
        )

        updated_event = sample_event.copy()
        updated_event["summary"] = "Updated Event"
        updated_event["description"] = "New description"
        updated_event["start"] = {"dateTime": "2025-01-21T10:00:00Z"}
        mock_calendar_client.service.events.return_value.update.return_value.execute.return_value = (
            updated_event
        )

        event = mock_calendar_client.update_event(
            event_id="event123",
            title="Updated Event",
            description="New description",
            start_time="2025-01-21T10:00:00",
        )

        assert event["summary"] == "Updated Event"
        assert event["description"] == "New description"
        assert event["start"] == "2025-01-21T10:00:00Z"

    def test_update_event_not_found(self, mock_calendar_client):
        """Test updating non-existent event"""
        from googleapiclient.errors import HttpError

        mock_calendar_client.service.events.return_value.get.return_value.execute.side_effect = HttpError(
            Mock(status=404), b"Not Found"
        )

        result = mock_calendar_client.update_event(
            event_id="nonexistent", title="Updated"
        )

        assert isinstance(result, dict)
        assert "error" in result


class TestDeleteEvent:
    """Tests for delete_event functionality"""

    def test_delete_event_success(self, mock_calendar_client):
        """Test successfully deleting an event"""
        mock_calendar_client.service.events.return_value.delete.return_value.execute.return_value = (
            None
        )

        result = mock_calendar_client.delete_event(event_id="event123")

        assert isinstance(result, dict)
        assert "message" in result
        assert "event123" in result["message"]

    def test_delete_event_not_found(self, mock_calendar_client):
        """Test deleting non-existent event"""
        from googleapiclient.errors import HttpError

        mock_calendar_client.service.events.return_value.delete.return_value.execute.side_effect = HttpError(
            Mock(status=404), b"Not Found"
        )

        result = mock_calendar_client.delete_event(event_id="nonexistent")

        assert isinstance(result, dict)
        assert "error" in result

    def test_delete_event_with_calendar_id(self, mock_calendar_client):
        """Test deleting event with specific calendar"""
        mock_calendar_client.service.events.return_value.delete.return_value.execute.return_value = (
            None
        )

        mock_calendar_client.delete_event(
            event_id="event123", calendar_id="secondary@example.com"
        )

        mock_calendar_client.service.events.return_value.delete.assert_called_once()
        call_kwargs = mock_calendar_client.service.events.return_value.delete.call_args[
            1
        ]
        assert call_kwargs["calendarId"] == "secondary@example.com"
        assert call_kwargs["eventId"] == "event123"


class TestEventFormatting:
    """Tests for event formatting utilities"""

    def test_format_single_event(self, mock_calendar_client, sample_event):
        """Test formatting a single event"""
        formatted = mock_calendar_client._format_event(sample_event)

        assert formatted["id"] == "event123"
        assert formatted["summary"] == "Test Event"
        assert formatted["description"] == "This is a test event"
        assert formatted["start"] == "2025-01-20T14:00:00Z"

    def test_format_event_with_all_day(self, mock_calendar_client):
        """Test formatting all-day event"""
        all_day_event = {
            "id": "event123",
            "summary": "All Day Event",
            "start": {"date": "2025-01-20"},
            "end": {"date": "2025-01-21"},
            "attendees": [],
            "htmlLink": "https://example.com/event",
        }

        formatted = mock_calendar_client._format_event(all_day_event)

        assert formatted["start"] == "2025-01-20"
        assert formatted["end"] == "2025-01-21"

    def test_format_multiple_events(self, mock_calendar_client, multiple_events):
        """Test formatting multiple events"""
        formatted = mock_calendar_client._format_events(multiple_events)

        assert len(formatted) == 3
        assert all("id" in event for event in formatted)
        assert all("summary" in event for event in formatted)
