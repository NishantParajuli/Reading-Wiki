"""asyncpg implementation of the opaque kernel unit-of-work contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any, TypeVar

T = TypeVar("T")


class TransactionBindings:
    """Creates public capabilities bound internally to one connection."""

    def __init__(self, connection: Any, factories: Mapping[type[Any], Callable[[Any], Any]]):
        self.__connection = connection
        self.__factories = dict(factories)
        self.__instances: dict[type[Any], Any] = {}

    def bind(self, capability: type[T]) -> T:
        if capability not in self.__instances:
            try:
                factory = self.__factories[capability]
            except KeyError as exc:
                raise LookupError(f"No transaction binding registered for {capability!r}") from exc
            self.__instances[capability] = factory(self.__connection)
        return self.__instances[capability]


class AsyncpgUnitOfWork:
    """One acquired connection and one explicit transaction per application operation."""

    def __init__(self, pool: Any, factories: Mapping[type[Any], Callable[[Any], Any]] | None = None):
        self._pool = pool
        self._factories = factories or {}
        self._acquire_cm = None
        self._transaction_cm = None
        self.transaction: TransactionBindings

    async def __aenter__(self) -> "AsyncpgUnitOfWork":
        self._acquire_cm = self._pool.acquire()
        connection = await self._acquire_cm.__aenter__()
        self._transaction_cm = connection.transaction()
        await self._transaction_cm.__aenter__()
        self.transaction = TransactionBindings(connection, self._factories)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        assert self._transaction_cm is not None and self._acquire_cm is not None
        try:
            result = await self._transaction_cm.__aexit__(exc_type, exc, traceback)
        finally:
            await self._acquire_cm.__aexit__(exc_type, exc, traceback)
        return result
