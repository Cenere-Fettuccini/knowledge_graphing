"""Google Calendar API tools — create, list, and delete events.

Requires OAuth2 credentials downloaded from Google Cloud Console:
    GOOGLE_CALENDAR_CREDENTIALS_PATH  — path to the client_secret JSON file
    GOOGLE_CALENDAR_TOKEN_PATH        — where to cache the OAuth token (auto-created)

First run will open a browser for OAuth consent. Subsequent runs use the cached token.

Usage (CLI):
    python -m src.tools.calendar list
    python -m src.tools.calendar create "Team standup" 2024-05-15T09:00:00+01:00 2024-05-15T09:30:00+01:00
    python -m src.tools.calendar delete <event_id>
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.core.config import settings

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service():
    """Build an authenticated Google Calendar service client."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Calendar requires extra packages:\n"
            "  pip install google-auth-oauthlib google-api-python-client"
        ) from exc

    token_path = Path(settings.google_calendar_token_path)
    creds_path = Path(settings.google_calendar_credentials_path)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise RuntimeError(
                    f"Google Calendar credentials not found at '{creds_path}'.\n"
                    "Download OAuth2 client credentials from Google Cloud Console and "
                    f"save them to that path (or set GOOGLE_CALENDAR_CREDENTIALS_PATH)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), _SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds)


def list_events(max_results: int = 10, calendar_id: str = "primary") -> list[dict]:
    """Return upcoming calendar events, soonest first.

    Returns a list of dicts with id, summary, start, and end fields.
    """
    try:
        service = _get_service()
        now = datetime.now(timezone.utc).isoformat()
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [
            {
                "id": e["id"],
                "summary": e.get("summary", "(no title)"),
                "start": e["start"].get("dateTime", e["start"].get("date")),
                "end": e["end"].get("dateTime", e["end"].get("date")),
                "description": e.get("description", ""),
            }
            for e in result.get("items", [])
        ]
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("Failed to list calendar events: %s", e)
        return [{"error": str(e)}]


def create_event(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    calendar_id: str = "primary",
) -> dict:
    """Create a calendar event and return its id, summary, and htmlLink.

    start_datetime / end_datetime must be ISO 8601 with timezone offset,
    e.g. '2024-05-15T09:00:00+01:00'.
    """
    try:
        service = _get_service()
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_datetime},
            "end": {"dateTime": end_datetime},
        }
        event = service.events().insert(calendarId=calendar_id, body=body).execute()
        return {
            "id": event["id"],
            "summary": event.get("summary"),
            "htmlLink": event.get("htmlLink"),
        }
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("Failed to create calendar event: %s", e)
        return {"error": str(e)}


def delete_event(event_id: str, calendar_id: str = "primary") -> bool:
    """Delete a calendar event by ID. Returns True on success."""
    try:
        service = _get_service()
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return True
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("Failed to delete calendar event %s: %s", event_id, e)
        return False


def _print(data) -> None:
    print(json.dumps(data, indent=2, default=str))


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd, *rest = args

    if cmd == "list":
        n = int(rest[0]) if rest else 10
        _print(list_events(max_results=n))

    elif cmd == "create":
        if len(rest) < 3:
            print("Usage: calendar create <summary> <start_iso> <end_iso> [description]")
            sys.exit(1)
        result = create_event(
            summary=rest[0],
            start_datetime=rest[1],
            end_datetime=rest[2],
            description=rest[3] if len(rest) > 3 else "",
        )
        _print(result)

    elif cmd == "delete":
        if not rest:
            print("Usage: calendar delete <event_id>")
            sys.exit(1)
        ok = delete_event(rest[0])
        print("Deleted." if ok else "Delete failed.")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
