"""
Unit tests for Google Calendar MCP tools
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import sys
import os

# Add app directory to path
app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
sys.path.insert(0, app_dir)


class TestListEventsTool:
    """Tests for list_events MCP tool"""

    def test_list_events_with_no_client(self):
        """Test list_events when calendar_client is not initialized"""
        with patch("tools.calendar_client", None):
            import tools

            result = tools.list_events()
            assert "Error: Calendar client not initialized" in result

    def test_list_events_success(self):
        """Test successful event listing"""
        mock_client = MagicMock()
        mock_client.list_events.return_value = [
            {
                "id": "event123",
                "summary": "Team Meeting",
                "description": "Weekly sync",
                "start": "2025-01-20T14:00:00Z",
                "end": "2025-01-20T15:00:00Z",
                "attendees": [{"email": "alice@example.com", "status": "accepted"}],
                "link": "https://example.com/event",
            }
        ]

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.list_events()

            assert "Events found:" in result
            assert "Team Meeting" in result
            assert "Weekly sync" in result

    def test_list_events_empty_result(self):
        """Test listing when no events exist"""
        mock_client = MagicMock()
        mock_client.list_events.return_value = []

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.list_events()

            assert "No events found" in result

    def test_list_events_with_parameters(self):
        """Test list_events with custom parameters"""
        mock_client = MagicMock()
        mock_client.list_events.return_value = []

        with patch("tools.calendar_client", mock_client):
            import tools

            tools.list_events(
                calendar_id="secondary@example.com",
                start_date="2025-01-20",
                end_date="2025-01-27",
                max_results=20,
            )

            mock_client.list_events.assert_called_once_with(
                calendar_id="secondary@example.com",
                start_date="2025-01-20",
                end_date="2025-01-27",
                max_results=20,
            )

    def test_list_events_api_error(self):
        """Test handling of API errors in list_events"""
        mock_client = MagicMock()
        mock_client.list_events.return_value = {"error": "API error: Unauthorized"}

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.list_events()

            assert "Error:" in result

    def test_list_events_exception_handling(self):
        """Test exception handling in list_events"""
        mock_client = MagicMock()
        mock_client.list_events.side_effect = Exception("Unexpected error")

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.list_events()

            assert "Error listing events:" in result

    def test_list_events_formatting(self):
        """Test that list_events properly formats output"""
        mock_client = MagicMock()
        mock_client.list_events.return_value = [
            {
                "id": "event1",
                "summary": "Meeting 1",
                "description": "Description 1",
                "start": "2025-01-20T14:00:00Z",
                "end": "2025-01-20T15:00:00Z",
                "attendees": [],
                "link": "https://example.com/1",
            },
            {
                "id": "event2",
                "summary": "Meeting 2",
                "description": "",
                "start": "2025-01-21T10:00:00Z",
                "end": "2025-01-21T11:00:00Z",
                "attendees": [{"email": "bob@example.com", "status": "pending"}],
                "link": "https://example.com/2",
            },
        ]

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.list_events()

            assert "Meeting 1" in result
            assert "Meeting 2" in result
            assert "event1" in result
            assert "event2" in result


class TestCreateEventTool:
    """Tests for create_event MCP tool"""

    def test_create_event_with_no_client(self):
        """Test create_event when calendar_client is not initialized"""
        with patch("tools.calendar_client", None):
            import tools

            result = tools.create_event(
                title="Test",
                start_time="2025-01-20T14:00:00",
                end_time="2025-01-20T15:00:00",
            )
            assert "Error: Calendar client not initialized" in result

    def test_create_event_success(self):
        """Test successful event creation"""
        mock_client = MagicMock()
        mock_client.create_event.return_value = {
            "id": "event123",
            "summary": "New Meeting",
            "description": "Test meeting",
            "start": "2025-01-20T14:00:00Z",
            "end": "2025-01-20T15:00:00Z",
            "attendees": [],
            "link": "https://calendar.google.com/event123",
        }

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.create_event(
                title="New Meeting",
                start_time="2025-01-20T14:00:00",
                end_time="2025-01-20T15:00:00",
                description="Test meeting",
            )

            assert "✅ Event created successfully" in result
            assert "New Meeting" in result
            assert "event123" in result

    def test_create_event_with_attendees(self):
        """Test creating event with attendees"""
        mock_client = MagicMock()
        mock_client.create_event.return_value = {
            "id": "event123",
            "summary": "Team Meeting",
            "description": "Team sync",
            "start": "2025-01-20T14:00:00Z",
            "end": "2025-01-20T15:00:00Z",
            "attendees": [
                {"email": "alice@example.com", "status": "needsAction"},
                {"email": "bob@example.com", "status": "needsAction"},
            ],
            "link": "https://calendar.google.com/event123",
        }

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.create_event(
                title="Team Meeting",
                start_time="2025-01-20T14:00:00",
                end_time="2025-01-20T15:00:00",
                description="Team sync",
                attendees=["alice@example.com", "bob@example.com"],
            )

            mock_client.create_event.assert_called_once()
            call_kwargs = mock_client.create_event.call_args[1]
            assert call_kwargs["attendees"] == ["alice@example.com", "bob@example.com"]

    def test_create_event_api_error(self):
        """Test handling of API errors"""
        mock_client = MagicMock()
        mock_client.create_event.return_value = {"error": "API error: Invalid time"}

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.create_event(
                title="Bad Event", start_time="invalid", end_time="invalid"
            )

            assert "Error:" in result

    def test_create_event_exception_handling(self):
        """Test exception handling in create_event"""
        mock_client = MagicMock()
        mock_client.create_event.side_effect = Exception("Creation failed")

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.create_event(
                title="Test",
                start_time="2025-01-20T14:00:00",
                end_time="2025-01-20T15:00:00",
            )

            assert "Error creating event:" in result


class TestUpdateEventTool:
    """Tests for update_event MCP tool"""

    def test_update_event_with_no_client(self):
        """Test update_event when calendar_client is not initialized"""
        with patch("tools.calendar_client", None):
            import tools

            result = tools.update_event(event_id="event123")
            assert "Error: Calendar client not initialized" in result

    def test_update_event_success(self):
        """Test successful event update"""
        mock_client = MagicMock()
        mock_client.update_event.return_value = {
            "id": "event123",
            "summary": "Updated Meeting",
            "description": "Updated description",
            "start": "2025-01-21T14:00:00Z",
            "end": "2025-01-21T15:00:00Z",
            "attendees": [],
            "link": "https://calendar.google.com/event123",
        }

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.update_event(
                event_id="event123",
                title="Updated Meeting",
                description="Updated description",
            )

            assert "✅ Event updated successfully" in result
            assert "Updated Meeting" in result

    def test_update_event_partial(self):
        """Test updating only specific event fields"""
        mock_client = MagicMock()
        mock_client.update_event.return_value = {
            "id": "event123",
            "summary": "New Title",
            "description": "Old description",
            "start": "2025-01-20T14:00:00Z",
            "end": "2025-01-20T15:00:00Z",
            "attendees": [],
            "link": "https://calendar.google.com/event123",
        }

        with patch("tools.calendar_client", mock_client):
            import tools

            tools.update_event(event_id="event123", title="New Title")

            mock_client.update_event.assert_called_once()
            call_kwargs = mock_client.update_event.call_args[1]
            assert call_kwargs["title"] == "New Title"
            assert call_kwargs["description"] is None

    def test_update_event_api_error(self):
        """Test handling of API errors in update"""
        mock_client = MagicMock()
        mock_client.update_event.return_value = {"error": "Event not found"}

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.update_event(event_id="nonexistent", title="Updated")

            assert "Error:" in result

    def test_update_event_exception_handling(self):
        """Test exception handling in update_event"""
        mock_client = MagicMock()
        mock_client.update_event.side_effect = Exception("Update failed")

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.update_event(event_id="event123")

            assert "Error updating event:" in result


class TestDeleteEventTool:
    """Tests for delete_event MCP tool"""

    def test_delete_event_with_no_client(self):
        """Test delete_event when calendar_client is not initialized"""
        with patch("tools.calendar_client", None):
            import tools

            result = tools.delete_event(event_id="event123")
            assert "Error: Calendar client not initialized" in result

    def test_delete_event_success(self):
        """Test successful event deletion"""
        mock_client = MagicMock()
        mock_client.delete_event.return_value = {
            "message": "Event event123 deleted successfully"
        }

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.delete_event(event_id="event123")

            assert "✅" in result
            assert "deleted successfully" in result

    def test_delete_event_with_calendar_id(self):
        """Test deleting with specific calendar"""
        mock_client = MagicMock()
        mock_client.delete_event.return_value = {
            "message": "Event event123 deleted successfully"
        }

        with patch("tools.calendar_client", mock_client):
            import tools

            tools.delete_event(event_id="event123", calendar_id="secondary@example.com")

            mock_client.delete_event.assert_called_once()
            call_kwargs = mock_client.delete_event.call_args[1]
            assert call_kwargs["calendar_id"] == "secondary@example.com"

    def test_delete_event_not_found(self):
        """Test deleting non-existent event"""
        mock_client = MagicMock()
        mock_client.delete_event.return_value = {"error": "Event not found"}

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.delete_event(event_id="nonexistent")

            assert "Error:" in result

    def test_delete_event_exception_handling(self):
        """Test exception handling in delete_event"""
        mock_client = MagicMock()
        mock_client.delete_event.side_effect = Exception("Deletion failed")

        with patch("tools.calendar_client", mock_client):
            import tools

            result = tools.delete_event(event_id="event123")

            assert "Error deleting event:" in result
