from etl_pipeline.segments import (
    CHANNELS,
    REGIONS,
    SEGMENTS,
    SEGMENT_COLUMNS,
    build_segments,
    stable_index,
)


def test_segments_are_generated_for_every_customer_id():
    segments = build_segments([3, 1, 2])

    assert list(segments.columns) == SEGMENT_COLUMNS
    assert list(segments["customer_id"]) == [1, 2, 3]
    assert segments["customer_id"].is_unique


def test_segments_are_deterministic_between_runs():
    assert build_segments([1, 2, 3, 4]).equals(build_segments([4, 3, 2, 1]))


def test_segments_use_the_documented_categories():
    segments = build_segments(range(1, 51))

    assert set(segments["segment"]) <= set(SEGMENTS)
    assert set(segments["region"]) <= set(REGIONS)
    assert set(segments["acquisition_channel"]) <= set(CHANNELS)
    assert segments["segment"].nunique() == len(SEGMENTS)


def test_segments_ignore_duplicate_and_string_ids():
    segments = build_segments([1, "1", 2])

    assert list(segments["customer_id"]) == [1, 2]


def test_stable_index_is_stable_and_bounded():
    for customer_id in range(1, 30):
        value = stable_index(customer_id, "segment", len(SEGMENTS))
        assert 0 <= value < len(SEGMENTS)
        assert value == stable_index(customer_id, "segment", len(SEGMENTS))
