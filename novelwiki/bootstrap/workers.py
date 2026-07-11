"""Explicit worker-handler registry assembled outside feature modules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

WorkerHandler = Callable[..., Awaitable[object]]


class WorkerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, WorkerHandler] = {}

    def register(self, workload: str, handler: WorkerHandler) -> None:
        if workload in self._handlers:
            raise ValueError(f"Worker handler already registered for {workload!r}")
        self._handlers[workload] = handler

    def resolve(self, workload: str) -> WorkerHandler:
        try:
            return self._handlers[workload]
        except KeyError as exc:
            raise LookupError(f"No worker handler registered for {workload!r}") from exc

    @property
    def workloads(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))
