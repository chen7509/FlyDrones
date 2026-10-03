import pytest

from tools.benchmark.audit_openvins_init_feature_trace import (
    parse_init_feature_trace,
    summarize_feature_phases,
)


def _states():
    return [
        {'image_ns': '10000000000', 'initialized': '0'},
        {'image_ns': '11000000000', 'initialized': '0'},
        {'image_ns': '12000000000', 'initialized': '1'},
        {'image_ns': '13000000000', 'initialized': '1'},
    ]


def test_trace_links_attempts_by_timestamp_and_retains_no_attempt_frame():
    log = ('FD_INIT_FRAME t=11.000000000 db=0\n'
           'FD_INIT_DISP newest=-1.000000000 old=0 new=0 stage=no_feature_time\n'
           'FD_INIT_FRAME t=12.000000000 db=23\n'
           'FD_INIT_DISP newest=12.000000000 old=17 new=18 stage=ready\n')
    rows = parse_init_feature_trace(log, _states())
    assert [row['attempted'] for row in rows] == [False, True, True]
    assert rows[1]['stage'] == 'no_feature_time'
    assert rows[2]['old_features'] == 17
    phases = summarize_feature_phases(rows, 10.5, 11.5)
    assert phases['prearm']['attempts'] == 1
    assert phases['prearm']['stages'] == {'no_feature_time': 1}


def test_async_initializer_can_complete_after_last_attempted_image():
    log = ('FD_INIT_FRAME t=11.000000000 db=23\n'
           'FD_INIT_DISP newest=11.000000000 old=17 new=18 stage=ready\n')
    rows = parse_init_feature_trace(log, _states())
    assert [row['attempted'] for row in rows] == [False, True, False]
    assert rows[-1]['initialized']


def test_async_initializer_must_have_feature_ready_attempt():
    log = ('FD_INIT_FRAME t=11.000000000 db=0\n'
           'FD_INIT_DISP newest=11.000000000 old=0 new=0 stage=insufficient_features\n')
    with pytest.raises(ValueError, match='feature-ready'):
        parse_init_feature_trace(log, _states())


@pytest.mark.parametrize('malformed', [
    'FD_INIT_FRAME t=10.000000000 db=',
    'FD_INIT_FRAME t=10.000000000 db=23x',
    'FD_INIT_DISP newest=11.000000000 old=17 new= stage=ready',
    'FD_INIT_OTHER t=10.000000000',
])
def test_trace_rejects_truncated_or_unknown_structured_log(malformed):
    log = (malformed + '\nFD_INIT_FRAME t=11.000000000 db=23\n'
           'FD_INIT_DISP newest=11.000000000 old=17 new=18 stage=ready\n')
    with pytest.raises(ValueError, match='malformed initialization diagnostic'):
        parse_init_feature_trace(log, _states())


@pytest.mark.parametrize('log', [
    'FD_INIT_FRAME t=11.000000000 db=0\n',
    'FD_INIT_DISP newest=-1.000000000 old=0 new=0 stage=no_feature_time\n',
    ('FD_INIT_FRAME t=11.000000000 db=0\n'
     'FD_INIT_DISP newest=-1.000000000 old=0 new=0 stage=no_feature_time\n'
     'FD_INIT_FRAME t=11.000000000 db=0\n'
     'FD_INIT_DISP newest=-1.000000000 old=0 new=0 stage=no_feature_time\n'),
    ('FD_INIT_FRAME t=12.000000000 db=0\n'
     'FD_INIT_DISP newest=-1.000000000 old=0 new=0 stage=no_feature_time\n'
     'FD_INIT_FRAME t=11.000000000 db=0\n'
     'FD_INIT_DISP newest=-1.000000000 old=0 new=0 stage=no_feature_time\n'),
])
def test_trace_rejects_missing_duplicate_or_disordered_records(log):
    with pytest.raises(ValueError):
        parse_init_feature_trace(log, _states())
