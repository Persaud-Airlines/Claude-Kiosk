"""Timezone helpers: IANA -> POSIX TZ (for ESP32 `setenv("TZ")`), local-day boundaries."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from importlib import resources
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

FALLBACK_POSIX = {
    "America/Toronto": "EST5EDT,M3.2.0,M11.1.0",
    "America/New_York": "EST5EDT,M3.2.0,M11.1.0",
    "America/Chicago": "CST6CDT,M3.2.0,M11.1.0",
    "America/Denver": "MST7MDT,M3.2.0,M11.1.0",
    "America/Vancouver": "PST8PDT,M3.2.0,M11.1.0",
    "America/Los_Angeles": "PST8PDT,M3.2.0,M11.1.0",
    "America/Halifax": "AST4ADT,M3.2.0,M11.1.0",
    "America/Winnipeg": "CST6CDT,M3.2.0,M11.1.0",
    "America/Edmonton": "MST7MDT,M3.2.0,M11.1.0",
    "America/Regina": "CST6",
    "America/St_Johns": "NST3:30NDT,M3.2.0,M11.1.0",
    "UTC": "UTC0",
}


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


@lru_cache(maxsize=512)
def posix_tz_for(iana: str) -> str:
    """Extract the POSIX TZ footer from the TZif v2+ file backing an IANA zone."""
    data: bytes | None = None
    try:
        parts = iana.split("/")
        pkg = ".".join(["tzdata", "zoneinfo", *parts[:-1]])
        data = resources.files(pkg).joinpath(parts[-1]).read_bytes()
    except (ModuleNotFoundError, FileNotFoundError, OSError, ValueError):
        for base in ("/usr/share/zoneinfo", "/var/db/timezone/zoneinfo"):
            try:
                with open(f"{base}/{iana}", "rb") as fh:
                    data = fh.read()
                break
            except OSError:
                continue
    if data and data[:4] == b"TZif" and data[4:5] in (b"2", b"3", b"4"):
        footer = data.rstrip(b"\n").rsplit(b"\n", 1)[-1].decode("ascii", "ignore").strip()
        if footer:
            return footer
    return FALLBACK_POSIX.get(iana, "UTC0")


def local_day_bounds_utc(tz_name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    start_local = datetime.combine(local.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def local_week_start_utc(tz_name: str, now: datetime | None = None) -> datetime:
    tz = ZoneInfo(tz_name)
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    monday = local.date() - timedelta(days=local.weekday())
    return datetime.combine(monday, time.min, tzinfo=tz).astimezone(timezone.utc)


def format_local(dt: datetime, tz_name: str) -> str:
    return dt.astimezone(ZoneInfo(tz_name)).strftime("%I:%M:%S %p").lstrip("0")


def common_timezones() -> list[str]:
    preferred = [z for z in FALLBACK_POSIX if z != "UTC"]
    rest = sorted(z for z in available_timezones() if z.startswith(("America/", "Europe/", "Pacific/", "Asia/")))
    return preferred + [z for z in rest if z not in preferred] + ["UTC"]
