"""Canonical UTC timestamp helpers (PLAN.md §5: `YYYY-MM-DDTHH:MM:SSZ`).

Stored instants are always canonical UTC text; the database CHECK constraints
enforce the same format. Parsing uses `strptime` with the exact format, so
non-canonical values are rejected rather than silently accepted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def to_timestamp(moment: datetime) -> str:
    """Format a timezone-aware datetime as canonical UTC text."""
    if moment.tzinfo is None:
        raise ValueError("naive datetimes are not canonical UTC timestamps")
    utc = moment.astimezone(UTC)
    # strftime does not zero-pad years below 1000 on every supported platform.
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}T"
        f"{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}Z"
    )


def now_timestamp() -> str:
    """Return the current instant as canonical UTC text."""
    return to_timestamp(datetime.now(UTC))


def parse_timestamp(value: str) -> datetime:
    """Parse canonical UTC text into a timezone-aware datetime."""
    return datetime.strptime(value, TIMESTAMP_FORMAT).replace(tzinfo=UTC)


def timestamp_plus_seconds(value: str, seconds: int) -> str:
    """Return canonical UTC text `seconds` after the given timestamp."""
    return to_timestamp(parse_timestamp(value) + timedelta(seconds=seconds))


def is_expired(expires_at: str, *, now: datetime | None = None) -> bool:
    """True when the given expiry instant is at or before `now` (UTC)."""
    moment = datetime.now(UTC) if now is None else now
    return parse_timestamp(expires_at) <= moment
