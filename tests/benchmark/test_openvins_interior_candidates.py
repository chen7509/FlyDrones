"""Candidate log pairing and the exact upstream integer border rule."""

import pytest

from tools.benchmark.audit_openvins_detection_pruning import DetectionRecord
from tools.benchmark.audit_openvins_interior_candidates import is_interior, parse_candidate_log

FRAME = DetectionRecord(2.8, 0, 9, 0, 0, 0, 0, 0, 9, 2, 1, "topoff", ())
VALID = "\n".join((
    "FD_CANDIDATE x=9.900 y=20.000",
    "FD_CANDIDATE x=30.500 y=30.500",
    "FD_NEW id=101 x=30.500 y=30.500",
    "FD_DETECT_SUMMARY input=9 edge=0 close_bounds=0 grid_bounds=0 close_collision=0 mask=0 retained=9 candidates=2 added=1 branch=topoff",
    "FD_KLT_FRAME t=2.800000000 cam=0 previous=9 retained=9 added=1 input=10 accepted=10 branch=normal",
))


def test_pair_candidates_and_new_id_with_frame():
    records = parse_candidate_log(VALID, [FRAME])
    assert len(records) == 1
    assert len(records[0].candidates) == 2
    assert records[0].new[0].feature_id == 101
    assert not is_interior(records[0].candidates[0].x, records[0].candidates[0].y, 160, 120)
    assert is_interior(records[0].new[0].x, records[0].new[0].y, 160, 120)


def test_duplicate_candidate_coordinates_are_counted_as_separate_extractions():
    frame = DetectionRecord(2.8, 0, 9, 0, 0, 0, 0, 0, 9, 2, 2, "topoff", ())
    log = "\n".join((
        "FD_CANDIDATE x=8.427 y=61.693",
        "FD_CANDIDATE x=8.427 y=61.693",
        "FD_NEW id=101 x=8.427 y=61.693",
        "FD_NEW id=102 x=8.427 y=61.693",
        "FD_DETECT_SUMMARY input=9 edge=0 close_bounds=0 grid_bounds=0 close_collision=0 mask=0 retained=9 candidates=2 added=2 branch=topoff",
        "FD_KLT_FRAME t=2.800000000 cam=0 previous=9 retained=9 added=2 input=11 accepted=11 branch=normal",
    ))
    records = parse_candidate_log(log, [frame])
    assert len(records[0].candidates) == 2
    assert len({(point.x, point.y) for point in records[0].candidates}) == 1


@pytest.mark.parametrize("bad", [
    VALID.replace("FD_CANDIDATE x=30.500 y=30.500\n", ""),
    VALID.replace("FD_NEW id=101 x=30.500 y=30.500\n", ""),
    VALID.replace("FD_NEW id=101", "FD_NEW id=bad"),
    VALID.replace("FD_NEW id=101 x=30.500", "FD_NEW id=101 x=31.500"),
    VALID.replace("t=2.800000000", "t=2.900000000"),
    VALID.replace("FD_CANDIDATE x=30.500", "FD_CANDIDATE x=bad"),
])
def test_reject_missing_mismatch_or_malformed_records(bad):
    with pytest.raises(ValueError):
        parse_candidate_log(bad, [FRAME])


def test_border_uses_integer_cast_like_upstream():
    assert not is_interior(-1.001, 83.503, 160, 120)
    assert not is_interior(-0.207, 96.455, 160, 120)
    assert not is_interior(9.999, 40, 160, 120)
    assert is_interior(10.001, 40, 160, 120)
    assert is_interior(149.999, 40, 160, 120)
    assert not is_interior(150.001, 40, 160, 120)
    assert is_interior(40, 109.999, 160, 120)
    assert not is_interior(40, 110.001, 160, 120)
