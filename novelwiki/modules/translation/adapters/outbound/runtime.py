"""On-demand chapter translation with a per-novel name/term glossary.

Flow (per the platform plan, "on-demand + prefetch"):
  - The reader requests a raw chapter -> translate_chapter() runs inline and returns
    the English text, then the API schedules prefetch_translations() for the next few.
  - Every translation is fed the novel's accumulated glossary so recurring names/terms
    stay spelled the same across chapters AND across a source switch (the glossary is
    seeded from the prior English chapters / codex entities — see seed_glossary_*).
  - Newly-seen proper nouns the model reports are folded back into the glossary
    (never overwriting locked or already-established terms), so consistency compounds.
"""
import json
import asyncio
import hashlib
import logging
import uuid
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.agent.llm_client import call_chat_completion
from novelwiki.translate.prompts import TRANSLATE_SYSTEM, TRANSLATE_USER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Per-(novel, chapter) locks so an on-demand request and a prefetch task never
# translate the same chapter twice (single-process uvicorn).
_locks: dict[tuple[int, float], asyncio.Lock] = {}


async def _translation_runtime():
    from novelwiki.bootstrap.translation import build_translation_runtime
    return await build_translation_runtime()


def _lock_for(novel_id: int, number: float) -> asyncio.Lock:
    key = (novel_id, float(number))
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


async def _load_glossary(novel_id: int, conn) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT source_term, translation, term_type
        FROM translation_glossary WHERE novel_id = $1
        ORDER BY locked DESC, id ASC;
        """,
        novel_id,
    )
    return [dict(r) for r in rows]


# Cap on how many established English spellings to inject (token budget guard). The
# glossary is ordered locked-first then oldest-first, so the most central names survive.
_ESTABLISHED_CAP = 120


def _format_glossary(rows: list[dict]) -> tuple[str, str]:
    """Split the glossary into (confirmed_mappings, established_spellings).

    A row is a *confirmed mapping* when its source_term is the real source-language form
    (source_term != translation) — the translator must reproduce its English exactly.
    A row is an *established spelling* when only the canonical English is known
    (source_term == translation, e.g. seeded from the codex over the prior English
    chapters) — the translator should use that spelling for the name and report the
    foreign term it actually saw so the mapping gets learned across the source switch.
    """
    confirmed, established = [], []
    for r in rows:
        src = (r.get("source_term") or "").strip()
        tr = (r.get("translation") or "").strip()
        if not tr:
            continue
        t = f" [{r['term_type']}]" if r.get("term_type") else ""
        if src and src != tr:
            confirmed.append(f"- {src} → {tr}{t}")
        else:
            established.append(f"- {tr}{t}")
    confirmed_str = "\n".join(confirmed) if confirmed else "(none yet — establish names as you go)"
    established_str = "\n".join(established[:_ESTABLISHED_CAP]) if established else "(none)"
    return confirmed_str, established_str


def _parse_translation(raw: str) -> tuple[str, str, list[dict]]:
    """Split the delimiter-framed response into (translated_title, translation_text, new_terms).
    Tolerant of a missing/garbled TERMS block — that just yields no new terms."""
    text = raw or ""
    title = ""
    if "===TITLE===" in text:
        parts = text.split("===TITLE===", 1)[1].split("===TRANSLATION===", 1)
        title = parts[0].strip()
        text = parts[1] if len(parts) > 1 else ""
    elif "===TRANSLATION===" in text:
        text = text.split("===TRANSLATION===", 1)[1]

    translation, terms_raw = text, ""
    if "===TERMS===" in text:
        translation, terms_raw = text.split("===TERMS===", 1)
    translation = translation.strip()

    terms: list = []
    tr = terms_raw.strip().replace("```json", "").replace("```", "").strip()
    if tr:
        try:
            terms = json.loads(tr)
        except Exception:
            try:
                import json_repair
                terms = json_repair.loads(tr)
            except Exception:
                terms = []
    if not isinstance(terms, list):
        terms = []
    clean = []
    for t in terms:
        if isinstance(t, dict) and t.get("source_term") and t.get("translation"):
            clean.append(t)
    return title, translation, clean


async def _upsert_terms(novel_id: int, terms: list[dict], conn):
    """Fold newly-seen terms into the glossary. Never overwrite an existing row
    (locked or not) — the FIRST established spelling wins, which is what keeps
    names stable across the whole novel."""
    for t in terms:
        await conn.execute(
            """
            INSERT INTO translation_glossary (novel_id, source_term, translation, term_type)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (novel_id, source_term) DO NOTHING;
            """,
            novel_id, t["source_term"].strip(), t["translation"].strip(),
            (t.get("term_type") or None),
        )


class SourceChangedError(RuntimeError):
    """The chapter no longer matches the immutable provider input snapshot."""


def source_sha256(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


async def stage_translation_batch(
    novel_id: int,
    chapter_numbers: list[float],
    run_id: uuid.UUID,
    *,
    force: bool = False,
) -> list[dict]:
    """Lock, snapshot, and mark an AGY batch before any subscription work.

    ``translation_run_id`` makes reset/commit ownership cross-process safe. A
    reader request now sees ``translating`` and will not launch an API call for a
    chapter already staged by the host worker.
    """
    reading, _uow_factory = await _translation_runtime()
    return await reading.stage_translation_batch(
        novel_id, chapter_numbers, run_id, force
    )


async def reset_staged_translations(run_id: uuid.UUID, *, status: str = "failed") -> int:
    if status not in ("failed", "pending", "none"):
        raise ValueError("invalid translation reset status")
    reading, _uow_factory = await _translation_runtime()
    return await reading.reset_staged_translations(run_id, status)


async def commit_translation(
    novel_id: int,
    chapter_number: float,
    *,
    expected_source_hash: str,
    expected_content_version: int,
    translated_title: str | None,
    translation: str,
    new_terms: list[dict],
    model_label: str,
    run_id: uuid.UUID | None = None,
    job_id: int | None = None,
) -> dict:
    """Backend-neutral, row-locked translation commit.

    The source/version/run checks and content write share one transaction, so a
    web API translator and host AGY worker cannot overwrite one another. When an
    AGY job id is supplied, reserved quota consumption commits atomically with
    the chapter.
    """
    if not translation or not translation.strip():
        raise ValueError("translation must not be empty")
    from novelwiki.workflows.commit_translation import commit_translation as workflow

    _reading, uow_factory = await _translation_runtime()
    try:
        return await workflow(
            uow_factory, novel_id, chapter_number,
            expected_source_hash=expected_source_hash,
            expected_content_version=expected_content_version,
            translated_title=translated_title, translation=translation,
            new_terms=new_terms, model_label=model_label, run_id=run_id,
            job_id=job_id,
        )
    except RuntimeError as exc:
        if str(exc).startswith("chapter "):
            raise SourceChangedError(str(exc)) from exc
        raise


async def translate_chapter(novel_id: int, number: float, force: bool = False,
                            meter_user: dict | None = None) -> dict:
    """Translate one raw chapter into chapters.content. Idempotent: returns the
    existing translation unless force=True. If meter_user is given, quota is reserved
    only after the chapter is confirmed still untranslated under the per-chapter lock.
    Returns {status, content, new_terms}."""
    charged_user_id = None
    async with _lock_for(novel_id, number):
        reading, _uow_factory = await _translation_runtime()
        ch = await reading.translation_candidate(novel_id, number)
        if not ch:
            return {"status": "missing", "content": None}
        if ch["content"] and not force:
            return {"status": "done", "content": ch["content"]}
        if not ch["original_text"]:
            return {"status": ch["translation_status"] or "none", "content": ch["content"]}
        if ch["translation_status"] == "translating" or ch["translation_run_id"] is not None:
            return {"status": "translating", "content": ch["content"]}
        if meter_user is not None:
            from novelwiki import quota
            if not await quota.try_reserve(meter_user, "translated_chapters", 1):
                return {"status": "quota_exceeded", "content": ch["content"]}
            charged_user_id = int(meter_user["id"])
        language = ch["language"] or "the source language"
        expected_hash = source_sha256(ch["original_text"])
        expected_version = int(ch["content_version"] or 1)
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            confirmed_g, established_g = _format_glossary(await _load_glossary(novel_id, conn))
        await reading.mark_translation_started(novel_id, number, expected_hash)

        title = f": {ch['title']}" if ch["title"] else ""
        text = ch["original_text"][: settings.TRANSLATE_MAX_INPUT_CHARS]
        messages = [
            {"role": "system", "content": TRANSLATE_SYSTEM.format(language=language)},
            {"role": "user", "content": TRANSLATE_USER.format(
                language=language, confirmed=confirmed_g, established=established_g,
                number=number, title=title, text=text)},
        ]

        try:
            raw = await call_chat_completion(model=settings.MODEL_TRANSLATE, messages=messages, temperature=0.2)
            title_translated, translation, new_terms = _parse_translation(raw)
            if not translation:
                raise ValueError("empty translation returned")
        except Exception as e:
            logger.error(f"Translation failed for novel {novel_id} ch {number}: {e}")
            await reading.mark_translation_failed(novel_id, number)
            if charged_user_id is not None:
                from novelwiki import quota
                refunded = await quota.refund(charged_user_id, "translated_chapters", 1)
                if refunded:
                    logger.info(
                        "Refunded translated_chapters quota for failed translation "
                        f"(user {charged_user_id}, novel {novel_id} ch {number})."
                    )
            return {"status": "failed", "content": None}
        try:
            result = await commit_translation(
                novel_id, number,
                expected_source_hash=expected_hash,
                expected_content_version=expected_version,
                translated_title=title_translated,
                translation=translation,
                new_terms=new_terms,
                model_label=settings.MODEL_TRANSLATE,
            )
        except Exception as e:
            logger.warning(f"Translation commit lost race for novel {novel_id} ch {number}: {e}")
            await reading.mark_translation_failed(novel_id, number, only_unowned=True)
            if charged_user_id is not None:
                from novelwiki import quota
                await quota.refund(charged_user_id, "translated_chapters", 1)
            return {"status": "failed", "content": None}
        logger.info(f"Translated novel {novel_id} ch {number} ({len(translation.split())} words, +{len(new_terms)} glossary terms).")
        return result


async def translate_raw_text(novel_id: int, number: float) -> str | None:
    """Translate a raw chapter's original_text and RETURN the text without touching the
    shared base. Used by per-user self-translation overlays (Phase 5): the result is stored
    in chapter_overlays, never in chapters.content. Returns None if there's nothing to translate."""
    reading, _uow_factory = await _translation_runtime()
    ch = await reading.translation_candidate(novel_id, number)
    if not ch or not ch["original_text"]:
        return None
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        confirmed_g, established_g = _format_glossary(await _load_glossary(novel_id, conn))

    language = ch["language"] or "the source language"
    title = f": {ch['title']}" if ch["title"] else ""
    text = ch["original_text"][: settings.TRANSLATE_MAX_INPUT_CHARS]
    messages = [
        {"role": "system", "content": TRANSLATE_SYSTEM.format(language=language)},
        {"role": "user", "content": TRANSLATE_USER.format(
            language=language, confirmed=confirmed_g, established=established_g,
            number=number, title=title, text=text)},
    ]
    raw = await call_chat_completion(model=settings.MODEL_TRANSLATE, messages=messages, temperature=0.2)
    _title, translation, _terms = _parse_translation(raw)
    return translation or None


async def _pending_after(novel_id: int, after_number: float, count: int) -> list[float]:
    reading, _uow_factory = await _translation_runtime()
    return await reading.pending_after(novel_id, after_number, count)


async def prefetch_translations(novel_id: int, after_number: float, count: int | None = None,
                                meter_user: dict | None = None):
    """Background task: translate the next few pending raw chapters so the reader
    rarely waits at a chapter boundary. When `meter_user` is given, each prefetched
    chapter is charged to that user's monthly quota and prefetch stops once they're out."""
    count = count if count is not None else settings.TRANSLATE_PREFETCH
    if count <= 0:
        return
    for num in await _pending_after(novel_id, after_number, count):
        try:
            res = await translate_chapter(novel_id, num, meter_user=meter_user)
            if res.get("status") == "quota_exceeded":
                break
        except Exception as e:
            logger.warning(f"Prefetch translation failed for novel {novel_id} ch {num}: {e}")


async def translate_range(novel_id: int, from_chapter: float | None = None,
                          to_chapter: float | None = None, force: bool = False,
                          meter_user: dict | None = None) -> int:
    """Translate all (pending, unless force) raw chapters in a range. Used by the
    manual 'Translate' action / CLI; reading itself uses on-demand + prefetch."""
    reading, _uow_factory = await _translation_runtime()
    rows = await reading.translation_range(
        novel_id, from_chapter, to_chapter, force
    )
    done = 0
    for number in rows:
        res = await translate_chapter(novel_id, number, force=force, meter_user=meter_user)
        if res.get("status") == "quota_exceeded":
            break
        if res.get("status") == "done":
            done += 1
    return done


async def seed_glossary_from_entities(novel_id: int) -> int:
    """Cross-source name consistency: seed the glossary's English side from the codex
    entities already established over the novel's English chapters. The source_term is
    left equal to the canonical name (the model fills the real foreign term as it meets
    it); the point is to hand the translator the established English spellings so a raw
    continuation keeps "Lin Xuan" rather than inventing "Lin Xenon"."""
    from novelwiki.bootstrap.translation import seed_system_glossary
    n = await seed_system_glossary(novel_id)
    logger.info(f"Seeded {n} glossary terms from codex entities for novel {novel_id}.")
    return n

