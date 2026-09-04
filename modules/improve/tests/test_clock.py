"""Displaying stored UTC in the zone you live in.

The failure this exists to prevent: a nightly scan that ran at 02:01 in
Singapore is stored as 18:01 the previous day in UTC, and reading the stored
number is how you conclude the job never ran.
"""

import pytest

from modules.improve import clock

SCAN_AT_0201_SINGAPORE = "2026-09-03T18:01:01+00:00"


@pytest.fixture(autouse=True)
def singapore(monkeypatch):
    monkeypatch.setenv("ALENA_TIMEZONE", "Asia/Singapore")


# -- conversion ------------------------------------------------------------


def test_a_stored_utc_stamp_reads_as_local():
    assert clock.local(SCAN_AT_0201_SINGAPORE) == "2026-09-04 02:01"


def test_the_local_date_can_differ_from_the_stored_one():
    """Which is the whole reason this module exists."""
    assert clock.local_date(SCAN_AT_0201_SINGAPORE) == "2026-09-04"
    assert SCAN_AT_0201_SINGAPORE.startswith("2026-09-03")


def test_a_stamp_with_no_offset_is_taken_as_utc():
    """Everything here has always written UTC; guessing local would shift
    older rows by the size of the offset."""
    assert clock.local("2026-09-03T18:01:01") == clock.local(SCAN_AT_0201_SINGAPORE)


def test_a_stamp_in_another_offset_is_converted_correctly():
    assert clock.local("2026-09-03T20:01:01+02:00") == "2026-09-04 02:01"


def test_millisecond_precision_is_accepted():
    assert clock.local("2026-09-03T18:01:01.123+00:00") == "2026-09-04 02:01"


# -- degrading -------------------------------------------------------------


def test_nothing_renders_as_the_default():
    assert clock.local(None, default="—") == "—"
    assert clock.local("", default="—") == "—"


def test_something_unparseable_renders_as_the_default():
    """A malformed row should not take down every command that prints a time."""
    assert clock.local("last Tuesday", default="—") == "—"


def test_an_unknown_zone_falls_back_to_utc(monkeypatch):
    monkeypatch.setenv("ALENA_TIMEZONE", "Mars/Olympus")

    assert clock.local(SCAN_AT_0201_SINGAPORE) == "2026-09-03 18:01"


def test_an_empty_zone_setting_uses_the_default(monkeypatch):
    monkeypatch.setenv("ALENA_TIMEZONE", "   ")

    assert clock.timezone_name() == clock.DEFAULT_TIMEZONE


# -- configuration ---------------------------------------------------------


def test_singapore_is_the_default(monkeypatch):
    monkeypatch.delenv("ALENA_TIMEZONE", raising=False)

    assert clock.timezone_name() == "Asia/Singapore"


def test_the_zone_can_be_changed(monkeypatch):
    monkeypatch.setenv("ALENA_TIMEZONE", "Europe/London")

    assert clock.local(SCAN_AT_0201_SINGAPORE) == "2026-09-03 19:01"


def test_the_label_names_the_zone_and_its_offset():
    label = clock.label()

    assert "Asia/Singapore" in label
    assert "+0800" in label


# -- storage is untouched --------------------------------------------------


def test_records_are_still_written_in_utc():
    """Local times in a database cannot be ordered, and stop meaning anything
    if the database is read anywhere else."""
    from modules.improve.artifacts import utcnow

    assert utcnow().endswith("+00:00")


def test_stored_stamps_still_sort_as_strings():
    from modules.improve.artifacts import utcnow

    first = utcnow()
    second = utcnow()
    assert first <= second
