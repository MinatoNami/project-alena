"""Displaying times in the timezone you actually live in.

**Storage stays UTC.** Every record is written with an explicit `+00:00`
offset and that does not change. It is what makes the history sortable as
plain strings, what keeps the database meaningful if it is ever read on
another machine, and what stops an hour going missing or repeating when a
zone shifts. A database of local times is a database you cannot order.

What changes is the reading. A scan stamped `18:01+00:00` happened at 02:01
in Singapore, and reporting the first number to someone who lives in the
second is how you conclude the nightly job did not run.

So conversion happens once, here, at the edge -- and the same configured zone
is handed to the dashboard so the CLI and the browser never disagree, even if
the browser is somewhere else.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.core.controller.logger import logger

DEFAULT_TIMEZONE = "Asia/Singapore"

DATETIME_FORMAT = "%Y-%m-%d %H:%M"
TIME_FORMAT = "%H:%M"
DATE_FORMAT = "%Y-%m-%d"


def timezone_name() -> str:
    return (os.getenv("ALENA_TIMEZONE") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE


def zone() -> ZoneInfo:
    """The display zone, falling back to UTC if it is not installed.

    A misconfigured zone should degrade to a readable time rather than break
    every command that prints one.
    """
    name = timezone_name()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(f"Unknown ALENA_TIMEZONE {name!r}; showing UTC")
        return ZoneInfo("UTC")


def parse(stamp: Optional[str]) -> Optional[datetime]:
    """Read a stored timestamp.

    Anything without an offset is taken as UTC, because that is what
    everything here has always written -- guessing local would silently shift
    older rows by the size of the offset.
    """
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def to_local(stamp: Optional[str]) -> Optional[datetime]:
    parsed = parse(stamp)
    return parsed.astimezone(zone()) if parsed else None


def local(stamp: Optional[str], fmt: str = DATETIME_FORMAT, default: str = "") -> str:
    """A stored timestamp, as a string in the display zone."""
    moment = to_local(stamp)
    return moment.strftime(fmt) if moment else default


def local_time(stamp: Optional[str], default: str = "") -> str:
    return local(stamp, TIME_FORMAT, default)


def local_date(stamp: Optional[str], default: str = "") -> str:
    return local(stamp, DATE_FORMAT, default)


def now() -> str:
    """The current time, in the display zone, for reading."""
    return datetime.now(zone()).strftime(DATETIME_FORMAT)


def label() -> str:
    """How the zone is named where a reader might otherwise assume UTC."""
    moment = datetime.now(zone())
    return f"{timezone_name()} ({moment.strftime('%z')})"
