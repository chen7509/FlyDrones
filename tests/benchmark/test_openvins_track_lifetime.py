"""Strict audit of OpenVINS KLT diagnostic records."""

import pytest

from tools.benchmark.audit_openvins_track_lifetime import parse_track_log, summarize_frames, validate_source_timeline

MATCH = "FD_KLT_MATCH cam0=0 cam1=0 input=12 klt=10 ransac=8 combined=2 status=normal"
FRAME = (
    "FD_KLT_FRAME t=2.800000000 cam=0 previous=2 retained=2 added=10 "
    "input=12 accepted=2 branch=normal"
)


def test_parse_normal_frame_with_exact_id_and_stage_counts():
    lines = "\n".join(
        (MATCH, FRAME, "FD_KLT_ID t=2.800000000 cam=0 id=7", "FD_KLT_ID t=2.800000000 cam=0 id=8")
    )
    frame = parse_track_log(lines)[0]
    assert frame.match.klt == 10
    assert frame.match.ransac == 8
    assert frame.match.combined == frame.accepted == 2
    assert frame.ids == (7, 8)


def test_bootstrap_frame_has_no_match_or_database_observations():
    frame = parse_track_log(
        "FD_KLT_FRAME t=2.700000000 cam=0 previous=0 retained=0 added=9 "
        "input=9 accepted=0 branch=bootstrap"
    )[0]
    assert frame.match is None
    assert frame.ids == ()


@pytest.mark.parametrize(
    "bad",
    [
        MATCH + "\n" + FRAME + "\nFD_KLT_ID t=2.800000000 cam=0 id=7",
        MATCH + "\n" + FRAME + "\nFD_KLT_ID t=2.800000000 cam=0 id=7\nFD_KLT_ID t=2.800000000 cam=0 id=7",
        MATCH.replace("klt=10", "klt=1") + "\n" + FRAME + "\nFD_KLT_ID t=2.800000000 cam=0 id=7\nFD_KLT_ID t=2.800000000 cam=0 id=8",
        MATCH.replace("klt=10", "klt=999") + "\n" + FRAME + "\nFD_KLT_ID t=2.800000000 cam=0 id=7\nFD_KLT_ID t=2.800000000 cam=0 id=8",
        MATCH + "\n" + FRAME.replace("added=10", "added=11") + "\nFD_KLT_ID t=2.800000000 cam=0 id=7\nFD_KLT_ID t=2.800000000 cam=0 id=8",
        MATCH + "\n" + FRAME.replace("cam=0", "cam=1") + "\nFD_KLT_ID t=2.800000000 cam=1 id=7\nFD_KLT_ID t=2.800000000 cam=1 id=8",
        MATCH + "\n" + FRAME.replace("accepted=2", "accepted=bad"),
    ],
)
def test_reject_incomplete_duplicate_or_impossible_records(bad):
    with pytest.raises(ValueError):
        parse_track_log(bad)


def test_reject_time_reversal_and_unpaired_match():
    first = "FD_KLT_FRAME t=2.700000000 cam=0 previous=0 retained=0 added=9 input=9 accepted=0 branch=bootstrap"
    second = first.replace("2.700000000", "2.600000000")
    with pytest.raises(ValueError):
        parse_track_log(first + "\n" + second)
    with pytest.raises(ValueError):
        parse_track_log(MATCH)


def test_count_id_lifetime_from_actual_database_writes():
    first = "FD_KLT_FRAME t=2.700000000 cam=0 previous=0 retained=0 added=9 input=9 accepted=0 branch=bootstrap"
    second = MATCH + "\n" + FRAME + "\nFD_KLT_ID t=2.800000000 cam=0 id=7\nFD_KLT_ID t=2.800000000 cam=0 id=8"
    third = (
        "FD_KLT_MATCH cam0=0 cam1=0 input=12 klt=11 ransac=9 combined=1 status=normal\n"
        "FD_KLT_FRAME t=2.900000000 cam=0 previous=2 retained=2 added=10 input=12 accepted=1 branch=normal\n"
        "FD_KLT_ID t=2.900000000 cam=0 id=7"
    )
    report = summarize_frames(parse_track_log("\n".join((first, second, third))), 2.7, 3.0)
    assert report["frames"] == 3
    assert report["unique_written_ids"] == 2
    assert report["ids_with_two_writes"] == 1
    assert report["accepted_total"] == 3


def test_source_timeline_requires_exact_order_and_unique_initializer_attempts():
    first = "FD_KLT_FRAME t=2.700000000 cam=0 previous=0 retained=0 added=9 input=9 accepted=0 branch=bootstrap"
    frames = parse_track_log("\n".join((first, MATCH, FRAME, "FD_KLT_ID t=2.800000000 cam=0 id=7", "FD_KLT_ID t=2.800000000 cam=0 id=8")))
    validate_source_timeline(frames, [2_700_000_000, 2_800_000_000], [2_800_000_000])
    with pytest.raises(ValueError):
        validate_source_timeline(frames, [2_800_000_000, 2_700_000_000], [2_800_000_000])
    with pytest.raises(ValueError):
        validate_source_timeline(frames, [2_700_000_000, 2_800_000_000], [2_800_000_000, 2_800_000_000])
