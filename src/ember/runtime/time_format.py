#!/usr/bin/env python3
"""Shared helpers for parsing and displaying heterogeneous task timestamps."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import re
from datetime import datetime, timezone


# Common timezone abbreviations mapped to numeric offsets. These are used only
# to normalize legacy task-card timestamps for display/sorting; new records
# should use numeric offsets or UTC.
_TZ_ABBR_OFFSETS = {
    "CST": "+0800",
    "CEST": "+0200",
    "EST": "-0500",
    "EDT": "-0400",
    "PST": "-0800",
    "PDT": "-0700",
    "GMT": "+0000",
    "UTC": "+0000",
}


def _normalize_timestamp_text(text: str) -> str:
    """Make heterogeneous timestamp strings parseable by datetime.strptime.

    - Replaces a trailing timezone abbreviation with its numeric offset.
    - Converts ``+HH:MM`` / ``-HH:MM`` offsets to ``+HHMM`` / ``-HHMM``.
    - Removes whitespace between the local time and the trailing offset.
    """
    normalized = text
    # First handle legacy abbreviations.
    for abbr, offset in _TZ_ABBR_OFFSETS.items():
        if normalized.upper().endswith(abbr):
            normalized = normalized[: len(normalized) - len(abbr)].rstrip() + offset
            break
    # Python 3.9 strptime %z expects +HHMM (no colon) and no space before it.
    normalized = re.sub(r"\s*([+-]\d{2}):?(\d{2})\s*$", r"\1\2", normalized)
    return normalized


def format_display_time(value: str | None) -> str:
    """Convert various stored timestamps to a human-friendly date+minute string.

    - Values with time information are shown as ``YYYY-MM-DD HH:MM``.
    - Date-only values are shown as ``YYYY-MM-DD``.
    - Unparseable input is returned unchanged.
    """
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    normalized = _normalize_timestamp_text(text)

    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M%z",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M%z",
        "%Y-%m-%d %H:%M",
    ):
        try:
            dt = datetime.strptime(normalized, fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue

    # Date only
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        pass

    return text


def now_iso_string(tz_offset_hours: int = 8) -> str:
    """Return the current local time as a task-card-friendly ISO string.

    Format: ``YYYY-MM-DD HH:MM:SS+HH:MM``. The default offset is +08:00.
    This matches the frontmatter style already used by several existing tasks.
    """
    sign = "+" if tz_offset_hours >= 0 else "-"
    hours = abs(tz_offset_hours)
    offset = f"{sign}{hours:02d}:00"
    now = datetime.now()
    return now.strftime(f"%Y-%m-%d %H:%M:%S{offset}")


def parse_sort_datetime(value: str | None) -> datetime:
    """Parse heterogeneous updated_at strings into a timezone-aware datetime for sorting.

    Date-only values (e.g. 2026-07-12) are treated as end-of-day in the local
    timezone (+08:00) so they sort after any timed record on the same day.
    """
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    normalized = _normalize_timestamp_text(text).replace(" ", "T", 1)
    if len(normalized) == 10 and normalized[4] == "-" and normalized[7] == "-":
        normalized = f"{normalized}T23:59:59+0800"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M%z",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(normalized, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.min.replace(tzinfo=timezone.utc)
