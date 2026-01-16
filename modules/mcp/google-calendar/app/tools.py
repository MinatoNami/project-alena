"""
Google Calendar MCP Tools
Defines MCP tools for calendar operations
"""

import sys
import os

# Ensure parent directory is in path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from calendar_client import GoogleCalendarClient
from typing import Optional, List

# Initialize MCP server
mcp = FastMCP("google-calendar-mcp")

# Initialize calendar client
try:
    calendar_client = GoogleCalendarClient()
except Exception as e:
    print(f"Warning: Could not initialize calendar client: {e}")
    calendar_client = None


@mcp.tool()
def google_list_events(
    calendar_id: str = "primary",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_results: int = 10,
) -> str:
    """
    List events from a Google Calendar within a date range.

    Args:
        calendar_id: The calendar ID to list events from (default: "primary")
        start_date: Start date in ISO format (YYYY-MM-DD). If not provided, uses today.
        end_date: End date in ISO format (YYYY-MM-DD). If not provided, uses today + 7 days.
        max_results: Maximum number of events to return (default: 10)

    Returns:
        A list of events with their details (id, summary, start, end, description, attendees)
    """
    if not calendar_client:
        return "Error: Calendar client not initialized"

    try:
        events = calendar_client.list_events(
            calendar_id=calendar_id,
            start_date=start_date,
            end_date=end_date,
            max_results=max_results,
        )

        if isinstance(events, dict) and "error" in events:
            return f"Error: {events['error']}"

        if not events:
            return "No events found in the specified date range."

        result = "Events found:\n\n"
        for event in events:
            result += f"- **{event.get('summary', 'No title')}**\n"
            result += f"  ID: {event.get('id')}\n"
            result += f"  Start: {event.get('start')}\n"
            result += f"  End: {event.get('end')}\n"
            if event.get("description"):
                result += f"  Description: {event.get('description')}\n"
            if event.get("attendees"):
                result += f"  Attendees: {', '.join([a.get('email') for a in event.get('attendees', [])])}\n"
            result += "\n"

        return result
    except Exception as e:
        return f"Error listing events: {str(e)}"


@mcp.tool()
def google_create_event(
    title: str,
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    description: Optional[str] = None,
    attendees: Optional[List[str]] = None,
) -> str:
    """
    Create a new event in a Google Calendar.

    Args:
        title: Event title/summary
        start_time: Start time in ISO format (YYYY-MM-DDTHH:MM:SS) or (YYYY-MM-DD for all-day)
        end_time: End time in ISO format (YYYY-MM-DDTHH:MM:SS) or (YYYY-MM-DD for all-day)
        calendar_id: The calendar ID to create the event in (default: "primary")
        description: Event description (optional)
        attendees: List of attendee email addresses (optional)

    Returns:
        Details of the created event including its ID
    """
    if not calendar_client:
        return "Error: Calendar client not initialized"

    try:
        event = calendar_client.create_event(
            title=title,
            start_time=start_time,
            end_time=end_time,
            calendar_id=calendar_id,
            description=description,
            attendees=attendees,
        )

        if isinstance(event, dict) and "error" in event:
            return f"Error: {event['error']}"

        result = f"✅ Event created successfully!\n\n"
        result += f"- **{event.get('summary')}**\n"
        result += f"  ID: {event.get('id')}\n"
        result += f"  Start: {event.get('start')}\n"
        result += f"  End: {event.get('end')}\n"
        if event.get("description"):
            result += f"  Description: {event.get('description')}\n"
        result += f"  Link: {event.get('link')}\n"

        return result
    except Exception as e:
        return f"Error creating event: {str(e)}"


@mcp.tool()
def google_update_event(
    event_id: str,
    calendar_id: str = "primary",
    title: Optional[str] = None,
    description: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """
    Update an existing event in a Google Calendar.

    Args:
        event_id: The ID of the event to update
        calendar_id: The calendar ID containing the event (default: "primary")
        title: New event title (optional)
        description: New event description (optional)
        start_time: New start time in ISO format (YYYY-MM-DDTHH:MM:SS) (optional)
        end_time: New end time in ISO format (YYYY-MM-DDTHH:MM:SS) (optional)

    Returns:
        Details of the updated event
    """
    if not calendar_client:
        return "Error: Calendar client not initialized"

    try:
        event = calendar_client.update_event(
            event_id=event_id,
            calendar_id=calendar_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
        )

        if isinstance(event, dict) and "error" in event:
            return f"Error: {event['error']}"

        result = f"✅ Event updated successfully!\n\n"
        result += f"- **{event.get('summary')}**\n"
        result += f"  ID: {event.get('id')}\n"
        result += f"  Start: {event.get('start')}\n"
        result += f"  End: {event.get('end')}\n"
        if event.get("description"):
            result += f"  Description: {event.get('description')}\n"
        result += f"  Link: {event.get('link')}\n"

        return result
    except Exception as e:
        return f"Error updating event: {str(e)}"


@mcp.tool()
def google_delete_event(event_id: str, calendar_id: str = "primary") -> str:
    """
    Delete an event from a Google Calendar.

    Args:
        event_id: The ID of the event to delete
        calendar_id: The calendar ID containing the event (default: "primary")

    Returns:
        Confirmation message
    """
    if not calendar_client:
        return "Error: Calendar client not initialized"

    try:
        result = calendar_client.delete_event(
            event_id=event_id, calendar_id=calendar_id
        )

        if isinstance(result, dict) and "error" in result:
            return f"Error: {result['error']}"

        return f"✅ {result.get('message', 'Event deleted successfully')}"
    except Exception as e:
        return f"Error deleting event: {str(e)}"
