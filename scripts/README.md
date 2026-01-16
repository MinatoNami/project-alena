# ALENA Scripts

Helper scripts to run ALENA with various MCP (Model Context Protocol) server configurations.

## Available Scripts

### 1. `start_alena_with_google_calendar_mcp.sh`

Runs ALENA with the **Google Calendar MCP** server.

**Requirements:**

- Google OAuth credentials file at `./credentials.json` (or path set in `GOOGLE_CREDENTIALS_PATH` env var)
- Google Calendar API enabled in your Google Cloud project

**Usage:**

```bash
./scripts/start_alena_with_google_calendar_mcp.sh
```

**What it does:**

1. Loads environment variables from `.env`
2. Starts Google Calendar MCP server in background
3. Launches ALENA with Calendar tool access
4. Cleans up MCP processes on exit

**Tools available:**

- `list_events` - List calendar events
- `create_event` - Create new events
- `update_event` - Modify events
- `delete_event` - Remove events

---

### 2. `start_alena_with_all_mcps.sh`

Runs ALENA with **both Codex and Google Calendar MCP** servers.

**Requirements:**

- Codex CLI installed and configured
- Google OAuth credentials file at `./credentials.json`

**Usage:**

```bash
./scripts/start_alena_with_all_mcps.sh
```

**What it does:**

1. Loads environment variables from `.env`
2. Starts Codex MCP server in background
3. Starts Google Calendar MCP server in background
4. Launches ALENA with full tool access
5. Manages cleanup of both MCP processes

**Tools available:**

- All Codex tools (code generation, analysis, etc.)
- All Google Calendar tools

---

### 3. `start_alena_with_codex_server_mcp.sh`

Runs ALENA with the **Codex MCP** server only.

**Requirements:**

- Codex CLI installed and configured

**Usage:**

```bash
./scripts/start_alena_with_codex_server_mcp.sh
```

---

### 4. `start_controller_with_mcp.sh`

Runs the ALENA **Controller Server** with MCP support.

**Usage:**

```bash
./scripts/start_controller_with_mcp.sh
```

This starts the core controller that other services can connect to.

---

### 5. `start_telegram_bot.sh`

Runs the **Telegram Bot** standalone.

**Usage:**

```bash
./scripts/start_telegram_bot.sh
```

---

### 6. `start_telegram_with_controller_mcp.sh`

Runs Telegram Bot connected to the **Controller with MCP**.

**Usage:**

```bash
./scripts/start_telegram_with_controller_mcp.sh
```

---

## Configuration

All scripts use environment variables from `.env` file. Key variables:

**Google Calendar MCP:**

```dotenv
GOOGLE_CREDENTIALS_PATH=./credentials.json
CALENDAR_ID=primary
CALENDAR_TIMEZONE=UTC
```

**Controller:**

```dotenv
ALENA_CONTROLLER_URL=http://localhost:9000
ALENA_CONTROLLER_TIMEOUT=120
ALENA_MAX_TOOL_STEPS=3
```

**Ollama:**

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gpt-oss:20b
OLLAMA_TIMEOUT=120
```

See `.env.example` for all available options.

---

## Setup Instructions

### For Google Calendar MCP

1. **Get Google Credentials:**

   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project
   - Enable the **Google Calendar API**
   - Create OAuth 2.0 credentials (Desktop Application)
   - Download the credentials as JSON

2. **Place Credentials:**

   ```bash
   # Option 1: Default location
   cp your-credentials.json /path/to/project-alena/credentials.json

   # Option 2: Custom location (update .env)
   cp your-credentials.json /custom/path/credentials.json
   echo "GOOGLE_CREDENTIALS_PATH=/custom/path/credentials.json" >> .env
   ```

3. **Update .env (if needed):**

   ```bash
   # Default calendar (use "primary" for your main calendar)
   CALENDAR_ID=primary

   # Your timezone
   CALENDAR_TIMEZONE=America/New_York
   ```

4. **Run with Google Calendar:**

   ```bash
   ./scripts/start_alena_with_google_calendar_mcp.sh
   ```

   On first run, a browser will open for you to authorize access. The token will be cached locally.

---

## Troubleshooting

### "No module named 'app.calendar_client'"

Make sure you're running from the project root:

```bash
cd /path/to/project-alena
./scripts/start_alena_with_google_calendar_mcp.sh
```

### "ModuleNotFoundError: No module named 'google'"

Install Google Calendar dependencies:

```bash
pip install -r requirements.txt
```

### "Google credentials not found"

Check that `credentials.json` exists at the path specified in `GOOGLE_CREDENTIALS_PATH`:

```bash
ls -la ./credentials.json
# or
cat .env | grep GOOGLE_CREDENTIALS_PATH
```

### MCP server doesn't start

Check the logs for the specific error. Try running the MCP server directly:

```bash
cd modules/mcp/google-calendar
python -m app.main
```

---

## Running Multiple Services

To run multiple services in parallel:

```bash
# Terminal 1: Start controller with MCPs
./scripts/start_controller_with_mcp.sh

# Terminal 2: Start ALENA with Google Calendar
./scripts/start_alena_with_google_calendar_mcp.sh

# Terminal 3: Start Telegram bot
./scripts/start_telegram_bot.sh
```

Or use the all-in-one script for ALENA + all MCPs:

```bash
./scripts/start_alena_with_all_mcps.sh
```

---

## Adding New MCP Servers

To add a new MCP server to a script:

1. Create your script in `scripts/`
2. Follow the pattern:

   ```bash
   #!/usr/bin/env bash
   set -euo pipefail

   ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

   # Source environment
   if [[ -f "$ROOT_DIR/.env" ]]; then
     set -a
     source "$ROOT_DIR/.env"
     set +a
   fi

   # Cleanup function
   cleanup() {
     [[ -n "${MCP_PID:-}" ]] && kill "$MCP_PID" 2>/dev/null || true
   }
   trap cleanup EXIT

   # Start your MCP
   cd "$ROOT_DIR/modules/mcp/your-mcp"
   python -m app.main &
   MCP_PID=$!

   sleep 2

   # Start ALENA or controller
   cd "$ROOT_DIR"
   python alena.py
   ```

3. Make it executable:
   ```bash
   chmod +x scripts/start_your_script.sh
   ```

---

## Testing

Run tests for Google Calendar MCP:

```bash
pytest modules/mcp/google-calendar/tests/ -v
```

Run all project tests:

```bash
pytest -v
```

---

## Documentation

- [Google Calendar MCP README](../modules/mcp/google-calendar/README.md)
- [Google Calendar MCP Tests](../modules/mcp/google-calendar/tests/TEST_SUMMARY.md)
- [Project README](../README.md)
