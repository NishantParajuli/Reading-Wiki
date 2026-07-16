from novelwiki.modules.codex.adapters.outbound.context import _chapter_memory_shape


def test_unlabeled_incomplete_block_has_no_checkpoint_target():
    shape = _chapter_memory_shape(
        10.0,
        {
            "kind": "chapter",
            "part_label": None,
            "narrative_part_chapters": [float(number) for number in range(1, 11)],
        },
    )

    assert shape["memory_targets"] == []
    assert shape["block_numbers"] == [float(number) for number in range(1, 10)]


def test_unlabeled_fixed_boundary_closes_checkpoint():
    shape = _chapter_memory_shape(
        25.0,
        {
            "kind": "chapter",
            "part_label": None,
            "narrative_part_chapters": [float(number) for number in range(1, 26)],
        },
    )

    assert shape["memory_targets"] == [{
        "kind": "checkpoint",
        "start_chapter": 1.0,
        "end_chapter": 25.0,
        "through_chapter": 25.0,
        "part_label": None,
    }]
    assert shape["block_numbers"] == [float(number) for number in range(1, 25)]


def test_real_part_end_closes_short_checkpoint_and_volume():
    shape = _chapter_memory_shape(
        7.0,
        {
            "kind": "chapter",
            "part_label": "Volume 1",
            "narrative_part_chapters": [float(number) for number in range(1, 8)],
        },
    )

    assert [target["kind"] for target in shape["memory_targets"]] == ["checkpoint", "volume"]
    assert all(target["through_chapter"] == target["end_chapter"] == 7.0
               for target in shape["memory_targets"])
