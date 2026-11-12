"""What day it is, for the models.

No stage of the agent was ever told the date. Asked on Wednesday Nov 11 2026
how CoreWeave's earnings "this week" compared with expectations, it led with
"CoreWeave did not report earnings this week, as its next earnings report is
scheduled for February 26, 2027" - and then, one bullet down, quoted the
report it had filed on Monday. A model cannot place "this week", "yesterday" or
"recent" without a calendar, so every prompt that reads a question gets one.
Dates are New York dates: the server runs on UTC, which rolls over at 7-8pm
New York time, exactly when after-the-close reports land.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def ny_now() -> datetime:
    return datetime.now(NY)


def ny_today() -> date:
    return ny_now().date()


def week_of(d: date) -> tuple[date, date]:
    """Monday and Sunday of d's week."""
    mon = d - timedelta(days=d.weekday())
    return mon, mon + timedelta(days=6)


def _day(d: date) -> str:
    return f"{d:%A} {d:%B} {d.day}"


def clock_line() -> str:
    now = ny_now()
    d = now.date()
    mon, sun = week_of(d)
    hour = now.strftime("%I:%M %p").lstrip("0")
    return (f"[Today is {_day(d)}, {d.year}, {hour} New York time ({d.isoformat()}). "
            f"\"This week\" is {_day(mon)} to {_day(sun)} ({mon.isoformat()} to {sun.isoformat()}); "
            f"\"yesterday\" is {_day(d - timedelta(days=1))}. Compare every date in the data "
            f"with today before calling something upcoming, recent or past.]")
