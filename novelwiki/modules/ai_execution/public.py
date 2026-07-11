from typing import Protocol


class ChatGateway(Protocol):
    async def complete(self, *, messages: list[dict], model: str, **options) -> object: ...


class EmbeddingGateway(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class RerankGateway(Protocol):
    async def rerank(self, query: str, documents: list[str], top_n: int) -> object: ...


class VisionGateway(Protocol):
    async def inspect(self, images: list[bytes], prompt: str) -> object: ...


async def capability_for_user(user_id: int) -> dict:
    """Compatibility owner API; Bootstrap replaces this with an injected port later."""
    from .adapters.outbound.policy import capability_for_user as implementation

    return await implementation(user_id)


# Provider and dedicated-run primitives are owner APIs used by composition bridges.
from .adapters.outbound.providers import (  # noqa: E402
    BudgetExhausted,
    call_chat_completion,
    call_llm,
    call_vision_completion,
    get_embedding,
    get_embeddings_batch,
    rerank_passages,
)
from .adapters.outbound.agy.contracts import (  # noqa: E402
    DisambiguationPayload,
    ExtractionPayload,
    InputManifest,
    TranslationMeta,
)
from .adapters.outbound.agy.errors import (  # noqa: E402
    AgyCanceled,
    AgyError,
    AgyValidationError,
    PROVIDER_WAIT_CODES,
    is_database_error,
    safe_error_summary,
)
from .adapters.outbound.agy.preflight import PreflightResult, run_preflight  # noqa: E402
from .adapters.outbound.agy.runner import (  # noqa: E402
    process_identity_matches,
    run_agy,
    terminate_process_group,
)
from .adapters.outbound.agy.runs import create_run, update_run, workspace_relpath  # noqa: E402
from .adapters.outbound.agy.validators import (  # noqa: E402
    load_json,
    read_text_artifact,
    validate_output_manifest,
)
from .adapters.outbound.agy.workspace import (  # noqa: E402
    add_input,
    cleanup_expired_workspaces,
    create_run_workspace,
    seal_inputs,
    sha256_file,
    validate_work_root,
    write_json,
)
from .adapters.outbound.agy import PLUGIN_SOURCE  # noqa: E402
from .adapters.outbound.policy import (  # noqa: E402
    delete_policy,
    get_policy,
    model_for,
    reauthorize_job,
    resolve_backend,
    upsert_policy,
    worker_available,
)
from .adapters.outbound.limits import (  # noqa: E402
    concurrency_slot,
    consume_ask_rate,
    require_ask_spend_allowed,
)
from .domain.backend import ExecutionBackend, RequestedBackend, Workload  # noqa: E402
