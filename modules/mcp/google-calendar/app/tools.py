"""
Google Calendar MCP Tools
Defines MCP tools for calendar operations
"""

import sys
import os
import logging

# Ensure parent directory is in path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Load environment variables from .env file if they're not already set
def load_env_file():
    """Load environment variables from .env file in project root"""
    # Find the project root (.env location)
    current_file = os.path.abspath(__file__)
    # current_file = /Users/.../modules/mcp/google-calendar/app/tools.py
    # We need to go up 4 levels to reach project root
    app_dir = os.path.dirname(current_file)  # app/
    google_calendar_dir = os.path.dirname(app_dir)  # google-calendar/
    mcp_dir = os.path.dirname(google_calendar_dir)  # mcp/
    modules_dir = os.path.dirname(mcp_dir)  # modules/
    project_root = os.path.dirname(modules_dir)  # project root
    env_file = os.path.join(project_root, ".env")

    if os.path.exists(env_file):
        try:
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    # Parse KEY=VALUE format
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        # Only set if not already set
                        if key not in os.environ:
                            os.environ[key] = value
        except Exception as e:
            print(f"[DEBUG] Warning: Could not load .env file: {e}")
    else:
        print(f"[DEBUG] .env file not found at: {env_file}")


# Load .env file at module initialization
load_env_file()

from mcp.server.fastmcp import FastMCP
from calendar_client import GoogleCalendarClient
from typing import Optional, List

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

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
    # Handle empty calendar_id
    if not calendar_id or calendar_id.strip() == "":
        calendar_id = "primary"

    log_msg = f"google_list_events called - calendar_id={calendar_id}, start_date={start_date}, end_date={end_date}, max_results={max_results}"
    logger.info(log_msg)
    print(f"[MCP_TOOL] {log_msg}")

    if not calendar_client:
        logger.error("Calendar client not initialized")
        return "Error: Calendar client not initialized"

    try:
        events = calendar_client.list_events(
            calendar_id=calendar_id,
            start_date=start_date,
            end_date=end_date,
            max_results=max_results,
        )

        if isinstance(events, dict) and "error" in events:
            logger.error(f"Error listing events: {events['error']}")
            return f"Error: {events['error']}"

        if not events:
            logger.info("No events found in the specified date range")
            return "No events found in the specified date range."

        logger.info(f"Found {len(events)} events")

        # Group events by date in user's timezone
        from datetime import datetime
        from collections import defaultdict
        from zoneinfo import ZoneInfo
        import os

        # Get user's timezone
        tz_name = os.getenv("CALENDAR_TIMEZONE", "UTC")
        try:
            user_tz = ZoneInfo(tz_name)
            logger.info(f"Using timezone: {tz_name}")
        except Exception as e:
            logger.warning(
                f"Failed to load timezone {tz_name}: {e}, falling back to UTC"
            )
            user_tz = ZoneInfo("UTC")
            tz_name = "UTC"

        events_by_date = defaultdict(list)
        for event in events:
            start = event.get("start")
            if start:
                # Parse UTC timestamp and convert to user's timezone
                try:
                    # Handle both full datetime and date-only formats
                    if "T" in start:
                        # Full datetime with timezone offset (e.g., +08:00 or Z)
                        # Replace Z with +00:00 for proper parsing
                        if start.endswith("Z"):
                            utc_dt = datetime.fromisoformat(
                                start.replace("Z", "+00:00")
                            )
                        else:
                            # Already has offset like +08:00
                            utc_dt = datetime.fromisoformat(start)

                        # Convert to user's timezone (if not already in it)
                        user_dt = utc_dt.astimezone(user_tz)
                        date_str = user_dt.strftime("%Y-%m-%d")
                    else:
                        # Date only
                        date_str = start
                except Exception as e:
                    # Fallback to direct parsing if conversion fails
                    date_str = start.split("T")[0] if "T" in start else start

                events_by_date[date_str].append(event)

        # Format results by date
        result = ""

        for date_str in sorted(events_by_date.keys()):
            # Format date nicely (2026-02-01 -> 1 Feb 2026)
            from datetime import datetime as dt

            date_obj = dt.strptime(date_str, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%d %b %Y")

            result += f"Events on {formatted_date}\n"
            result += "\n"

            for i, event in enumerate(
                sorted(events_by_date[date_str], key=lambda e: e.get("start", "")), 1
            ):
                summary = event.get("summary", "No title")
                event_id = event.get("id", "N/A")
                start = event.get("start", "N/A")
                end = event.get("end", "N/A")

                logger.info(
                    f"Processing event: {summary}, raw start: {start}, raw end: {end}"
                )

                # Format time range in user's timezone
                time_range = "All day"

                if start and end and start != "N/A" and end != "N/A":
                    try:
                        # Parse start time
                        start_time = None
                        if "T" in start:
                            # Handle both Z and +08:00 format
                            if start.endswith("Z"):
                                utc_start = datetime.fromisoformat(
                                    start.replace("Z", "+00:00")
                                )
                                logger.debug(
                                    f"Parsed UTC start from Z format: {utc_start}"
                                )
                            else:
                                utc_start = datetime.fromisoformat(start)
                                logger.debug(f"Parsed start with offset: {utc_start}")
                            user_start = utc_start.astimezone(user_tz)
                            start_time = user_start.strftime("%H:%M")
                            logger.info(
                                f"Start time in {tz_name}: {user_start} -> {start_time}"
                            )
                        else:
                            start_time = start
                            logger.info(f"Start time (no T): {start_time}")

                        # Parse end time
                        end_time = None
                        if "T" in end:
                            # Handle both Z and +08:00 format
                            if end.endswith("Z"):
                                utc_end = datetime.fromisoformat(
                                    end.replace("Z", "+00:00")
                                )
                                logger.debug(f"Parsed UTC end from Z format: {utc_end}")
                            else:
                                utc_end = datetime.fromisoformat(end)
                                logger.debug(f"Parsed end with offset: {utc_end}")
                            user_end = utc_end.astimezone(user_tz)
                            end_time = user_end.strftime("%H:%M")
                            logger.info(
                                f"End time in {tz_name}: {user_end} -> {end_time}"
                            )
                        else:
                            end_time = end
                            logger.info(f"End time (no T): {end_time}")

                        time_range = f"{start_time} – {end_time}"
                        logger.info(f"Final time range for {summary}: {time_range}")
                    except Exception as e:
                        logger.error(
                            f"Error parsing time for {summary}: {e}", exc_info=True
                        )
                        time_range = "All day"

                result += f"{i}. {summary}\n"
                result += f"   Time: {time_range} ({tz_name})\n"
                result += f"   ID: {event_id}\n"
                result += "\n"

        if result:
            result = (
                result.rstrip()
                + "\n\nThese are the only events scheduled for that day."
            )

        logger.info(f"TOOL_RESPONSE: {result}")
        print(f"[MCP_TOOL_RESPONSE] {result}")
        return result
    except Exception as e:
        logger.exception(f"Exception in google_list_events: {str(e)}")
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
    # Handle empty calendar_id
    if not calendar_id or calendar_id.strip() == "":
        calendar_id = "primary"

    log_msg = f"google_create_event called - title={title}, start_time={start_time}, end_time={end_time}, calendar_id={calendar_id}"
    logger.info(log_msg)
    print(f"[MCP_TOOL] {log_msg}")

    if not calendar_client:
        logger.error("Calendar client not initialized")
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
            logger.error(f"Error creating event: {event['error']}")
            return f"Error: {event['error']}"

        logger.info(f"Event created successfully - ID: {event.get('id')}")
        result = f"✅ Event created successfully!\n\n"
        result += f"- **{event.get('summary')}**\n"
        result += f"  ID: {event.get('id')}\n"
        result += f"  Start: {event.get('start')}\n"
        result += f"  End: {event.get('end')}\n"
        if event.get("description"):
            result += f"  Description: {event.get('description')}\n"
        result += f"  Link: {event.get('link')}\n"

        logger.info(f"TOOL_RESPONSE: {result}")
        print(f"[MCP_TOOL_RESPONSE] {result}")
        return result
    except Exception as e:
        logger.exception(f"Exception in google_create_event: {str(e)}")
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
    # Handle empty calendar_id
    if not calendar_id or calendar_id.strip() == "":
        calendar_id = "primary"

    log_msg = f"google_update_event called - event_id={event_id}, calendar_id={calendar_id}, title={title}, start_time={start_time}, end_time={end_time}"
    logger.info(log_msg)
    print(f"[MCP_TOOL] {log_msg}")

    if not calendar_client:
        logger.error("Calendar client not initialized")
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
            logger.error(f"Error updating event: {event['error']}")
            return f"Error: {event['error']}"

        logger.info(f"Event updated successfully - ID: {event.get('id')}")
        result = f"✅ Event updated successfully!\n\n"
        result += f"- **{event.get('summary')}**\n"
        result += f"  ID: {event.get('id')}\n"
        result += f"  Start: {event.get('start')}\n"
        result += f"  End: {event.get('end')}\n"
        if event.get("description"):
            result += f"  Description: {event.get('description')}\n"
        result += f"  Link: {event.get('link')}\n"

        logger.info(f"TOOL_RESPONSE: {result}")
        print(f"[MCP_TOOL_RESPONSE] {result}")
        return result
    except Exception as e:
        logger.exception(f"Exception in google_update_event: {str(e)}")
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
    # Handle empty calendar_id
    if not calendar_id or calendar_id.strip() == "":
        calendar_id = "primary"

    log_msg = (
        f"google_delete_event called - event_id={event_id}, calendar_id={calendar_id}"
    )
    logger.info(log_msg)
    print(f"[MCP_TOOL] {log_msg}")

    if not calendar_client:
        logger.error("Calendar client not initialized")
        return "Error: Calendar client not initialized"

    try:
        result = calendar_client.delete_event(
            event_id=event_id, calendar_id=calendar_id
        )

        if isinstance(result, dict) and "error" in result:
            logger.error(f"Error deleting event: {result['error']}")
            return f"Error: {result['error']}"

        logger.info(f"Event deleted successfully - ID: {event_id}")
        return f"✅ {result.get('message', 'Event deleted successfully')}"
    except Exception as e:
        logger.exception(f"Exception in google_delete_event: {str(e)}")
        return f"Error deleting event: {str(e)}"
