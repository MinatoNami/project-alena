import pytest

from modules.gateway.contracts import SideEffect, ToolContract


def test_side_effects_are_ordered_least_to_most_consequential():
    assert SideEffect.DESTRUCTIVE.at_least(SideEffect.READ_ONLY)
    assert SideEffect.REMOTE_WRITE.at_least(SideEffect.REPOSITORY_WRITE)
    assert not SideEffect.READ_ONLY.at_least(SideEffect.LOCAL_WRITE)
    assert SideEffect.READ_ONLY.at_least(SideEffect.READ_ONLY)


def test_every_side_effect_has_a_rank():
    assert len({e.rank for e in SideEffect}) == len(list(SideEffect))


def test_parse_rejects_an_unknown_value_and_says_what_is_valid():
    with pytest.raises(ValueError, match="read_only"):
        SideEffect.parse("probably_fine")


def test_missing_required_arguments_are_named():
    contract = ToolContract(
        name="t",
        input_schema={"type": "object", "required": ["a", "b"], "properties": {}},
    )
    with pytest.raises(ValueError, match="a, b"):
        contract.validate_arguments({})


def test_extra_arguments_are_left_to_the_tool():
    """The tool validates its own schema; duplicating that here would drift."""
    contract = ToolContract(
        name="t", input_schema={"type": "object", "required": ["a"], "properties": {}}
    )
    contract.validate_arguments({"a": 1, "unexpected": 2})


def test_non_object_arguments_are_rejected():
    with pytest.raises(ValueError, match="must be an object"):
        ToolContract(name="t").validate_arguments(["not", "a", "dict"])


def test_openai_rendering_uses_the_input_schema_verbatim():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    rendered = ToolContract(name="t", description="d", input_schema=schema).to_openai_tool()

    assert rendered["function"]["name"] == "t"
    assert rendered["function"]["parameters"] == schema


def test_a_tool_with_no_schema_still_renders():
    rendered = ToolContract(name="t").to_openai_tool()
    assert rendered["function"]["parameters"]["type"] == "object"
