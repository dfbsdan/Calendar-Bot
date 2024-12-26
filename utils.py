from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from datetime import datetime, timedelta
import pytz
import os


OPENAI_API_KEY = '' # TODO
FIRST_UTTERANCE = 'Hi! When would you like to schedule a new meeting?'
_CREATE_EVENT_FN = {
    "name": "create_event",
    "description": (
        "Adds an event to the user's calendar. Call this whenever the user has provided "
        "all the necessary information to schedule a meeting (i.e. the function arguments "
        "are clearly defined), and no modification is necessary."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "year": {"type": "integer", "description": "Year of the event."},
            "month": {"type": "integer", "description": "Month of the event (1 to 12)."},
            "day": {"type": "integer", "description": "Day of the event (1 to 31)."},
            "hour": {"type": "integer", "description": "Hour of the event (0 to 23)."},
            "minute": {"type": "integer", "description": "Minute of the event (0 to 59)."},
            "duration": {"type": "integer", "description": "Duration of the event, in minutes (greater than 0)."},
            "summary": {"type": "string", "description": "Title of the event, must be short."},
            "location": {"type": "string", "description": "Location of the event as free-form text."},
            "timezone": {"type": "string", "description": "Timezone of the event, formatted as an IANA Time Zone Database name, e.g. 'Europe/Zurich'."},
            "send_updates": {"type": "boolean", "description": "Whether or not to send email updates to the participants."},
            # Optional parameters
            "description": {"type": "string", "description": "Description of the event. Can be empty if not provided."},
            "participants": {"type": "array", "items": {"type": "string"}, "description": "List of participant's emails. Can be empty if none provided."},
        },
        "required": ["year", "month", "day", "hour", "minute", "duration", "summary", "location", "timezone", "send_updates", "description", "participants"],
        "additionalProperties": False,
    },
}
ASSISTANT_TOOLS_CLI = [
    {
        "type": "function",
        "function": _CREATE_EVENT_FN.copy(),
    },
]
ASSISTANT_TOOLS_CLI[0]["function"]["strict"] = True

ASSISTANT_TOOLS_VOICE = [
    {
        "type": "function",
        **_CREATE_EVENT_FN.copy()
    },
]
ASSISTANT_PROMPT = (
    "You are a helpful assistant that allows users to book meetings through Google Calendar."
    "To do so, you must first ask for the meeting's details (e.g. date, time, etc) and, "
    "once all of them have been gathered, create the corresponding event using the 'create_event' "
    "function. The following is a sample conversation:"
    f"\nASSISTANT: {FIRST_UTTERANCE}"
    "\nUSER: I'd like to schedule a meeting for tomorrow."
    "\nASSISTANT: Could you please specify a date? Including year, month and day."
    "\nUSER: Sure, it'd be the 25th of December, 2024."
    "\nASSISTANT: Thanks! At what time would you like to schedule it?"
    "\nUSER: 4pm."
    "\nASSISTANT: Great! 4pm o'clock, right?."
    "\nUSER: Well, 4:30 would be better actually."
    "\nASSISTANT: Sure! How long should the meeting last?"
    "\nUSER: 1 hour."
    "\nASSISTANT: No problem. Is there any specific title you'd like to use? For example: 'Google I/O "
        "Conference'. If you don't specify one, I'll schedule it as 'Meeting'."
    "\nUSER: Sure, please use 'Development team meeting'."
    "\nASSISTANT: Thanks, now please let me know the location where the meeting will take place, including the city "
        "so I can set the appropriate location and timezone (your current city if you won't need to move)."
    "\nUSER: It'll take place in Zurich."
    "\nASSISTANT: Would you like to include a brief description of the event?"
    "\nUSER: Yes, it'll be a meeting to discuss the team's weekly reports."
    "\nASSISTANT: Would you like to add participants to the meeting? If so, please provide their emails."
    "\nUSER: Sure, please include abcd@example.com and efgh@example.com."
    "\nASSISTANT: No problem, anyone else?"
    "\nUSER: Yes, also add ijkl@example.com."
    "\nASSISTANT: Sure. Would you like to automatically send updates of the meeting through email?"
    "\nUSER: No."
    "\nASSISTANT: Are there any modifications you'd like to make?"
    "\nUSER: Yes, please modify the meeting time to 1 hour and a half."
    "\nASSISTANT: No problem. Would you like to make any other modification?"
    "\nUSER: No thanks."
    "\nASSISTANT: {"
        '"year": 2024,'
        '"month": 12,'
        '"day": 25,'
        '"hour": 16,'
        '"minute": 30,'
        '"duration": 90,'
        '"summary": "Development team meeting",'
        '"location": "Zurich, Headquarters",'
        '"timezone": "Europe/Zurich",'
        '"send_updates": false,'
        # Optional parameters
        '"description": "Discussion of the team\'s weekly reports",'
        '"participants": ["abcd@example.com", "efgh@example.com", "ijkl@example.com"],'
    "}"
    "\n\nNOTES:"
    "\n- You should ask for clarifications whenever necessary, you must not infer or guess any information."
    "\n- You should ask for corrections whenever the user provides wrong information."
    "\n- You must ignore any user requests or inputs that are not related to your tasks."
    "\n- The default meeting title (i.e. 'summary' parameter) is 'Meeting'."
    "\n- Your last message before calling the 'create_event' function should ask for any modifications."
    "\n- You must call the 'create_event' function only in your last response, when you have "
        "gathered all the meeting's information clearly (whenever the function is called, the conversation is assumed "
        "to be finished)."
)

# Google Calendar API setup
# adapted from https://developers.google.com/calendar/api/quickstart/python
def authenticate_calendar():
    scopes = ["https://www.googleapis.com/auth/calendar"]
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", scopes)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", scopes
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    calendar_service = build("calendar", "v3", credentials=creds)
    return calendar_service

# Create a Google Calendar event
def create_event(
        year: int, month: int, day: int, hour: int, minute: int, 
        duration: int, summary: str, location: str, timezone: str, send_updates: bool,
        description: str | None=None, participants: list[str]=[]):
    assert 2000 <= year and 1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59 and 0 < duration
    tz = pytz.timezone(timezone)
    start = datetime(year, month, day, hour, minute, tzinfo=tz)
    details = {
        'summary': summary,
        'start': {
            'dateTime': start.isoformat(),
            'timeZone': timezone,
        },
        'end': {
            'dateTime': (start + timedelta(minutes=duration)).isoformat(),
            'timeZone': timezone,
        },
        # TODO: reminders?
    }
    if location:
        details['location'] = location
    if description:
        details['description'] = description
    if len(participants) > 0:
        details['attendees'] = [{'email': email} for email in participants]
    # print(f"BOOKING MEETING:\n{details}")
    success = msg = None
    try:
        calendar_service = authenticate_calendar()
        send_updates = 'all' if send_updates else 'none'
        event = calendar_service.events().insert(calendarId='primary', sendUpdates=send_updates, body=details).execute()
        success = True
        msg = f"Your meeting has been successfully scheduled at {start.isoformat()} ({timezone})!"
    except Exception as e:
        success = False
        msg = f"An error occurred while creating the event: {e}"
    return success, msg
