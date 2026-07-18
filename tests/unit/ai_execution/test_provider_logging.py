from __future__ import annotations

from types import SimpleNamespace

import pytest

from novelwiki.modules.ai_execution.adapters.outbound import providers


def test_native_deepseek_client_uses_configured_key_and_base_url(monkeypatch):
    constructor_calls = []

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            constructor_calls.append(kwargs)

    monkeypatch.setattr(providers.settings, "DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setattr(
        providers.settings, "DEEPSEEK_BASE_URL", "https://deepseek.test"
    )
    monkeypatch.setattr(providers, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(providers, "_deepseek_client", None)

    client = providers.get_deepseek_client()

    assert isinstance(client, FakeAsyncOpenAI)
    assert constructor_calls == [
        {
            "api_key": "sk-deepseek-test",
            "base_url": "https://deepseek.test",
        }
    ]


@pytest.mark.asyncio
async def test_chat_provider_logs_sizes_usage_retries_and_no_payload(monkeypatch):
    calls = 0
    events = []

    async def create(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary provider failure")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="safe result"))],
            usage=SimpleNamespace(
                prompt_tokens=21, completion_tokens=3, total_tokens=24,
            ),
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    async def no_sleep(_seconds):
        return None

    def capture(_logger, level, event, message, **fields):
        events.append({"level": level, "event": event, "message": message, **fields})

    monkeypatch.setattr(providers.settings, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(providers, "_openrouter_client", fake_client)
    monkeypatch.setattr(providers, "log_event", capture)
    monkeypatch.setattr(providers.asyncio, "sleep", no_sleep)

    secret_payload = "chapter text that must never enter a log field"
    result = await providers.call_chat_completion(
        "model/test", [{"role": "user", "content": secret_payload}]
    )

    assert result == "safe result"
    started = next(item for item in events if item["event"] == "ai.provider_call_started")
    failed = next(item for item in events if item["event"] == "ai.provider_call_failed")
    completed = next(item for item in events if item["event"] == "ai.provider_call_completed")
    assert started["model"] == "model/test"
    assert started["provider"] == "openrouter"
    assert started["messages"] == 1
    assert started["input_chars"] >= len(secret_payload)
    assert failed["attempt"] == 1 and failed["retry_scheduled"] is True
    assert completed["attempt"] == 2
    assert completed["input_tokens"] == 21
    assert completed["output_tokens"] == 3
    assert completed["total_tokens"] == 24
    assert completed["output_chars"] == len("safe result")
    assert secret_payload not in str(events)
    assert "safe result" not in str(events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured_model", "native_model"),
    [
        ("deepseek/deepseek-v4-flash", "deepseek-v4-flash"),
        ("deepseek/deepseek-v4-pro", "deepseek-v4-pro"),
    ],
)
async def test_native_deepseek_key_routes_v4_chat_and_normalizes_model(
    monkeypatch, configured_model, native_model
):
    calls = []
    events = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="native result"))],
            usage=None,
        )

    native_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    def capture(_logger, level, event, message, **fields):
        events.append({"level": level, "event": event, "message": message, **fields})

    monkeypatch.setattr(providers.settings, "DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setattr(providers, "_deepseek_client", native_client)
    monkeypatch.setattr(providers, "log_event", capture)

    result = await providers.call_chat_completion(
        configured_model,
        [{"role": "user", "content": "hello"}],
        reasoning="max",
    )

    assert result == "native result"
    assert calls[0]["model"] == native_model
    assert calls[0]["reasoning_effort"] == "max"
    started = next(item for item in events if item["event"] == "ai.provider_call_started")
    assert started["provider"] == "deepseek"
    assert started["model"] == native_model
    assert started["configured_model"] == configured_model


@pytest.mark.asyncio
async def test_deepseek_key_keeps_non_deepseek_chat_on_openrouter(monkeypatch):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback result"))],
            usage=None,
        )

    openrouter_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(providers.settings, "DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setattr(providers, "_openrouter_client", openrouter_client)

    result = await providers.call_chat_completion(
        "anthropic/claude-test", [{"role": "user", "content": "hello"}]
    )

    assert result == "fallback result"
    assert calls[0]["model"] == "anthropic/claude-test"


@pytest.mark.asyncio
async def test_native_deepseek_model_id_is_normalized_for_openrouter_fallback(monkeypatch):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback result"))],
            usage=None,
        )

    openrouter_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(providers.settings, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(providers, "_openrouter_client", openrouter_client)

    result = await providers.call_chat_completion(
        "deepseek-v4-flash", [{"role": "user", "content": "hello"}]
    )

    assert result == "fallback result"
    assert calls[0]["model"] == "deepseek/deepseek-v4-flash"


@pytest.mark.asyncio
async def test_deepseek_key_keeps_embeddings_on_openrouter(monkeypatch):
    embedding_calls = []

    async def create(**kwargs):
        embedding_calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[3.0, 4.0])],
            usage=None,
        )

    openrouter_client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    monkeypatch.setattr(providers.settings, "DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setattr(providers.settings, "EMBED_DIM", 2)
    monkeypatch.setattr(providers.settings, "EMBED_MODEL", "embedding/test")
    monkeypatch.setattr(providers, "_openrouter_client", openrouter_client)

    result = await providers.get_embedding("hello")

    assert result == pytest.approx([0.6, 0.8])
    assert embedding_calls == [{"model": "embedding/test", "input": "hello"}]


@pytest.mark.asyncio
async def test_deepseek_key_keeps_rerank_on_openrouter(monkeypatch):
    requests = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "index": 0,
                        "relevance_score": 0.9,
                        "document": {"text": "first"},
                    }
                ]
            }

    class FakeHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, headers, json):
            requests.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(providers.settings, "DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setattr(providers.settings, "OPENROUTER_API_KEY", "sk-openrouter-test")
    monkeypatch.setattr(
        providers.settings, "OPENROUTER_BASE_URL", "https://openrouter.test/v1"
    )
    monkeypatch.setattr(
        providers.httpx, "AsyncClient", lambda **_kwargs: FakeHttpClient()
    )

    result = await providers.rerank_passages("query", ["first"], top_n=1)

    assert result == [{"index": 0, "score": 0.9, "text": "first"}]
    assert requests[0]["url"] == "https://openrouter.test/v1/rerank"
    assert requests[0]["headers"]["Authorization"] == "Bearer sk-openrouter-test"
