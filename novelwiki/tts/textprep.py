"""Text normalization for TTS.

OmniVoice narrates raw text better when numerals are spelled out, and it treats square
brackets ``[...]`` as control symbols (CMU pronunciations / non-verbal tags), so footnote
markers like ``[12]`` in prose must be removed or they get misread. This module turns a
chapter's clean prose (``chapters.content`` — paragraphs separated by blank lines) into a
list of normalized paragraphs ready to hand to the sidecar's ``/narrate`` endpoint.

Pure-Python (no extra deps) so it stays in the lean web image. Best-effort: it improves
pronunciation without trying to be a full TTS frontend.
"""
from __future__ import annotations

import re

# ── Number → words ────────────────────────────────────────────────────────────
_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = ["", " thousand", " million", " billion", " trillion", " quadrillion"]
_ORDINAL = {
    "one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
    "nine": "ninth", "twelve": "twelfth",
}


def _under_1000(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + ("-" + _ONES[o] if o else "")
    h, rest = divmod(n, 100)
    return _ONES[h] + " hundred" + (" " + _under_1000(rest) if rest else "")


def int_to_words(n: int) -> str:
    """Cardinal words for a non-negative integer (handles up to ~10^18)."""
    if n == 0:
        return "zero"
    if n < 0:
        return "minus " + int_to_words(-n)
    groups = []
    scale = 0
    while n > 0 and scale < len(_SCALES):
        n, rem = divmod(n, 1000)
        if rem:
            groups.append(_under_1000(rem) + _SCALES[scale])
        scale += 1
    return " ".join(reversed(groups)) or "zero"


def _ordinal_words(n: int) -> str:
    words = int_to_words(n)
    last = words.split()[-1].split("-")[-1]
    if last in _ORDINAL:
        return words[: len(words) - len(last)] + _ORDINAL[last]
    if last.endswith("y"):  # twenty → twentieth
        return words[:-1] + "ieth"
    return words + "th"


def _decimal_words(m: re.Match) -> str:
    whole, frac = m.group(1), m.group(2)
    digits = " ".join(_ONES[int(d)] for d in frac)
    return f"{int_to_words(int(whole))} point {digits}"


def _ordinal_sub(m: re.Match) -> str:
    return _ordinal_words(int(m.group(1)))


def _int_sub(m: re.Match) -> str:
    return int_to_words(int(m.group(0).replace(",", "")))


# ── Abbreviations ─────────────────────────────────────────────────────────────
_ABBREV = {
    "Mr": "Mister", "Mrs": "Missus", "Ms": "Miss", "Dr": "Doctor", "Prof": "Professor",
    "St": "Saint", "Mt": "Mount", "vs": "versus", "etc": "et cetera", "No": "Number",
    "Jr": "Junior", "Sr": "Senior",
}
_ABBREV_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in _ABBREV) + r")\.")

# Unicode → ascii-ish for cleaner pronunciation/pauses.
_PUNCT = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": " - ", "—": " - ", "…": "...", " ": " ",
}
_ZERO_WIDTH = re.compile(r"[​-‏‪-‮﻿]")
# Footnote/reference markers and stray control-bracket runs OmniVoice would misread.
_BRACKET_REFS = re.compile(r"\[[\s\d.,;*†‡—-]{0,40}\]")
_DECIMAL = re.compile(r"\b(\d+)\.(\d+)\b")
_PERCENT = re.compile(r"(\d)\s*%")
_ORDINAL_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b", re.IGNORECASE)
_INT_RE = re.compile(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b")
_WS = re.compile(r"[ \t]+")


def normalize(text: str) -> str:
    """Normalize one passage of prose for narration."""
    if not text:
        return ""
    text = _ZERO_WIDTH.sub("", text)
    for k, v in _PUNCT.items():
        text = text.replace(k, v)
    text = _BRACKET_REFS.sub("", text)
    text = text.replace("[", "").replace("]", "")   # drop any remaining control brackets
    text = _ABBREV_RE.sub(lambda m: _ABBREV[m.group(1)], text)
    text = _PERCENT.sub(lambda m: m.group(1) + " percent", text)
    text = _ORDINAL_RE.sub(_ordinal_sub, text)
    text = _DECIMAL.sub(_decimal_words, text)
    text = _INT_RE.sub(_int_sub, text)
    text = _WS.sub(" ", text)
    return text.strip()


def to_paragraphs(content: str, title: str | None = None, number=None, intro: bool = True) -> list[str]:
    """Split chapter ``content`` into normalized paragraphs (blank-line separated), optionally
    prepending a spoken chapter-title intro. Empty paragraphs are dropped."""
    paras = []
    if intro:
        label = f"Chapter {_fmt_number(number)}" if number is not None else "Chapter"
        if title and str(title).strip():
            paras.append(normalize(f"{label}. {title}."))
        else:
            paras.append(normalize(f"{label}."))
    for block in re.split(r"\n\s*\n", content or ""):
        norm = normalize(block)
        if norm:
            paras.append(norm)
    return paras


def _fmt_number(number) -> str:
    """A chapter number is NUMERIC (may be a float like 15.5). Render 15.0 as '15'."""
    try:
        f = float(number)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(number)
