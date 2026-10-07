"""Unit tests for canonical UTC timestamp helpers."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.timestamps import (
    is_expired,
    now_timestamp,
    parse_timestamp,
    timestamp_plus_seconds,
    to_timestamp,
)

CANONICAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_to_timestamp_formats_utc() -> None:
    moment = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    assert to_timestamp(moment) == "2026-03-04T05:06:07Z"


def test_to_timestamp_converts_offset_to_utc() -> None:
    plus_two = datetime(2026, 3, 4, 7, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert to_timestamp(plus_two) == "2026-03-04T05:00:00Z"


def test_to_timestamp_zero_pads_early_years() -> None:
    assert to_timestamp(datetime(999, 1, 2, 3, 4, 5, tzinfo=UTC)) == "0999-01-02T03:04:05Z"


def test_to_timestamp_rejects_naive() -> None:
    with pytest.raises(ValueError, match="naive"):
        to_timestamp(datetime(2026, 3, 4, 5, 6, 7))


def test_now_timestamp_is_canonical() -> None:
    assert CANONICAL.match(now_timestamp())


def test_parse_roundtrip() -> None:
    text = "2026-03-04T05:06:07Z"
    assert to_timestamp(parse_timestamp(text)) == text
    assert parse_timestamp(text).tzinfo is not None


def test_parse_rejects_non_canonical() -> None:
    for bad in ("2026-03-04T05:06:07", "2026-03-04 05:06:07Z", "not-a-timestamp"):
        with pytest.raises(ValueError):
            parse_timestamp(bad)


def test_timestamp_plus_seconds_crosses_day() -> None:
    assert timestamp_plus_seconds("2026-03-04T23:59:59Z", 2) == "2026-03-05T00:00:01Z"


def test_is_expired_boundaries() -> None:
    now = datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)
    assert is_expired("2026-03-04T11:59:59Z", now=now) is True
    # Exactly at the expiry instant counts as expired (<=).
    assert is_expired("2026-03-04T12:00:00Z", now=now) is True
    assert is_expired("2026-03-04T12:00:01Z", now=now) is False
