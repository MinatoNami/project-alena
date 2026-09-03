"""Authorise against Google Calendar and list a few events.

A manual check, not a test: it opens a browser for the OAuth consent screen and
calls the live Calendar API. It used to sit in tests/ and ran both of those at
import time, which broke `pytest` and could fire real API calls.

    python modules/mcp/google-calendar/scripts/check_credentials.py
"""

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
from datetime import datetime, timedelta, timezone

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Use secrets folder
SECRETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets")
CREDENTIALS_PATH = os.path.join(SECRETS_DIR, "credentials.json")
TOKEN_PATH = os.path.join(SECRETS_DIR, "token.json")


def main() -> int:
    if not os.path.exists(CREDENTIALS_PATH) and not os.path.exists(TOKEN_PATH):
        print(f"No credentials at {CREDENTIALS_PATH}. See the README for setup.")
        return 1

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)
        os.makedirs(SECRETS_DIR, exist_ok=True)
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)

    # A window around now, rather than dates hard-coded to a past quarter.
    now = datetime.now(timezone.utc)
    events = (
        service.events()
        .list(
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=60)).isoformat(),
            calendarId="primary",
            maxResults=5,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    items = events.get("items", [])
    if not items:
        print("Authorised. No upcoming events in the next 60 days.")
    for event in items:
        print(event.get("start", {}).get("dateTime", "?"), "-", event.get("summary"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
