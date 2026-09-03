"""A read/write HTTP API over the improvement orchestrator.

Another thin adapter, like the MCP server: every endpoint calls a function in
`query.py`, `status.py` or `decide.py` and shapes the result. No logic lives
here, so the dashboard, the CLI and an MCP client all see the same answers.

## Why it binds to loopback

The API can approve a recommendation, and an approved recommendation is what
authorises the action agent to write to a repository. Loopback is therefore
the default and the documented posture.

That is not sufficient on its own. A page on the public internet cannot *read*
a loopback response, but a browser will happily *send* a simple cross-origin
POST to one -- so drive-by approval is a real shape of attack against any
localhost service that changes state. Two things close it:

* Origins are allowlisted, and only the dashboard's own origins are on the
  list.
* Every state-changing request must carry `X-Alena-Dashboard`. A custom header
  forces a CORS preflight, and the preflight fails for an origin that is not
  allowlisted -- so the POST never arrives, rather than arriving and being
  rejected after the fact.

`implement` is deliberately absent. It writes to a repository, takes minutes,
and is the thing most worth watching while it happens; the dashboard shows the
command instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from modules.improve import query
from modules.improve.decide import (
    ABANDONED,
    ACCEPTED,
    RECOMMENDED,
    REJECTED,
    SUCCESSFUL,
    UNSUCCESSFUL,
    DecisionError,
    decide,
    history,
)
from modules.improve.persistence import implementations_for, recommendations_for
from modules.improve.registry import RegistryError, load_registry
from modules.improve.status import summary
from modules.improve.web.runs import COMMANDS, Busy, get_runner

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9100
# The dashboard's dev server. Set in its nuxt.config, and repeated here
# because the two have to agree -- an origin missing from this list fails the
# preflight and every request from the dashboard silently cannot read a
# response.
DASHBOARD_PORT = 3100

# The built dashboard. When it exists it is served from this app, which makes
# the whole thing one process on one port -- no node at runtime, and the
# browser is same-origin so CORS stops mattering at all. `npm run dev` on 3100
# is still the way to work on it, and that path is cross-origin, which is why
# the allowlist and the header guard remain.
BUILT_DASHBOARD = (
    Path(__file__).resolve().parents[1] / "dashboard" / ".output" / "public"
)

# The header that forces a preflight. Its value does not matter; its presence
# is what an attacker's origin cannot arrange.
GUARD_HEADER = "x-alena-dashboard"

DECISIONS = {
    "accept": ACCEPTED,
    "reject": REJECTED,
    "revisit": RECOMMENDED,
    "abandon": ABANDONED,
    "successful": SUCCESSFUL,
    "unsuccessful": UNSUCCESSFUL,
}


def allowed_origins() -> List[str]:
    configured = os.getenv("ALENA_DASHBOARD_ORIGINS", "").strip()
    if configured:
        return [o.strip() for o in configured.split(",") if o.strip()]
    # The dashboard, on both spellings of loopback: a browser treats
    # localhost and 127.0.0.1 as different origins.
    return [
        f"http://localhost:{DASHBOARD_PORT}",
        f"http://127.0.0.1:{DASHBOARD_PORT}",
        f"http://localhost:{DEFAULT_PORT}",
        f"http://{DEFAULT_HOST}:{DEFAULT_PORT}",
    ]


def require_dashboard(**kwargs) -> None:
    """Reject a state-changing request that did not come from the dashboard."""
    if not kwargs.get("x_alena_dashboard"):
        raise HTTPException(
            status_code=403,
            detail=(
                "State-changing requests must send the X-Alena-Dashboard header. "
                "This is what stops a page you did not open from approving a "
                "change on your behalf."
            ),
        )


async def guard(x_alena_dashboard: Optional[str] = Header(default=None)) -> None:
    require_dashboard(x_alena_dashboard=x_alena_dashboard)


class RunRequest(BaseModel):
    command: str = Field(..., description="A key from /api/commands")


class DecisionRequest(BaseModel):
    decision: str = Field(..., description="accept, reject, revisit, abandon, successful, unsuccessful")
    reason: Optional[str] = None
    actor: str = "human"
    actual_effort: Optional[str] = None
    observed_value: Optional[float] = None
    feedback: Optional[str] = None


def _parse_breakdown(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("score_breakdown")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _recommendation(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "repository_id": row["repository_id"],
        "title": row["title"],
        "status": row["status"],
        "score": row["score"],
        "confidence": row["confidence"],
        "estimated_effort": row["estimated_effort"],
        "reason": row["reason"],
        "body": row["body"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "breakdown": _parse_breakdown(row),
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="alena-improve",
        description="Repository intelligence, recommendations and the approval gate.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Alena-Dashboard"],
    )

    def registry():
        return load_registry()

    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        return {"ok": True}

    @app.get("/api/status")
    async def get_status() -> Dict[str, Any]:
        state = summary(registry())
        coverage = state["coverage"]
        return {
            "coverage": {
                "repositories": coverage.repositories,
                "scanned": coverage.scanned,
                "last_scan": coverage.last_scan,
                "last_scan_days": coverage.last_scan_days,
                "research_documents": coverage.research_documents,
            },
            "stages": [
                {
                    "name": s.name,
                    "label": s.label,
                    "count": s.count,
                    "oldest_days": s.oldest_days,
                    "stale": s.stale,
                    "examples": s.examples,
                }
                for s in state["stages"]
            ],
            "jobs": [
                {
                    "label": j.label,
                    "loaded": j.loaded,
                    "running": j.running,
                    "failing": j.failing,
                    "description": j.describe(),
                }
                for j in state["jobs"]
            ],
            "stranded": [
                {"repository_id": r["repository_id"], "title": r["title"]}
                for r in state["stranded"]
            ],
            "waiting_on_you": state["waiting_on_you"],
        }

    @app.get("/api/repositories")
    async def get_repositories() -> List[Dict[str, Any]]:
        return query.list_repositories(registry())

    @app.get("/api/repositories/{repository_id}")
    async def get_repository(repository_id: str) -> Dict[str, Any]:
        try:
            return query.repository_profile(repository_id, registry())
        except RegistryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @app.get("/api/repositories/{repository_id}/recommendations")
    async def get_repository_recommendations(
        repository_id: str, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        try:
            registry().resolve(repository_id)
        except RegistryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return [_recommendation(r) for r in recommendations_for(repository_id, status)]

    @app.get("/api/queue")
    async def get_queue() -> List[Dict[str, Any]]:
        """Everything awaiting a human decision, across every repository."""
        rows: List[Dict[str, Any]] = []
        for repository in registry().all():
            for row in recommendations_for(repository.id, RECOMMENDED):
                entry = _recommendation(row)
                entry["repository_name"] = repository.name
                rows.append(entry)
        return sorted(rows, key=lambda r: -(r["score"] or 0))

    @app.get("/api/recommendations/{recommendation_id}")
    async def get_recommendation(recommendation_id: int) -> Dict[str, Any]:
        for repository in registry().all():
            for row in recommendations_for(repository.id):
                if row["id"] == recommendation_id:
                    entry = _recommendation(row)
                    entry["repository_name"] = repository.name
                    entry["history"] = history(recommendation_id)
                    entry["implementations"] = implementations_for(recommendation_id)
                    return entry
        raise HTTPException(status_code=404, detail=f"No recommendation {recommendation_id}")

    @app.post("/api/recommendations/{recommendation_id}/decision", dependencies=[Depends(guard)])
    async def post_decision(
        recommendation_id: int, payload: DecisionRequest
    ) -> Dict[str, Any]:
        target = DECISIONS.get(payload.decision)
        if target is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown decision {payload.decision!r}. "
                f"Expected one of: {', '.join(sorted(DECISIONS))}",
            )

        repository_id = None
        for repository in registry().all():
            if any(r["id"] == recommendation_id for r in recommendations_for(repository.id)):
                repository_id = repository.id
                break
        if repository_id is None:
            raise HTTPException(status_code=404, detail=f"No recommendation {recommendation_id}")

        try:
            result = decide(
                repository_id,
                recommendation_id,
                target,
                reason=payload.reason,
                actor=payload.actor,
                actual_effort=payload.actual_effort,
                observed_value=payload.observed_value,
                feedback=payload.feedback,
            )
        except DecisionError as exc:
            # The state machine's refusals are the user's problem to fix, not
            # a server fault -- they say what is possible instead.
            raise HTTPException(status_code=422, detail=str(exc)) from None

        response = {
            "recommendation_id": result.recommendation_id,
            "repository_id": result.repository_id,
            "from_status": result.from_status,
            "to_status": result.to_status,
            "reason": result.reason,
        }
        if result.to_status == ACCEPTED:
            # Implementing is deliberately not something the dashboard does.
            response["next"] = (
                f"alena-improve implement {result.repository_id} "
                f"{result.recommendation_id}"
            )
        return response

    # -- running a step on request -----------------------------------------

    @app.get("/api/commands")
    async def get_commands() -> List[Dict[str, Any]]:
        """What the dashboard is allowed to start, and what each one costs."""
        return [
            {
                "key": c.key,
                "label": c.label,
                "description": c.description,
                "costs": c.costs,
            }
            for c in COMMANDS.values()
        ]

    @app.get("/api/runs")
    async def get_runs() -> Dict[str, Any]:
        runner = get_runner()
        return {
            "current": runner.current.to_dict(include_output=False)
            if runner.current
            else None,
            "runs": [r.to_dict(include_output=False) for r in runner.runs()],
        }

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> Dict[str, Any]:
        run = get_runner().get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run {run_id}")
        return run.to_dict()

    @app.post("/api/runs", dependencies=[Depends(guard)])
    async def post_run(payload: RunRequest) -> Dict[str, Any]:
        try:
            run = get_runner().start(payload.command)
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown command {payload.command!r}. "
                f"Expected one of: {', '.join(sorted(COMMANDS))}",
            ) from None
        except Busy as exc:
            # 409, not 500: nothing is broken, the caller just has to wait.
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return run.to_dict()

    @app.get("/api/portfolio")
    async def get_portfolio() -> Dict[str, Any]:
        return query.portfolio_snapshot(registry())

    @app.get("/api/tools")
    async def get_tools() -> List[Dict[str, Any]]:
        from modules.gateway.catalog import ToolCatalog, static_contracts
        from modules.gateway.metrics import tool_metrics
        from modules.gateway.policy import load_policy

        catalog = ToolCatalog(load_policy())
        catalog.register(static_contracts())
        return [m.to_dict() for m in tool_metrics(catalog)]

    _mount_dashboard(app)
    return app


def _mount_dashboard(app: FastAPI) -> None:
    """Serve the built dashboard, if it has been built.

    Missing is a normal state -- the API is useful on its own, and the built
    output is not checked in. Saying so beats a bare 404 that reads like the
    API is broken.
    """
    if not (BUILT_DASHBOARD / "index.html").exists():

        @app.get("/")
        async def not_built() -> Dict[str, Any]:
            return {
                "api": "ok",
                "dashboard": "not built",
                "build_it": "cd modules/improve/dashboard && npm install && npm run generate",
                "or_run_dev": "scripts/start_alena_dashboard.sh",
            }

        return

    app.mount(
        "/_nuxt",
        StaticFiles(directory=BUILT_DASHBOARD / "_nuxt"),
        name="assets",
    )

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """Serve a file if it exists, otherwise the SPA shell.

        A single-page app owns its own routing, so /queue is a client route
        with no file behind it.

        Anything under /api/ is excluded explicitly. Registration order alone
        is not enough: a mistyped API path matches no route and would fall
        through to here, and a client that asked for JSON should get a 404
        rather than a page of HTML with a 200 on it.
        """
        if path.startswith("api/") or path == "api":
            raise HTTPException(status_code=404, detail=f"No such endpoint: /{path}")

        candidate = (BUILT_DASHBOARD / path).resolve()
        # Resolve and confirm containment: a path like ../../.env would
        # otherwise walk out of the build directory.
        if (
            path
            and BUILT_DASHBOARD in candidate.parents
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(BUILT_DASHBOARD / "index.html")


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "modules.improve.web.api:app",
        host=os.getenv("ALENA_DASHBOARD_HOST", DEFAULT_HOST),
        port=int(os.getenv("ALENA_DASHBOARD_PORT", DEFAULT_PORT)),
        reload=False,
    )
