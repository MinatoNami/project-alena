import pytest

from modules.improve.registry import (
    Capabilities,
    RegistryError,
    parse_registry,
    parse_repository,
)


def entry(**overrides):
    data = {"id": "sample", "workspace": {"path": "/srv/alena/repos/sample"}}
    data.update(overrides)
    return data


def registry(*entries):
    return parse_registry({"repositories": list(entries)})


# -- validation ------------------------------------------------------------


def test_id_must_be_slug_shaped():
    """Ids become path segments and alena:// URIs."""
    with pytest.raises(RegistryError, match="lowercase"):
        parse_repository(entry(id="Sample Project"))


def test_id_is_required():
    with pytest.raises(RegistryError, match="no id"):
        parse_repository({"workspace": {"path": "/srv/x"}})


def test_workspace_is_required():
    with pytest.raises(RegistryError, match="workspace"):
        parse_repository({"id": "sample"})


def test_relative_workspace_is_rejected():
    """It would resolve differently for the CLI, the controller and cron."""
    with pytest.raises(RegistryError, match="absolute"):
        parse_repository(entry(workspace={"path": "repos/sample"}))


def test_duplicate_ids_are_rejected():
    with pytest.raises(RegistryError, match="Duplicate"):
        registry(entry(), entry())


def test_unknown_capability_key_is_rejected():
    with pytest.raises(RegistryError, match="unknown key"):
        parse_repository(entry(capabilities={"deploy": True}))


def test_unknown_agent_role_is_rejected():
    with pytest.raises(RegistryError, match="unknown role"):
        parse_repository(entry(agents={"marketing": ["someone"]}))


# -- secrets ---------------------------------------------------------------


def test_a_key_named_token_is_rejected():
    with pytest.raises(RegistryError, match="credential"):
        registry(entry(source={"token": "anything"}))


def test_a_token_shaped_value_is_rejected():
    with pytest.raises(RegistryError, match="access token"):
        registry(entry(source={"url": "https://ghp_abcdefghijklmnopqrstuvwx@github.com/x"}))


def test_a_nested_secret_is_still_found():
    with pytest.raises(RegistryError, match="credential"):
        registry(entry(source={"auth": {"password": "hunter2"}}))


# -- workspace containment -------------------------------------------------


def test_workspace_must_sit_inside_the_configured_root(monkeypatch, tmp_path):
    monkeypatch.setenv("ALENA_WORKSPACE_ROOT", str(tmp_path / "repos"))
    with pytest.raises(RegistryError, match="outside"):
        parse_repository(entry(workspace={"path": "/etc"}))


def test_workspace_inside_the_root_is_accepted(monkeypatch, tmp_path):
    root = tmp_path / "repos"
    monkeypatch.setenv("ALENA_WORKSPACE_ROOT", str(root))
    parsed = parse_repository(entry(workspace={"path": str(root / "sample")}))
    assert parsed.workspace == root / "sample"


def test_traversal_out_of_the_root_is_rejected(monkeypatch, tmp_path):
    root = tmp_path / "repos"
    monkeypatch.setenv("ALENA_WORKSPACE_ROOT", str(root))
    with pytest.raises(RegistryError, match="outside"):
        parse_repository(entry(workspace={"path": f"{root}/../elsewhere"}))


def test_a_sibling_sharing_a_prefix_is_not_inside_the_root(monkeypatch, tmp_path):
    monkeypatch.setenv("ALENA_WORKSPACE_ROOT", str(tmp_path / "repos"))
    with pytest.raises(RegistryError, match="outside"):
        parse_repository(entry(workspace={"path": str(tmp_path / "repos-evil")}))


# -- capability defaults ---------------------------------------------------


def test_read_capabilities_default_on():
    caps = Capabilities.parse(None, "sample")
    assert caps.research and caps.analyze and caps.plan


def test_write_capabilities_default_off():
    caps = Capabilities.parse(None, "sample")
    assert not (caps.modify or caps.create_branch or caps.create_pr or caps.merge)


def test_merge_cannot_be_enabled_by_omission():
    """The one capability where guessing wrong is unrecoverable."""
    caps = Capabilities.parse({"modify": True, "create_pr": True}, "sample")
    assert caps.modify and caps.create_pr and not caps.merge


# -- resolution ------------------------------------------------------------


def test_unknown_repository_lists_what_is_declared():
    with pytest.raises(RegistryError, match="sample"):
        registry(entry()).resolve("nope")


def test_disabled_repository_is_refused():
    with pytest.raises(RegistryError, match="disabled"):
        registry(entry(enabled=False)).resolve("sample")


def test_disabled_repositories_are_left_out_of_all():
    r = registry(entry(), entry(id="off", enabled=False))
    assert [repo.id for repo in r.all()] == ["sample"]
    assert len(r.all(include_disabled=True)) == 2


def test_resolution_checks_the_requested_capability():
    with pytest.raises(RegistryError, match="modify"):
        registry(entry()).resolve("sample", "modify")


def test_resolution_passes_when_the_capability_is_granted():
    r = registry(entry(capabilities={"modify": True}))
    assert r.resolve("sample", "modify").id == "sample"


def test_unknown_capability_name_is_an_error_not_a_denial():
    with pytest.raises(RegistryError, match="Unknown capability"):
        registry(entry()).resolve("sample", "deploy")


# -- gateway integration ---------------------------------------------------


def test_workspaces_feed_the_gateway_path_guard():
    r = registry(entry(), entry(id="two", workspace={"path": "/srv/alena/repos/two"}))
    assert r.workspaces() == ["/srv/alena/repos/sample", "/srv/alena/repos/two"]


def test_disabled_repositories_are_not_allowed_roots():
    r = registry(entry(), entry(id="off", enabled=False, workspace={"path": "/srv/off"}))
    assert "/srv/off" not in r.workspaces()


# -- agent routing ---------------------------------------------------------


def test_an_empty_agent_list_means_unrestricted():
    """Routing, not permission -- the gateway is what actually refuses."""
    assert parse_repository(entry()).agents.permits("research", "anyone")


def test_a_configured_agent_list_restricts():
    repo = parse_repository(entry(agents={"engineering": ["codex"]}))
    assert repo.agents.permits("engineering", "codex")
    assert not repo.agents.permits("engineering", "claude-code")
