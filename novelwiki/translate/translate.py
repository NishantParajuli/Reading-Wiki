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
import logging
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.agent.llm_client import call_chat_completion
from novelwiki.translate.prompts import TRANSLATE_SYSTEM, TRANSLATE_USER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Per-(novel, chapter) locks so an on-demand request and a prefetch task never
# translate the same chapter twice (single-process uvicorn).
_locks: dict[tuple[int, float], asyncio.Lock] = {}


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


async def translate_chapter(novel_id: int, number: float, force: bool = False,
                            meter_user: dict | None = None) -> dict:
    """Translate one raw chapter into chapters.content. Idempotent: returns the
    existing translation unless force=True. If meter_user is given, quota is reserved
    only after the chapter is confirmed still untranslated under the per-chapter lock.
    Returns {status, content, new_terms}."""
    charged_user_id = None
    async with _lock_for(novel_id, number):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            ch = await conn.fetchrow(
                """
                SELECT title, original_text, content, translation_status, language
                FROM chapters WHERE novel_id = $1 AND number = $2;
                """,
                novel_id, number,
            )
            if not ch:
                return {"status": "missing", "content": None}
            # Already translated (or a normal English chapter): nothing to do.
            if ch["content"] and not force:
                return {"status": "done", "content": ch["content"]}
            if not ch["original_text"]:
                return {"status": ch["translation_status"] or "none", "content": ch["content"]}
            if meter_user is not None:
                from novelwiki import quota
                if not await quota.try_reserve(meter_user, "translated_chapters", 1):
                    return {"status": "quota_exceeded", "content": ch["content"]}
                charged_user_id = int(meter_user["id"])
            language = ch["language"] or "the source language"
            confirmed_g, established_g = _format_glossary(await _load_glossary(novel_id, conn))
            await conn.execute(
                "UPDATE chapters SET translation_status = 'translating' WHERE novel_id = $1 AND number = $2;",
                novel_id, number,
            )

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
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE chapters SET translation_status = 'failed' WHERE novel_id = $1 AND number = $2;",
                    novel_id, number,
                )
            if charged_user_id is not None:
                from novelwiki import quota
                refunded = await quota.refund(charged_user_id, "translated_chapters", 1)
                if refunded:
                    logger.info(
                        "Refunded translated_chapters quota for failed translation "
                        f"(user {charged_user_id}, novel {novel_id} ch {number})."
                    )
            return {"status": "failed", "content": None}

        word_count = len(translation.split())
        async with pool.acquire() as conn:
            async with conn.transaction():
                if title_translated:
                    await conn.execute(
                        """
                        UPDATE chapters
                        SET title = $1, content = $2, is_translated = TRUE, translation_status = 'done',
                            translation_model = $3, word_count = $4, content_version = content_version + 1
                        WHERE novel_id = $5 AND number = $6;
                        """,
                        title_translated, translation, settings.MODEL_TRANSLATE, word_count, novel_id, number,
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE chapters
                        SET content = $1, is_translated = TRUE, translation_status = 'done',
                            translation_model = $2, word_count = $3, content_version = content_version + 1
                        WHERE novel_id = $4 AND number = $5;
                        """,
                        translation, settings.MODEL_TRANSLATE, word_count, novel_id, number,
                    )
                # A re-translation of the shared base supersedes per-user overlays forked from
                # an older version — flag them so the reader shows a conflict badge (Phase 5).
                await conn.execute(
                    """
                    UPDATE chapter_overlays SET conflict = TRUE, updated_at = now()
                    WHERE novel_id = $1 AND chapter = $2
                      AND base_version < (SELECT content_version FROM chapters WHERE novel_id = $1 AND number = $2);
                    """,
                    novel_id, number,
                )
                await _upsert_terms(novel_id, new_terms, conn)
        logger.info(f"Translated novel {novel_id} ch {number} ({word_count} words, +{len(new_terms)} glossary terms).")
        return {"status": "done", "content": translation, "new_terms": len(new_terms)}


async def translate_raw_text(novel_id: int, number: float) -> str | None:
    """Translate a raw chapter's original_text and RETURN the text without touching the
    shared base. Used by per-user self-translation overlays (Phase 5): the result is stored
    in chapter_overlays, never in chapters.content. Returns None if there's nothing to translate."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        ch = await conn.fetchrow(
            "SELECT title, original_text, language FROM chapters WHERE novel_id = $1 AND number = $2;",
            novel_id, number,
        )
        if not ch or not ch["original_text"]:
            return None
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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT number FROM chapters
            WHERE novel_id = $1 AND number > $2
              AND content IS NULL AND original_text IS NOT NULL
              AND translation_status IN ('none', 'pending', 'failed')
            ORDER BY number ASC LIMIT $3;
            """,
            novel_id, after_number, count,
        )
    return [float(r["number"]) for r in rows]


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
    pool = await get_db_pool()
    conds = ["novel_id = $1", "original_text IS NOT NULL"]
    args: list = [novel_id]
    if not force:
        conds.append("content IS NULL")
    if from_chapter is not None:
        args.append(from_chapter); conds.append(f"number >= ${len(args)}")
    if to_chapter is not None:
        args.append(to_chapter); conds.append(f"number <= ${len(args)}")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT number FROM chapters WHERE {' AND '.join(conds)} ORDER BY number ASC;", *args
        )
    done = 0
    for r in rows:
        res = await translate_chapter(novel_id, float(r["number"]), force=force, meter_user=meter_user)
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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT canonical_name, type FROM entities
            WHERE novel_id = $1 AND type IN ('character', 'location', 'faction', 'organization', 'item')
            ORDER BY first_seen_chapter ASC;
            """,
            novel_id,
        )
        n = 0
        for r in rows:
            name = (r["canonical_name"] or "").strip()
            if not name:
                continue
            ttype = {"character": "name", "location": "place", "faction": "name",
                     "organization": "name", "item": "item"}.get(r["type"], "term")
            res = await conn.execute(
                """
                INSERT INTO translation_glossary (novel_id, source_term, translation, term_type, notes)
                VALUES ($1, $2, $2, $3, 'seeded from codex')
                ON CONFLICT (novel_id, source_term) DO NOTHING;
                """,
                novel_id, name, ttype,
            )
            if res.endswith("1"):
                n += 1
    logger.info(f"Seeded {n} glossary terms from codex entities for novel {novel_id}.")
    return n
