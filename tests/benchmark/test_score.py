import pytest

from flydrones.benchmark.score import EpisodeScorer, ScoreSample


def sample(sim_ns, position=(0., 0., 1.5), clearance=1., contact=False, in_bounds=True):
    return ScoreSample(sim_ns, position, clearance, contact, in_bounds)


def test_collision_has_priority_over_goal():
    scorer = EpisodeScorer((1., 0., 1.5), .6, 1., 120.)
    assert scorer.update(sample(0, (1., 0., 1.5), -.01, True)) == 'collision'
    assert {'collision', 'goal_region'} <= set(scorer.summary()['events'])


def test_goal_hold_resets_after_leaving_region():
    scorer = EpisodeScorer((1., 0., 1.5), .6, 1., 120.)
    assert scorer.update(sample(0, (1., 0., 1.5))) is None
    assert scorer.update(sample(600_000_000, (2., 0., 1.5))) is None
    assert scorer.update(sample(1_000_000_000, (1., 0., 1.5))) is None
    assert scorer.update(sample(1_900_000_000, (1., 0., 1.5))) is None
    assert scorer.update(sample(2_000_000_000, (1., 0., 1.5))) == 'success'


def test_timeout_and_clock_regression():
    scorer = EpisodeScorer((8., 0., 1.5), .6, 1., 2.)
    assert scorer.update(sample(0)) is None
    assert scorer.update(sample(2_000_000_000)) == 'timeout'
    with pytest.raises(ValueError, match='backwards'):
        scorer.update(sample(1_000_000_000))


def test_swept_clearance_counts_as_collision_without_contact_topic():
    scorer = EpisodeScorer((8., 0., 1.5), .6, 1., 120.)
    assert scorer.update(sample(0, clearance=-.001, contact=False)) == 'collision'
    summary = scorer.summary()
    assert summary['contact_truth'] is False
    assert summary['envelope_collision'] is True


def test_infrastructure_error_outranks_recorded_collision():
    scorer = EpisodeScorer((8., 0., 1.5), .6, 1., 120.)
    scorer.update(sample(0, clearance=-.1, contact=True))
    scorer.fail('infrastructure_error', 'clock drift')
    assert scorer.summary()['status'] == 'infrastructure_error'
    assert 'collision' in scorer.summary()['events']
