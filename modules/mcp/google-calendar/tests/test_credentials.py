from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Use secrets folder
SECRETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets")
CREDENTIALS_PATH = os.path.join(SECRETS_DIR, "credentials.json")
TOKEN_PATH = os.path.join(SECRETS_DIR, "token.json")

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

events = (
    service.events()
    .list(
        calendarId="primary",
        maxResults=5,
        singleEvents=True,
        orderBy="startTime",
    )
    .execute()
)

for event in events.get("items", []):
    print(event["summary"], event["start"])

# Create a test event called "Potato Test" on the current day at 6pm
from datetime import datetime, time

today = datetime.now().date()
event_time = datetime.combine(today, time(18, 0))  # 6pm

# Get timezone settings from environment
CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "Asia/Singapore")
CALENDAR_TIMEZONE_OFFSET = os.getenv("CALENDAR_TIMEZONE_OFFSET", "+08:00")

test_event = {
    "summary": "Potato Test",
    "start": {
        "dateTime": f"{event_time.isoformat()}{CALENDAR_TIMEZONE_OFFSET}",
        "timeZone": CALENDAR_TIMEZONE,
    },
    "end": {
        "dateTime": f"{event_time.replace(hour=19).isoformat()}{CALENDAR_TIMEZONE_OFFSET}",
        "timeZone": CALENDAR_TIMEZONE,
    },
}

created_event = service.events().insert(calendarId="primary", body=test_event).execute()
print(f"Created event: {created_event['summary']} at {created_event['start']}")
