"""Strict pairing of OpenVINS detection decisions with tracked frames."""

import pytest

from tools.benchmark.audit_openvins_detection_pruning import parse_detection_log
from tools.benchmark.audit_openvins_track_lifetime import Match, TrackFrame

FRAMES = [
    TrackFrame(2.8, 0, 2, 2, 10, 12, 2, "normal", Match(0, 0, 12, 12, 12, 12, "normal"), (7, 8)),
    TrackFrame(2.9, 0, 2, 1, 11, 12, 1, "normal", Match(0, 0, 12, 12, 12, 12, "normal"), (7,)),
]
FIRST = (
    "FD_DETECT_SUMMARY input=2 edge=0 close_bounds=0 grid_bounds=0 close_collision=0 "
    "mask=0 retained=2 candidates=10 added=10 branch=topoff\n"
    "FD_KLT_FRAME t=2.800000000 cam=0 previous=2 retained=2 added=10 input=12 accepted=2 branch=normal"
)
DROP = "FD_DETECT_DROP id=8 reason=close_collision x=30.500 y=20.500"
SECOND = (
    "FD_DETECT_SUMMARY input=2 edge=0 close_bounds=0 grid_bounds=0 close_collision=1 "
    "mask=0 retained=1 candidates=11 added=11 branch=topoff\n"
    "FD_KLT_FRAME t=2.900000000 cam=0 previous=2 retained=1 added=11 input=12 accepted=1 branch=normal"
)


def test_pair_pruning_reason_with_previous_written_id():
    records = parse_detection_log("\n".join((FIRST, DROP, SECOND)), FRAMES)
    assert len(records) == 2
    assert records[1].time == 2.9
    assert records[1].drops[0].feature_id == 8
    assert records[1].drops[0].reason == "close_collision"
    assert records[1].retained == 1


@pytest.mark.parametrize(
    "bad",
    [
        FIRST + "\n" + SECOND,
        FIRST + "\n" + DROP.replace("id=8", "id=99") + "\n" + SECOND,
        FIRST + "\n" + DROP + "\n" + DROP + "\n" + SECOND,
        FIRST + "\n" + DROP.replace("close_collision", "unknown") + "\n" + SECOND,
        FIRST + "\n" + DROP + "\n" + SECOND.replace("close_collision=1", "close_collision=0"),
        FIRST + "\n" + DROP + "\n" + SECOND.replace("added=11", "added=10"),
        FIRST + "\n" + DROP + "\n" + SECOND.replace("t=2.900000000", "t=3.000000000"),
    ],
)
def test_reject_missing_duplicate_unknown_or_misaligned_detection(bad):
    with pytest.raises(ValueError):
        parse_detection_log(bad, FRAMES)


def test_skip_extraction_still_emits_one_summary():
    frame = TrackFrame(2.8, 0, 12, 12, 0, 12, 12, "normal", Match(0, 0, 12, 12, 12, 12, "normal"), tuple(range(12)))
    log = (
        "FD_DETECT_SUMMARY input=12 edge=0 close_bounds=0 grid_bounds=0 close_collision=0 "
        "mask=0 retained=12 candidates=0 added=0 branch=skip\n"
        "FD_KLT_FRAME t=2.800000000 cam=0 previous=12 retained=12 added=0 input=12 accepted=12 branch=normal"
    )
    assert parse_detection_log(log, [frame])[0].branch == "skip"
