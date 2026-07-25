"""Generation-time narration timing manifests."""
from __future__ import annotations


def build_timing_manifest(
    paragraph_records: list[dict],
    paragraph_durations_ms: list[int],
    silence_ms: int,
    duration_ms: int,
    audio_bytes: int,
) -> dict:
    """Combine actual synthesized PCM durations with visible paragraph identities.

    ``speech_end_ms`` excludes the configured inter-paragraph gap. ``end_ms`` includes
    that gap so the final sentence remains highlighted until the next paragraph begins.
    """
    if len(paragraph_records) != len(paragraph_durations_ms):
        raise ValueError("Narration paragraph timing count does not match generated text.")

    cursor = 0
    paragraphs = []
    for index, (record, raw_duration) in enumerate(
        zip(paragraph_records, paragraph_durations_ms, strict=True)
    ):
        paragraph_duration = max(0, int(raw_duration))
        start = cursor
        speech_end = start + paragraph_duration
        gap = max(0, int(silence_ms)) if index < len(paragraph_records) - 1 else 0
        end = speech_end + gap
        paragraphs.append({
            "source_index": record.get("source_index"),
            "start_ms": start,
            "speech_end_ms": speech_end,
            "end_ms": end,
        })
        cursor = end

    return {
        "version": 1,
        "duration_ms": max(0, int(duration_ms)),
        "audio_bytes": max(0, int(audio_bytes)),
        "paragraphs": paragraphs,
    }
