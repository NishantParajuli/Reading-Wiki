from __future__ import annotations

import pytest
from pydantic import ValidationError

from novelwiki.platform.config.settings import Settings


def test_openai_codex_defaults_use_required_reasoning_policy():
    configured = Settings(_env_file=None)

    assert configured.OPENAI_CODEX_MODEL_TRANSLATE == "gpt-5.6-terra"
    assert configured.OPENAI_CODEX_REASONING_TRANSLATE == "xhigh"
    assert configured.OPENAI_CODEX_MODEL_CODEX == "gpt-5.6-luna"
    assert configured.OPENAI_CODEX_REASONING_CODEX == "xhigh"
    assert configured.CODEX_CONTEXT_MAX_TOKENS == 48_000
    assert configured.CODEX_VERIFY_CONTEXT_MAX_TOKENS == 64_000


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "OPENAI_CODEX_MODEL_CODEX": "gpt-5.6-luna",
                "OPENAI_CODEX_REASONING_CODEX": "medium",
            },
            "OPENAI_CODEX_REASONING_CODEX must be 'xhigh'",
        ),
        (
            {
                "OPENAI_CODEX_MODEL_TRANSLATE": "gpt-5.6-terra",
                "OPENAI_CODEX_REASONING_TRANSLATE": "medium",
            },
            "OPENAI_CODEX_REASONING_TRANSLATE must be 'xhigh'",
        ),
    ],
)
def test_openai_codex_rejects_weakened_luna_or_terra_effort(overrides, message):
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **overrides)


def test_verifier_context_cap_cannot_be_smaller_than_primary_cap():
    with pytest.raises(ValidationError, match="CODEX_VERIFY_CONTEXT_MAX_TOKENS"):
        Settings(
            _env_file=None,
            CODEX_CONTEXT_MAX_TOKENS=48_000,
            CODEX_VERIFY_CONTEXT_MAX_TOKENS=47_999,
        )
