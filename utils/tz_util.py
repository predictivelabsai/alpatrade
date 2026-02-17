"""
Timezone utilities — all user-facing timestamps in US Eastern Time.

Uses stdlib zoneinfo (no extra dependencies).
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    """Current time in US Eastern."""
    return datetime.now(ET)


def to_et(dt) -> datetime:
    """Convert datetime/string/pandas Timestamp to ET-aware datetime."""
    if dt is None:
        return None
    # Handle strings
    if isinstance(dt, str):
        dt = dt.strip()
        if not dt or dt == "n/a":
            return None
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            # Try pandas as fallback
            import pandas as pd
            dt = pd.to_datetime(dt).to_pydatetime()
    # Handle pandas Timestamp
    try:
        import pandas as pd
        if isinstance(dt, pd.Timestamp):
            dt = dt.to_pydatetime()
    except ImportError:
        pass
    if not isinstance(dt, datetime):
        return None
    # If naive, assume UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET)


def format_et(dt, fmt: str = "%Y-%m-%d %H:%M ET") -> str:
    """Convert + format as ET string. Returns '-' for None."""
    converted = to_et(dt)
    if converted is None:
        return "-"
    return converted.strftime(fmt)
