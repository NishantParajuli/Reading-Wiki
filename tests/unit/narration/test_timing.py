from __future__ import annotations

import json

from novelwiki.modules.narration.adapters.outbound.migration import LocalAudioFiles
from novelwiki.modules.narration.domain import textprep, timing


def test_paragraph_records_preserve_visible_indexes_around_spoken_intro():
    records = textprep.to_paragraph_records(
        "First paragraph.\n\n[12]\n\nThird paragraph.",
        title="Arrival",
        number=4,
        intro=True,
    )

    assert records == [
        {"text": "Chapter four. Arrival.", "source_index": None},
        {"text": "First paragraph.", "source_index": 0},
        {"text": "Third paragraph.", "source_index": 2},
    ]


def test_timing_manifest_uses_actual_paragraph_durations_and_gaps():
    records = [
        {"text": "Chapter one.", "source_index": None},
        {"text": "Short.", "source_index": 0},
        {"text": "Long.", "source_index": 1},
    ]

    manifest = timing.build_timing_manifest(
        records,
        paragraph_durations_ms=[800, 1200, 4400],
        silence_ms=350,
        duration_ms=7100,
        audio_bytes=1234,
    )

    assert manifest["paragraphs"] == [
        {"source_index": None, "start_ms": 0, "speech_end_ms": 800, "end_ms": 1150},
        {"source_index": 0, "start_ms": 1150, "speech_end_ms": 2350, "end_ms": 2700},
        {"source_index": 1, "start_ms": 2700, "speech_end_ms": 7100, "end_ms": 7100},
    ]


def test_local_audio_files_return_only_matching_timing_manifest(tmp_path):
    audio = tmp_path / "chapter.opus"
    audio.write_bytes(b"opus-bytes")
    manifest = {
        "version": 1,
        "duration_ms": 2000,
        "audio_bytes": audio.stat().st_size,
        "paragraphs": [
            {
                "source_index": 0,
                "start_ms": 0,
                "speech_end_ms": 1900,
                "end_ms": 2000,
            },
        ],
    }
    audio.with_suffix(".timings.json").write_text(json.dumps(manifest), encoding="utf-8")
    files = LocalAudioFiles()

    assert files.read_timing_manifest(str(audio)) == {
        "version": 1,
        "duration_ms": 2000,
        "paragraphs": manifest["paragraphs"],
    }

    audio.write_bytes(b"different-audio-size")
    assert files.read_timing_manifest(str(audio)) is None
