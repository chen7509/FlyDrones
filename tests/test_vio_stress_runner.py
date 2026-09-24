from tools.run_vio_stress_trial_wsl import relay_closed_cleanly, shared_px4_files_restored


def test_shared_px4_restoration_requires_all_files_to_match(tmp_path):
    run_dir = tmp_path / "run"
    root = tmp_path / "px4"
    backup = run_dir / "backups"
    paths = (
        (backup / "world.sdf", root / "Tools/simulation/gz/worlds/flydrones_forest.sdf"),
        (backup / "OakD-Lite-Fly/model.sdf", root / "Tools/simulation/gz/models/OakD-Lite-Fly/model.sdf"),
        (backup / "x500_depth_fly/model.sdf", root / "Tools/simulation/gz/models/x500_depth_fly/model.sdf"),
    )
    for before, after in paths:
        before.parent.mkdir(parents=True, exist_ok=True)
        after.parent.mkdir(parents=True, exist_ok=True)
        before.write_text("original", encoding="utf-8")
        after.write_text("original", encoding="utf-8")
    assert shared_px4_files_restored(run_dir, root)
    paths[-1][1].write_text("fault routing left behind", encoding="utf-8")
    assert not shared_px4_files_restored(run_dir, root)


def test_truncated_relay_tail_does_not_abort_failure_preservation(tmp_path):
    path = tmp_path / "vio-relay.jsonl"
    path.write_text('{"event": "publish"}\n{"event": "stop"', encoding="utf-8")
    assert not relay_closed_cleanly(path)
    path.write_text('{"event": "publish"}\n{"event": "stop"}\n', encoding="utf-8")
    assert relay_closed_cleanly(path)
