"""The dashboard's API.

The write endpoint gets most of the attention: it can approve a
recommendation, and an approved recommendation is what authorises the action
agent to write to a repository.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from modules.improve.decide import ACCEPTED, RECOMMENDED
from modules.improve.persistence import recommendations_for
from modules.improve.research import ingest_text
from modules.improve.review_run import recommend_repository, review_repository_async
from modules.improve.web.api import allowed_origins, create_app

RESEARCH = """# Research: sample

Repository: sample
Source: chatgpt-work

## A worthwhile change

Something substantial.

Evidence: https://a https://b
"""

SUPPORTED = {
    "verdict": "supported", "value": 0.8, "fit": 0.8, "cost": 0.4,
    "risk": 0.2, "confidence": 0.85,
}

DASHBOARD = {"X-Alena-Dashboard": "1"}


async def codex(server, tool, arguments, **kwargs):
    text = f"Assessment.\n\n```json\n{json.dumps(SUPPORTED)}\n```"
    line = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": text}}
    )
    return SimpleNamespace(content=[SimpleNamespace(text=line)])


@pytest.fixture
def client(registry_file, monkeypatch):
    monkeypatch.setenv("ALENA_REPOSITORIES", registry_file)
    return TestClient(create_app())


@pytest.fixture
def registry_file(tmp_path, repo):
    import yaml

    path = tmp_path / "repositories.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "repositories": [
                    {"id": "sample", "name": "Sample", "workspace": {"path": str(repo)}}
                ]
            }
        )
    )
    return str(path)


@pytest.fixture
def queued(repository, registry_file, monkeypatch):
    """One recommendation sitting in the queue, awaiting a decision."""
    import asyncio

    monkeypatch.setenv("ALENA_REPOSITORIES", registry_file)
    ingest_text(repository, RESEARCH, use_embeddings=False)
    asyncio.run(review_repository_async(repository, executor=codex))
    recommend_repository(repository)
    return recommendations_for("sample", RECOMMENDED)[0]["id"]


# -- reading ---------------------------------------------------------------


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_status_reports_the_pipeline(client):
    body = client.get("/api/status").json()

    assert body["coverage"]["repositories"] == 1
    assert {s["name"] for s in body["stages"]} == {
        "unreviewed", "unscored", "undecided", "unimplemented", "unresolved",
    }
    assert body["waiting_on_you"] == 0


def test_repositories_lists_the_registry(client):
    assert [r["id"] for r in client.get("/api/repositories").json()] == ["sample"]


def test_an_unknown_repository_is_a_404(client):
    assert client.get("/api/repositories/nope").status_code == 404


def test_an_unscanned_repository_is_a_404_that_says_what_to_run(client):
    body = client.get("/api/repositories/sample").json()
    assert "scan" in body["detail"]


def test_the_queue_carries_what_is_needed_to_decide(client, queued):
    rows = client.get("/api/queue").json()

    assert len(rows) == 1
    assert rows[0]["id"] == queued
    assert rows[0]["repository_name"] == "Sample"
    assert rows[0]["body"]
    assert rows[0]["breakdown"]["priority"]


def test_one_recommendation_carries_its_history(client, queued):
    body = client.get(f"/api/recommendations/{queued}").json()

    assert body["id"] == queued
    assert body["history"] == []
    assert body["implementations"] == []


def test_an_unknown_recommendation_is_a_404(client):
    assert client.get("/api/recommendations/999").status_code == 404


def test_portfolio_and_tools_answer(client):
    assert "repositories" in client.get("/api/portfolio").json()
    assert isinstance(client.get("/api/tools").json(), list)


# -- deciding --------------------------------------------------------------


def test_accepting_moves_the_recommendation(client, queued):
    response = client.post(
        f"/api/recommendations/{queued}/decision",
        json={"decision": "accept"},
        headers=DASHBOARD,
    )

    assert response.status_code == 200
    assert response.json()["to_status"] == ACCEPTED
    assert recommendations_for("sample")[0]["status"] == ACCEPTED


def test_accepting_points_at_the_command_that_implements(client, queued):
    """The dashboard approves; implementing stays something you watch."""
    body = client.post(
        f"/api/recommendations/{queued}/decision",
        json={"decision": "accept"},
        headers=DASHBOARD,
    ).json()

    assert body["next"] == f"alena-improve implement sample {queued}"


def test_rejecting_without_a_reason_is_refused(client, queued):
    response = client.post(
        f"/api/recommendations/{queued}/decision",
        json={"decision": "reject"},
        headers=DASHBOARD,
    )

    assert response.status_code == 422
    assert "requires a reason" in response.json()["detail"]
    assert recommendations_for("sample")[0]["status"] == RECOMMENDED


def test_an_illegal_transition_says_what_is_possible(client, queued):
    response = client.post(
        f"/api/recommendations/{queued}/decision",
        json={"decision": "successful"},
        headers=DASHBOARD,
    )

    assert response.status_code == 422
    assert "Cannot go from" in response.json()["detail"]


def test_an_unknown_decision_is_rejected(client, queued):
    response = client.post(
        f"/api/recommendations/{queued}/decision",
        json={"decision": "obliterate"},
        headers=DASHBOARD,
    )

    assert response.status_code == 400
    assert "accept" in response.json()["detail"]


def test_deciding_on_an_unknown_recommendation_is_a_404(client):
    assert client.post(
        "/api/recommendations/999/decision",
        json={"decision": "accept"},
        headers=DASHBOARD,
    ).status_code == 404


# -- what stops a page you did not open from approving something -----------


def test_a_decision_without_the_dashboard_header_is_refused(client, queued):
    """A browser will send a simple cross-origin POST to a loopback service.
    Requiring a custom header forces a preflight, which an unlisted origin
    fails -- so the POST never arrives."""
    response = client.post(
        f"/api/recommendations/{queued}/decision", json={"decision": "accept"}
    )

    assert response.status_code == 403
    assert "X-Alena-Dashboard" in response.json()["detail"]
    assert recommendations_for("sample")[0]["status"] == RECOMMENDED


def test_reading_does_not_need_the_header(client):
    assert client.get("/api/status").status_code == 200


def test_only_the_dashboards_own_origins_are_allowed(monkeypatch):
    monkeypatch.delenv("ALENA_DASHBOARD_ORIGINS", raising=False)
    origins = allowed_origins()

    assert all("localhost" in o or "127.0.0.1" in o for o in origins)
    assert "*" not in origins


def test_the_origins_can_be_configured(monkeypatch):
    monkeypatch.setenv("ALENA_DASHBOARD_ORIGINS", "http://a.test, http://b.test")
    assert allowed_origins() == ["http://a.test", "http://b.test"]


def test_the_api_offers_no_way_to_implement(client):
    """Writing to a repository is not something a browser initiates here."""
    paths = {route.path for route in client.app.routes}
    assert not any("implement" in path for path in paths)


# -- serving the built dashboard -------------------------------------------


def test_an_unknown_api_path_is_a_json_404(client):
    """The SPA fallback must not answer for /api. A client that asked for JSON
    and got a page of HTML with a 200 on it has no way to tell."""
    response = client.get("/api/definitely-not-a-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_the_root_says_how_to_build_when_the_dashboard_is_not_built(monkeypatch, tmp_path):
    """Missing is a normal state -- the API is useful on its own."""
    from modules.improve.web import api as api_module

    monkeypatch.setattr(api_module, "BUILT_DASHBOARD", tmp_path / "nothing")
    built = TestClient(api_module.create_app())

    body = built.get("/").json()
    assert body["dashboard"] == "not built"
    assert "npm run generate" in body["build_it"]


def test_a_client_route_falls_through_to_the_shell(monkeypatch, tmp_path):
    """A single-page app owns its own routing; /queue has no file behind it."""
    from modules.improve.web import api as api_module

    public = tmp_path / "public"
    (public / "_nuxt").mkdir(parents=True)
    (public / "index.html").write_text("<html>shell</html>")
    monkeypatch.setattr(api_module, "BUILT_DASHBOARD", public)
    built = TestClient(api_module.create_app())

    assert built.get("/queue").text == "<html>shell</html>"
    assert built.get("/repositories/luma-index").text == "<html>shell</html>"


def test_a_path_cannot_walk_out_of_the_build_directory(monkeypatch, tmp_path):
    from modules.improve.web import api as api_module

    public = tmp_path / "public"
    (public / "_nuxt").mkdir(parents=True)
    (public / "index.html").write_text("<html>shell</html>")
    (tmp_path / "secret.txt").write_text("do not serve me")
    monkeypatch.setattr(api_module, "BUILT_DASHBOARD", public)
    built = TestClient(api_module.create_app())

    for attempt in ("../secret.txt", "..%2Fsecret.txt", "_nuxt/../../secret.txt"):
        response = built.get(f"/{attempt}")
        assert "do not serve me" not in response.text


# -- proposing an idea -----------------------------------------------------


def test_proposing_records_an_observation(client):
    response = client.post(
        "/api/observations",
        json={"repository_id": "sample", "title": "Cache thumbnails", "body": "Detail."},
        headers=DASHBOARD,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["observation_id"]
    assert not body["duplicate"]


def test_proposing_the_same_thing_twice_says_so(client):
    payload = {"repository_id": "sample", "title": "Cache thumbnails", "body": "Detail."}
    client.post("/api/observations", json=payload, headers=DASHBOARD)

    second = client.post("/api/observations", json=payload, headers=DASHBOARD).json()

    assert second["duplicate"]
    assert "duplicate" in second["duplicate_reason"]


def test_proposing_needs_the_dashboard_header(client):
    """It is state-changing, like every other write here."""
    response = client.post(
        "/api/observations",
        json={"repository_id": "sample", "title": "X", "body": ""},
    )

    assert response.status_code == 403


def test_proposing_for_an_unknown_repository_is_a_404(client):
    response = client.post(
        "/api/observations",
        json={"repository_id": "nope", "title": "X", "body": ""},
        headers=DASHBOARD,
    )

    assert response.status_code == 404


def test_a_proposal_with_no_title_is_refused(client):
    response = client.post(
        "/api/observations",
        json={"repository_id": "sample", "title": "", "body": "Detail."},
        headers=DASHBOARD,
    )

    assert response.status_code == 422


# -- history ---------------------------------------------------------------


def test_history_returns_a_timeline(client, repo):
    from modules.improve.registry import load_registry
    from modules.improve.scan_run import scan_repository

    scan_repository(load_registry().resolve("sample"), summarize=False)

    body = client.get("/api/history").json()
    assert body["events"]
    assert body["counts"]["scan"] == 1
    assert "review" in body["kinds"]


def test_history_can_be_filtered_by_kind(client, repo):
    from modules.improve.registry import load_registry
    from modules.improve.scan_run import scan_repository

    scan_repository(load_registry().resolve("sample"), summarize=False)

    assert client.get("/api/history?kind=review").json()["events"] == []
    assert client.get("/api/history?kind=scan").json()["events"]


def test_an_unknown_kind_is_a_400(client):
    response = client.get("/api/history?kind=invented")

    assert response.status_code == 400
    assert "scan" in response.json()["detail"]


def test_history_for_an_unknown_repository_is_a_404(client):
    assert client.get("/api/history?repository_id=nope").status_code == 404


def test_history_needs_no_dashboard_header(client):
    """It only reads."""
    assert client.get("/api/history").status_code == 200
