from __future__ import annotations

from types import SimpleNamespace

import pytest

from novelwiki.modules.ai_execution.adapters.outbound import providers


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

    monkeypatch.setattr(providers, "_openai_client", fake_client)
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
