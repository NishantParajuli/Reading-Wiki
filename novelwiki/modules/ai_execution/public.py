from typing import Protocol


class ChatGateway(Protocol):
    async def complete(self, *, messages: list[dict], model: str, **options) -> object: ...


class EmbeddingGateway(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class RerankGateway(Protocol):
    async def rerank(self, query: str, documents: list[str], top_n: int) -> object: ...


class VisionGateway(Protocol):
    async def inspect(self, images: list[bytes], prompt: str) -> object: ...
