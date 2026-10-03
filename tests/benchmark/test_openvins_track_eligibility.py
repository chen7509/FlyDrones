import pytest

from tools.benchmark.audit_openvins_track_eligibility import parse_track_count_trace

FEATURE_ROWS = [
    {'image_ns': 2_600_000_000, 'attempted': True, 'stage': 'no_feature_time',
     'db_features': 0,
     'old_features': 0, 'new_features': 0},
    {'image_ns': 2_700_000_000, 'attempted': True, 'stage': 'insufficient_features',
     'db_features': 4,
     'old_features': 1, 'new_features': 0},
]
COUNT = ('FD_TRACK_COUNTS newest=2.700000000 db=3 tracks=3 '
         'old0=1 old1=1 old2=1 new0=2 new1=1 new2=0 '
         'both2=0 old_max=2 new_max=1')


def test_track_counts_pair_with_initializer_and_disparity():
    rows = parse_track_count_trace('InertialInitializer.cpp:123 ' + COUNT, FEATURE_ROWS)
    assert len(rows) == 1
    assert rows[0]['image_ns'] == 2_700_000_000
    assert rows[0]['old2'] == 1
    assert rows[0]['new2'] == 0
    assert rows[0]['db_before_cleanup'] == 4
    assert rows[0]['db_removed_by_cleanup'] == 1


@pytest.mark.parametrize('log', [
    '',
    COUNT.replace('old2=1', 'old2=0'),
    COUNT.replace('tracks=3', 'tracks=4'),
    COUNT + '\n' + COUNT,
    COUNT.replace('old_max=2', 'old_max=oops'),
    COUNT + '\n' + COUNT.replace('newest=2.700000000', 'newest=2.600000000'),
])
def test_track_counts_reject_missing_or_inconsistent_rows(log):
    with pytest.raises(ValueError):
        parse_track_count_trace(log, FEATURE_ROWS)


def test_track_counts_reject_db_growth_during_cleanup():
    impossible = [FEATURE_ROWS[0], {**FEATURE_ROWS[1], 'db_features': 2}]
    with pytest.raises(ValueError, match='database'):
        parse_track_count_trace(COUNT, impossible)
