# Google Calendar MCP Server

An **MCP (Model Context Protocol) server** that allows agents to interact with Google Calendar by reading, creating, updating, and deleting events.

## ✨ Features

- 📅 **List Events** - Retrieve events from a calendar within a date range
- ➕ **Create Events** - Create new calendar events with title, description, and time
- ✏️ **Update Events** - Modify existing event details
- ❌ **Delete Events** - Remove events from the calendar
- 🔐 OAuth 2.0 authentication with Google Calendar API
- 📦 Minimal dependencies

---

## 🏗 Architecture

```
[MCP Client / Agent]
        |
        |  MCP tool call (JSON-RPC)
        v
[Google Calendar MCP Server]
        |
        |  Google Calendar API calls
        v
[Google Calendar]
```

---

## 📋 Prerequisites

- Python 3.8+
- Google Cloud Project with Calendar API enabled
- OAuth 2.0 credentials (credentials.json)

---

## 🚀 Setup

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the **Google Calendar API**
4. Create OAuth 2.0 credentials:
   - Go to Credentials → Create Credentials → OAuth client ID
   - Choose "Desktop application"
   - Download the credentials as JSON

### 2. Install Dependencies

```bash
cd /path/to/modules/mcp/google-calendar
pip install -r requirements.txt
```

### 3. Add Your Credentials

```bash
# Copy your downloaded credentials to the secrets folder
cp ~/Downloads/client_secret_*.json secrets/credentials.json
```

**Important:** The MCP server uses **hardcoded paths** to `secrets/credentials.json` and `secrets/token.json`. No environment variables needed!

See [secrets/README.md](secrets/README.md) for detailed setup instructions.

### 4. First Authentication

```bash
cd modules/mcp/google-calendar
python tests/test_credentials.py
```

- A browser will open for Google login
- Grant permissions to your app
- `token.json` will be automatically created by Google

### 5. Start the MCP Server

```bash
# From project root
bash scripts/start_alena_with_google_calendar_mcp.sh
```

---

## 🛠 Available Tools

### `list_events`

List events from the calendar within a date range.

**Parameters:**

- `calendar_id` (string): Calendar ID (default: "primary")
- `start_date` (string): Start date in ISO format (YYYY-MM-DD)
- `end_date` (string): End date in ISO format (YYYY-MM-DD)
- `max_results` (integer): Maximum number of events to return (default: 10)

**Returns:** List of events with details (id, summary, start, end, description)

---

### `create_event`

Create a new event in the calendar.

**Parameters:**

- `title` (string): Event title
- `description` (string, optional): Event description
- `start_time` (string): Start time in ISO format (YYYY-MM-DDTHH:MM:SS)
- `end_time` (string): End time in ISO format (YYYY-MM-DDTHH:MM:SS)
- `calendar_id` (string): Calendar ID (default: "primary")
- `attendees` (list, optional): List of attendee emails

**Returns:** Created event details including event ID

---

### `update_event`

Update an existing event.

**Parameters:**

- `event_id` (string): ID of the event to update
- `title` (string, optional): New event title
- `description` (string, optional): New description
- `start_time` (string, optional): New start time
- `end_time` (string, optional): New end time
- `calendar_id` (string): Calendar ID (default: "primary")

**Returns:** Updated event details

---

### `delete_event`

Delete an event from the calendar.

**Parameters:**

- `event_id` (string): ID of the event to delete
- `calendar_id` (string): Calendar ID (default: "primary")

**Returns:** Confirmation message

---

## 🔑 Authentication

The server uses OAuth 2.0 with local file-based token caching:

1. First run will open a browser for Google login
2. Token is saved locally in `token.pickle`
3. Subsequent runs use the cached token

To reset authentication, delete `token.pickle` and run again.

---

## 🎯 Usage Example

```python
from app.tools import mcp

# The server runs and exposes MCP tools
# Clients can call tools like:
# - list_events(calendar_id="primary", start_date="2025-01-17", end_date="2025-01-24")
# - create_event(title="Meeting", start_time="2025-01-20T14:00:00", end_time="2025-01-20T15:00:00")
# - update_event(event_id="abc123", title="Updated Meeting")
# - delete_event(event_id="abc123")
```

---

## 📝 Running the Server

```bash
cd /path/to/modules/mcp/google-calendar
python -m app.main
```

The server will be available for MCP clients to connect.

---

## 🔧 Configuration

Environment variables:

- `GOOGLE_CREDENTIALS_PATH`: Path to credentials.json (default: "./credentials.json")
- `CALENDAR_ID`: Default calendar ID (default: "primary")

---

## 📚 References

- [Google Calendar API Docs](https://developers.google.com/calendar/api/quickstart/python)
- [MCP Protocol Docs](https://modelcontextprotocol.io)
