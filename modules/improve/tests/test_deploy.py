"""The launchd templates.

Templates ship uninstalled, so nothing exercises them until someone copies one
into ~/Library/LaunchAgents at which point a mistake shows up as a job that
silently never runs. These check the two things that go wrong: malformed XML,
and a schedule that does not say what the README says it does.
"""

import plistlib
from pathlib import Path

import pytest

LAUNCHD = Path(__file__).resolve().parents[3] / "deploy" / "launchd"

EXPECTED = {
    "local.alena.scan": {"Hour": 2, "Minute": 0},
    "local.alena.review": {"Weekday": 3, "Hour": 22, "Minute": 30},
    "local.alena.recommend": {"Weekday": 4, "Hour": 7, "Minute": 0},
}


def plists():
    return sorted(LAUNCHD.glob("*.plist"))


def test_the_templates_are_present():
    assert {p.stem for p in plists()} == set(EXPECTED)


@pytest.mark.parametrize("path", plists(), ids=lambda p: p.stem)
def test_a_template_is_well_formed(path):
    """A double hyphen inside an XML comment is illegal, and easy to write."""
    plistlib.loads(path.read_bytes())


@pytest.mark.parametrize("path", plists(), ids=lambda p: p.stem)
def test_the_schedule_matches_the_documented_cadence(path):
    data = plistlib.loads(path.read_bytes())
    assert data["StartCalendarInterval"] == EXPECTED[data["Label"]]


@pytest.mark.parametrize("path", plists(), ids=lambda p: p.stem)
def test_nothing_runs_the_moment_it_is_loaded(path):
    """Installing a job should not immediately start doing work."""
    assert plistlib.loads(path.read_bytes())["RunAtLoad"] is False


@pytest.mark.parametrize("path", plists(), ids=lambda p: p.stem)
def test_every_template_goes_through_the_wrapper(path):
    data = plistlib.loads(path.read_bytes())
    joined = " ".join(data["ProgramArguments"])
    assert "scripts/alena_improve.sh" in joined


def test_nothing_schedules_the_action_agent():
    """`implement` writes to a repository and requires a recorded human
    acceptance. On a timer, the approval gate would have a way around it."""
    for path in plists():
        joined = " ".join(plistlib.loads(path.read_bytes())["ProgramArguments"])
        assert "implement" not in joined


def test_nothing_schedules_a_live_claude_escalation():
    """The expensive reviewer stays a deliberate act until its rate is known."""
    for path in plists():
        joined = " ".join(plistlib.loads(path.read_bytes())["ProgramArguments"])
        assert "--agent claude" not in joined
