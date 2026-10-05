import pytest

from tools.benchmark.audit_openvins_init_feature_trace import parse_static_attempt_outcomes


def attempt(t, outcome):
    return (f'FD_INIT_FRAME t={t} db=28\n'
            f'FD_INIT_DISP newest={t} old=28 new=28 stage=ready\n'
            'USING STATIC INITIALIZER METHOD!\n'
            f'[init]: {outcome} initialization in 0.0003 seconds\n')


def test_multiple_ready_attempts_do_not_imply_multiple_successes():
    rows = parse_static_attempt_outcomes(attempt('4.5', 'failed') + attempt('4.6', 'successful'))
    assert [(r['image_s'], r['success']) for r in rows] == [(4.5, False), (4.6, True)]


@pytest.mark.parametrize('text', [
    attempt('4.6', 'successful').replace('stage=ready', 'stage=insufficient_features'),
    attempt('4.6', 'successful').replace('USING STATIC INITIALIZER METHOD!', ''),
    attempt('4.6', 'successful').replace('[init]: successful initialization in 0.0003 seconds', ''),
    attempt('4.6', 'successful') + attempt('4.7', 'successful'),
    attempt('4.6', 'failed'),
    attempt('4.5', 'failed').replace('USING STATIC INITIALIZER METHOD!', '')
    + attempt('4.6', 'successful'),
])
def test_reject_incomplete_or_ambiguous_success(text):
    with pytest.raises(ValueError):
        parse_static_attempt_outcomes(text)
