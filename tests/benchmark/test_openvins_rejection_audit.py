from __future__ import annotations

from tools.benchmark.audit_openvins_rejections import analyze


def test_only_updater_reason_lines_count_and_replay_must_match(tmp_path) -> None:
    reference = tmp_path / "reference.csv"
    replay = tmp_path / "replay.csv"
    reference.write_text("same bytes\n")
    replay.write_text("same bytes\n")
    log = tmp_path / "stderr.txt"
    log.write_text("\n".join([
        "FD_TRI_REJECT cond=1 max_cond=10 depth=-1 min_dist=0.1 max_dist=60 nan=0",
        "FD_VIO_STAGE t=1.000000000 lost=2 marg=0 maxtracks=0 candidate=2",
        "FD_TRI_REJECT cond=20 max_cond=10 depth=-1 min_dist=0.1 max_dist=60 nan=0",
        "FD_MSCKF_STAGE t=1.000000000 input=2 clean=1 tri=0 chi2=0 tri_fail=1 refine_fail=0 chi2_fail=0",
        "FD_REFINE_REJECT depth=0 min_dist=0.1 max_dist=60 baseline=0 ratio=-nan max_ratio=40 nan=1",
        "FD_VIO_STAGE t=1.100000000 lost=1 marg=0 maxtracks=0 candidate=1",
        "FD_MSCKF_STAGE t=1.100000000 input=1 clean=0 tri=0 chi2=0 tri_fail=0 refine_fail=0 chi2_fail=0",
    ]))
    result = analyze(log, reference, replay)
    assert result["state_csv_identical"] is True
    assert result["windows"] == 2
    assert result["totals"]["input"] == 3
    assert result["totals"]["clean"] == 1
    assert result["tri_reason_combinations"]["condition_number+depth_below_min"] == 1
    assert result["outside_reject_logs"] == 2


def test_rejects_inconsistent_stage_totals(tmp_path) -> None:
    import pytest

    state = tmp_path / "states.csv"
    state.write_text("same\n")
    log = tmp_path / "stderr.txt"
    log.write_text("\n".join([
        "FD_VIO_STAGE t=1.000000000 lost=1 marg=0 maxtracks=0 candidate=1",
        "FD_MSCKF_STAGE t=1.000000000 input=1 clean=1 tri=0 chi2=0 tri_fail=1 refine_fail=0 chi2_fail=0",
    ]))
    with pytest.raises(ValueError, match="reason count"):
        analyze(log, state, state)


def test_refinement_after_failed_triangulation_is_secondary(tmp_path) -> None:
    state = tmp_path / "states.csv"
    state.write_text("same\n")
    log = tmp_path / "stderr.txt"
    log.write_text("\n".join([
        "FD_VIO_STAGE t=1.000000000 lost=2 marg=0 maxtracks=0 candidate=2",
        "FD_TRI_REJECT cond=20 max_cond=10 depth=-1 min_dist=0.1 max_dist=60 nan=0",
        "FD_REFINE_REJECT depth=0 min_dist=0.1 max_dist=60 baseline=0 ratio=-nan max_ratio=40 nan=1",
        "FD_REFINE_REJECT depth=70 min_dist=0.1 max_dist=60 baseline=1 ratio=70 max_ratio=40 nan=0",
        "FD_MSCKF_STAGE t=1.000000000 input=2 clean=2 tri=0 chi2=0 tri_fail=1 refine_fail=1 chi2_fail=0",
    ]))
    result = analyze(log, state, state)
    assert result["totals"]["tri_fail"] == 1
    assert result["totals"]["refine_fail"] == 1
    assert result["secondary_refine_after_failed_tri"]["depth_below_min+nan_position"] == 1
    assert result["refine_reason_combinations"]["depth_above_max+baseline_ratio"] == 1
