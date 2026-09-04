"""Reusable MCP stdio sessions.

The original executor opened `stdio_client` inside the call itself, so every
tool call spawned a Python process and redid the MCP handshake. One or two
calls per chat turn hid the cost; an orchestrator scanning a portfolio makes
dozens per run.

Each server gets one long-lived *owner task* that holds the session open and
services calls from a queue. The owner task exists because anyio cancel scopes
belong to the task that entered them: a session entered in one task and closed
from another raises "attempted to exit cancel scope in a different task".
Funnelling every call through the owner keeps enter, use, and exit in one
place.

Sessions are also bound to the event loop that created them. `alena.py` calls
`asyncio.run()` per line of input, so the CLI gets a fresh loop every turn and
its sessions are discarded each time -- correct, just not a saving. The
controller and the orchestrator run one loop and do benefit.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from modules.core.controller.logger import logger

T = TypeVar("T")

_SHUTDOWN = object()


def server_key(server: Any) -> str:
    """A stable identity for a server config, used as the pool key."""
    command = getattr(server, "command", "?")
    args = getattr(server, "args", []) or []
    cwd = getattr(server, "cwd", "") or ""
    return f"{command} {' '.join(str(a) for a in args)} @ {cwd}"


class _ServerWorker:
    """Owns one MCP session and runs work against it inside its own task."""

    def __init__(self, server: Any, key: str):
        self._server = server
        self._key = key
        self._queue: asyncio.Queue = asyncio.Queue()
        self._ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self._task: Optional[asyncio.Task] = None
        self._failure: Optional[BaseException] = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"mcp-session:{self._key}")
        await self._ready

    async def _run(self) -> None:
        try:
            async with stdio_client(self._server) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if not self._ready.done():
                        self._ready.set_result(None)
                    await self._serve(session)
        except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
            self._failure = exc
            if not self._ready.done():
                self._ready.set_exception(exc)
            else:
                logger.warning(f"MCP session {self._key} ended: {exc!r}")
            self._drain(exc)
            if isinstance(exc, asyncio.CancelledError):
                raise

    async def _serve(self, session: ClientSession) -> None:
        while True:
            item = await self._queue.get()
            if item is _SHUTDOWN:
                return
            fn, future = item
            if future.cancelled():
                continue
            try:
                future.set_result(await fn(session))
            except Exception as exc:  # per-call failure; the session survives
                future.set_exception(exc)

    def _drain(self, exc: BaseException) -> None:
        """Fail everything still queued once the session is gone."""
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if item is _SHUTDOWN:
                continue
            _, future = item
            if not future.done():
                future.set_exception(exc)

    async def submit(self, fn: Callable[[ClientSession], Awaitable[T]]) -> T:
        if self._failure is not None:
            raise RuntimeError(f"MCP session {self._key} is closed") from self._failure
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._queue.put_nowait((fn, future))
        return await future

    async def aclose(self) -> None:
        if self._task is None or self._task.done():
            return
        self._queue.put_nowait(_SHUTDOWN)
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"MCP session {self._key} failed to close: {exc!r}")


class MCPSessionPool:
    """One live session per server, for as long as the event loop lives."""

    def __init__(self) -> None:
        self._workers: Dict[str, _ServerWorker] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock: Optional[asyncio.Lock] = None

    def _check_loop(self) -> None:
        """Discard sessions belonging to a previous event loop.

        They cannot be awaited or closed from here -- their transports died
        with their loop -- so they are dropped rather than cleaned up.
        """
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        if self._loop is not None and self._workers:
            logger.debug(
                f"Discarding {len(self._workers)} MCP session(s) from a closed loop"
            )
        self._workers = {}
        self._loop = loop
        self._lock = asyncio.Lock()

    async def _worker(self, server: Any) -> _ServerWorker:
        self._check_loop()
        key = server_key(server)
        assert self._lock is not None
        async with self._lock:
            worker = self._workers.get(key)
            if worker is not None and worker._failure is None:
                return worker
            worker = _ServerWorker(server, key)
            await worker.start()
            self._workers[key] = worker
            return worker

    async def run(
        self, server: Any, fn: Callable[[ClientSession], Awaitable[T]]
    ) -> T:
        """Run `fn` against a live session for `server`."""
        worker = await self._worker(server)
        return await worker.submit(fn)

    async def call_tool(self, server: Any, tool: str, arguments: dict) -> Any:
        return await self.run(server, lambda s: s.call_tool(tool, arguments))

    async def list_tools(self, server: Any) -> Any:
        return await self.run(server, lambda s: s.list_tools())

    async def aclose(self) -> None:
        workers, self._workers = self._workers, {}
        for worker in workers.values():
            await worker.aclose()


_pool: Optional[MCPSessionPool] = None


def get_pool() -> MCPSessionPool:
    global _pool
    if _pool is None:
        _pool = MCPSessionPool()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
