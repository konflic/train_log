"""Small query-parameter helpers shared by resource routers.

History and statistics date filters are local calendar dates (PLAN.md §4, §7).
Both `GET /workouts` and `GET /stats/summary` accept them through one explicit
annotation so parsing, rejection messages, and supported bounds cannot drift
apart; this is deliberately not a generic query framework.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Query
from pydantic import BeforeValidator

# The bounds keep the UTC boundary arithmetic (±1 day, ±14 h offset) inside
# years that format as canonical four-digit UTC text.
MIN_HISTORY_DATE = date(1900, 1, 1)
MAX_HISTORY_DATE = date(9998, 12, 31)


def parse_history_date(value: object) -> date:
    """Accept an ISO calendar date, never a coerced timestamp."""
    if not isinstance(value, str) or (
        len(value) != 10
        or value[4] != "-"
        or value[7] != "-"
        or not (value[:4] + value[5:7] + value[8:]).isdigit()
    ):
        raise ValueError("date must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("date must be a valid calendar date") from None


HistoryDate = Annotated[
    date,
    BeforeValidator(parse_history_date),
    Query(ge=MIN_HISTORY_DATE, le=MAX_HISTORY_DATE),
]
