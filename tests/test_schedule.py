"""The schedule contract: 21:00 Asia/Jakarta must be what actually fires.

A wrong cron here fails silently: the job runs, the report renders, and the
prices are a day stale. These tests pin the conversion and the weekday choice so
a future edit to the workflow cannot quietly break it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from buffett.config import load_config

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/daily-brief.yml"
JAKARTA = ZoneInfo("Asia/Jakarta")


def _cron() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r'-\s*cron:\s*"([^"]+)"', text)
    assert match, "no cron expression found in the daily-brief workflow"
    return match.group(1)


def test_cron_hour_is_9pm_jakarta():
    minute, hour, _dom, _month, _dow = _cron().split()
    fires_at = datetime(2026, 8, 18, int(hour), int(minute), tzinfo=timezone.utc)
    local = fires_at.astimezone(JAKARTA)

    assert (local.hour, local.minute) == (21, 0)


def test_cron_matches_the_configured_schedule():
    cfg = load_config()
    minute, hour, *_ = _cron().split()
    fires_at = datetime(2026, 8, 18, int(hour), int(minute), tzinfo=timezone.utc)
    local = fires_at.astimezone(ZoneInfo(cfg.schedule.timezone))

    assert local.hour == cfg.schedule.hour
    assert local.minute == cfg.schedule.minute


def test_jakarta_has_no_daylight_saving():
    """The single-offset assumption is what makes one fixed cron correct."""
    january = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc).astimezone(JAKARTA)
    july = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc).astimezone(JAKARTA)

    assert january.utcoffset() == july.utcoffset()
    assert january.hour == july.hour == 21


def test_runs_tuesday_through_saturday():
    """Monday would only re-read Friday's close, which Saturday already covered."""
    _minute, _hour, _dom, _month, dow = _cron().split()
    assert dow == "2-6", (
        "expected Tue-Sat: a 14:00 UTC run reads the previous calendar day's US "
        f"close, so Monday adds nothing. Found {dow!r}"
    )


@pytest.mark.parametrize(
    "run_day_utc,expected_us_session",
    [
        # A 14:00 UTC run happens before that day's New York close (20:00 or
        # 21:00 UTC), so the freshest complete session is the day before.
        ("2026-08-18", "2026-08-17"),  # Tuesday reads Monday
        ("2026-08-19", "2026-08-18"),  # Wednesday reads Tuesday
        ("2026-08-22", "2026-08-21"),  # Saturday reads Friday
    ],
)
def test_run_reads_the_previous_session(run_day_utc: str, expected_us_session: str):
    from datetime import date, timedelta

    run_day = date.fromisoformat(run_day_utc)
    assert run_day - timedelta(days=1) == date.fromisoformat(expected_us_session)
    # Cron day-of-week 2-6 is Tuesday to Saturday, which for ISO weekdays
    # (Mon=1 .. Sun=7) is the same 2..6 range.
    assert run_day.isoweekday() in {2, 3, 4, 5, 6}
    # The session it reads must itself be a trading weekday (Mon-Fri).
    assert date.fromisoformat(expected_us_session).isoweekday() <= 5


def test_workflow_declares_write_permission_for_committing_reports():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "contents: write" in text
    assert "concurrency:" in text, "overlapping runs would fight over the cache"
