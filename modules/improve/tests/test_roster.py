"""Which agent does which segment.

The point of the roster is not the mapping -- it is that an impossible mapping
is refused when the file is read, with the reason, rather than at 02:00 by an
agent that cannot do the thing it was handed.
"""

import pytest

from modules.improve.agents.roster import (
    ACTION,
    AGENTS,
    RESEARCH,
    REVIEW,
    SCAN,
    SEGMENTS,
    RosterError,
    load,
    matrix,
    parse,
    resolve,
)


def test_the_defaults_are_what_ran_before_any_of_this_was_configurable():
    assignment = resolve()

    assert assignment.agent_for(SCAN) == "local"
    assert assignment.agent_for(REVIEW) == "codex"
    assert assignment.agent_for(ACTION) == "codex"


def test_a_segment_can_be_reassigned():
    assignment = resolve({REVIEW: "claude"})

    assert assignment.agent_for(REVIEW) == "claude"
    assert assignment.agent_for(ACTION) == "codex", "the rest keep their defaults"


def test_a_hosted_agent_cannot_be_given_the_one_segment_that_writes():
    """The reason is structural, and the error says so.

    A Claude routine runs on Anthropic's side. It can read a diff and judge it;
    it cannot commit to a checkout on this machine, and no amount of wiring
    changes that.
    """
    with pytest.raises(RosterError) as exc:
        resolve({ACTION: "claude"})

    assert "structural" in str(exc.value)
    assert "codex" in str(exc.value), "the error names who can"


def test_a_source_label_cannot_be_given_work():
    """`chatgpt-work` is what a dropped document is stamped with, not a client."""
    with pytest.raises(RosterError) as exc:
        resolve({REVIEW: "chatgpt-work"})

    assert "no endpoint" in str(exc.value).lower()


def test_research_may_name_an_agent_alena_cannot_call():
    """The one exemption, and it is how research already works: documents
    arrive on somebody else's schedule and the cycle ingests them."""
    assignment = resolve({RESEARCH: "chatgpt-work"})

    assert assignment.agent_for(RESEARCH) == "chatgpt-work"


def test_an_unknown_agent_is_named_along_with_the_real_ones():
    with pytest.raises(RosterError) as exc:
        resolve({REVIEW: "gpt-9"})

    assert "gpt-9" in str(exc.value)
    assert "codex" in str(exc.value)


def test_an_unknown_segment_is_refused():
    with pytest.raises(RosterError):
        resolve({"deploying": "codex"})


def test_a_missing_file_means_the_defaults_rather_than_an_error(tmp_path):
    """Unlike the tool policy, absence here is not a failure: it means keep
    doing what you were doing."""
    assignment = load(str(tmp_path / "nothing.yaml"))

    assert assignment.agent_for(REVIEW) == "codex"


def test_the_shipped_configuration_is_usable():
    """The file in config/ must load, or every command that reads it stops."""
    assert load().agent_for(SCAN) in AGENTS


def test_a_file_that_is_not_a_mapping_is_refused():
    with pytest.raises(RosterError):
        parse(["scan", "local"])


def test_every_gap_carries_a_reason():
    """"Unsupported" tells a reader nothing about whether it is a missing
    adapter or an impossibility. Every no has to explain itself."""
    for agent, segments in matrix().items():
        for segment, reason in segments.items():
            if reason is not None:
                assert len(reason) > 20, f"{agent}/{segment} has no real reason"


def test_at_least_one_agent_can_do_each_segment_that_alena_drives():
    """Research is the exception -- nothing drives it yet, by design."""
    for segment in SEGMENTS:
        if segment == RESEARCH:
            continue
        assert any(a.can(segment) for a in AGENTS.values()), segment
