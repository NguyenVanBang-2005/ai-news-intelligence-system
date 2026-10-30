"""Date formats of app/static/js/format.js, run in Node (skipped when Node is not installed).

format.js has no DOM imports, so Node can load it as an ES module. One Node process runs
every case and prints JSON; each test reads its part.
"""

import json
import shutil
import subprocess

import pytest

from app.main import STATIC_DIR

NODE = shutil.which("node")
FORMAT_JS = (STATIC_DIR / "js" / "format.js").as_uri()
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")

SCRIPT = """
const f = await import(process.argv[1]);
const months = Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, "0"));
console.log(JSON.stringify({
  // 15th of each month, 12:00 UTC = 19:00 in Ho Chi Minh City (GMT+7).
  dateTimes: months.map((m) => f.formatDateTime(`2026-${m}-15T12:00:00Z`)),
  shortDays: months.map((m) => f.formatShortDay(`2026-${m}-04`)),
  dayChange: f.formatDateTime("2026-09-30T20:30:00Z"),
  naive: f.formatDateTime("2026-01-02T03:04:05"),
  invalid: [f.formatDateTime(null), f.formatDateTime("nope"), f.formatShortDay("2026-13-01"),
            f.formatShortDay("Oct 24"), f.formatShortDay(null)],
}));
"""


@pytest.fixture(scope="module")
def formatted() -> dict:
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", SCRIPT, FORMAT_JS],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout)


def test_all_twelve_months_use_three_letter_names(formatted: dict) -> None:
    expected = [f"15 {month} 2026, 19:00 GMT+7" for month in MONTHS]
    assert formatted["dateTimes"] == expected
    assert not any("Sept" in text for text in formatted["dateTimes"])


def test_short_day_for_all_twelve_months(formatted: dict) -> None:
    assert formatted["shortDays"] == [f"{month} 4" for month in MONTHS]


def test_time_zone_moves_the_day(formatted: dict) -> None:
    assert formatted["dayChange"] == "01 Oct 2026, 03:30 GMT+7"  # 20:30 UTC on 30 Sep


def test_time_without_zone_is_utc(formatted: dict) -> None:
    assert formatted["naive"] == "02 Jan 2026, 10:04 GMT+7"


def test_invalid_input(formatted: dict) -> None:
    assert formatted["invalid"] == ["Date unknown", "Date unknown", None, None, None]
