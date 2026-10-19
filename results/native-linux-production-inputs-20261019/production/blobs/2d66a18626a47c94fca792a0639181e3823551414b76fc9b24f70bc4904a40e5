"""Recorded safety constraints and offline scoring; no runtime authorization."""

from __future__ import annotations

import io
import json

from tools.benchmark.audit_live_wire_study import _equal, _integer, _shape
from tools.benchmark.motion_intent_gate import MotionIntentGate
from tools.benchmark.openvins_online_shadow import SourceWatchdog, project_motion_intent_ack
from tools.benchmark.readiness_anchor import AnchoredPolicy, anchored_profile
from tools.benchmark.supported_excitation import MASSES
from tools.benchmark.trajectory_gauge_contract import (
    audit_trajectory,
    trajectory_contract,
    validate_trajectory_gauge_policy,
)

END, STEP = 25_000_000_000, 1_000_000


def _presteps(trace):
    if type(trace) is not list or len(trace) != 50000:
        raise ValueError("incomplete safety callback trace")
    previous = 0
    for index in range(25000):
        ns = (index + 1) * STEP
        pre, post = trace[index * 2 : index * 2 + 2]
        for row, phase in ((pre, "pre"), (post, "post")):
            _equal(row["phase"], phase, "safety callback phase")
            _equal(row["sim_ns"], ns, "safety callback epoch")
            _integer(row["wall_ns"], previous, 2**63 - 1, "safety callback clock")
            previous = row["wall_ns"]
        yield pre, post


def audit_source_health_records(*, sources, trace, terminal, capture_start_ns, watchdog_failure):
    """Recompute arrival constraints, explicitly not a journal of check() calls.

    Per-source arrival order is known. Cross-source callbacks can contend for a
    lock, so this chronological replay is a conservative recorded-time analysis,
    not an assertion about the precise runtime lock acquisition order.
    """
    _equal(watchdog_failure, None, "source watchdog failure")
    _shape(
        terminal,
        ("started_ns", "ready_ns", "last_arrivals", "startup_timeout_ns", "operational_timeout_ns"),
        "source watchdog snapshot",
    )
    _equal(terminal["startup_timeout_ns"], 10_000_000_000, "source startup limit")
    _equal(terminal["operational_timeout_ns"], 2_000_000_000, "source operational limit")
    _integer(capture_start_ns, 1, 2**63 - 1, "capture start")
    steps = list(_presteps(trace))
    start = terminal["started_ns"]
    _integer(start, capture_start_ns, steps[0][0]["wall_ns"], "source watchdog start")
    counts, previous, events = dict(imu=0, rgb=0, info=0), {}, []
    if type(sources) is not list:
        raise ValueError("invalid source records")
    for row in sources:
        kind = row["kind"]
        if kind not in counts:
            continue
        now = row["arrival_monotonic_ns"]
        _integer(now, max(start, previous.get(kind, start - 1) + 1), 2**63 - 1, "source arrival order")
        previous[kind] = now
        counts[kind] += 1
        events.append((now, 0, kind))
    _equal(counts, dict(imu=6251, rgb=251, info=251), "source watchdog input coverage")
    events.extend((pre["wall_ns"], 1, None) for pre, _ in steps)
    events.sort()
    guard = SourceWatchdog(startup_timeout_ns=10_000_000_000)
    guard.start(start)
    try:
        for now, _, kind in events:
            # Check before an arrival can hide a preceding >2s silence. At equal
            # timestamps the arrival and pre-step do not create a positive gap.
            guard.check(now)
            if kind is not None:
                guard.observe(kind, now)
    except (TimeoutError, ValueError) as exc:
        raise ValueError("recorded source interval violates watchdog: " + str(exc)) from exc
    _equal(guard.snapshot(), terminal, "recorded source watchdog snapshot")
    if terminal["ready_ns"] is None:
        raise ValueError("source readiness never established")
    return dict(
        source_counts=counts,
        physical_presteps_checked=len(steps),
        recorded_arrival_constraints_passed=True,
        ready_ns=terminal["ready_ns"],
        every_runtime_watchdog_call_observed=False,
        cross_source_lock_order_proven=False,
        live_qualified=False,
        fusion_qualified=False,
    )


def audit_motion_records(
    *, anchor, profile, forces, trace, intent_records, requests, acknowledgements, intent_terminal, motion_terminal, session_id
):
    """Join one native intent and every recorded force to the frozen time policy.

    Full source/estimator proof attribution at anchor and subsequent readiness
    calls is a separate check. A source string is never authenticated PX4 control.
    These are external unarmed fixture forces, not a learned flight controller.
    """
    _equal(profile, anchored_profile(), "frozen force profile")
    _shape(anchor, ("anchor_ns", "selected_sim_ns", "proof", "profile", "eligible_for_px4_fusion"), "anchor")
    _equal(anchor["profile"], profile, "anchor force profile")
    _equal(anchor["eligible_for_px4_fusion"], False, "anchor fusion flag")
    selected = anchor["selected_sim_ns"]
    _integer(selected, STEP, 8_000_000_000 - STEP, "readiness selection time")
    if selected % STEP:
        raise ValueError("anchor selection outside physical step")
    _equal(anchor["anchor_ns"], selected + 200_000_000, "immutable future anchor")
    if type(forces) is not list or type(intent_records) is not list or len(intent_records) != 4:
        raise ValueError("incomplete normal motion evidence")
    heartbeat = anchor["proof"]["records"]["heartbeat"]
    _equal(heartbeat["system_id"], 9, "anchor heartbeat identity")
    _integer(heartbeat["base_mode"], 0, 127, "unarmed anchor heartbeat")
    steps = list(_presteps(trace))
    selection_pre, selection_post = steps[selected // STEP - 1]
    _integer(anchor["proof"]["checked_wall_ns"], selection_pre["wall_ns"], selection_post["wall_ns"], "anchor proof time")
    raw_requests = [r for r in requests if r["action"]["kind"] == "motion_intent"]
    raw_acks = [r for r in acknowledgements if r["kind"] == "M"]
    if len(raw_requests) != 1 or len(raw_acks) != 1:
        raise ValueError("one native motion-intent request/ack required")
    request, ack = raw_requests[0], raw_acks[0]
    _equal(request["sequence"], ack["sequence"], "motion native request sequence")
    for row, event in zip(
        intent_records,
        ("estimator_state_observed", "motion_intent_requested", "motion_intent_applied", "motion_intent_finish"),
        strict=True,
    ):
        _equal(row["event"], event, "motion event order")
    command = intent_records[1]["command"]
    issued = command["issued_monotonic_ns"]
    _integer(issued, anchor["proof"]["checked_wall_ns"], selection_post["wall_ns"], "motion issue time")
    expected_command = dict(
        session_id=session_id,
        clock_id="gazebo-sim+linux-monotonic",
        command_sequence=0,
        effective_sim_ns=anchor["anchor_ns"],
        issued_monotonic_ns=issued,
        unarmed=True,
        safety_authorized=True,
        velocity_setpoint_frd_m_s=[0.0, 0.0, -0.2],
        yaw_rate_setpoint_rad_s=0.0,
        source="px4-safe-setpoint-supervisor",
    )
    _equal(command, expected_command, "frozen fixture motion command")
    seq = intent_records[0]["native_sequence"]
    cameras = [r for r in acknowledgements if r["kind"] == "C" and r["sequence"] == seq]
    if len(cameras) != 1:
        raise ValueError("motion estimator state missing exact native camera")
    camera = cameras[0]
    estimator = dict(
        kind="C",
        native_sequence=seq,
        sample_ns=camera["sample_ns"],
        acknowledged_ns=camera["acknowledged_ns"],
        internal_initialized=camera["internal_initialized"],
        has_moved_since_zupt=camera["has_moved_since_zupt"],
        reset_counter=camera["reset_counter"],
    )
    output, now = io.StringIO(), [issued]
    gate = MotionIntentGate(
        session_id=session_id,
        clock_id="gazebo-sim+linux-monotonic",
        stream=output,
        clock=lambda: now[0],
        native_adapter_integrated=True,
    )
    gate.observe_estimator(estimator)
    action = gate.request(command)
    _equal(request["action"], action, "native motion action")
    projected = project_motion_intent_ack(ack, action)
    now[0] = projected["acknowledged_ns"]
    _integer(now[0], issued, selection_post["wall_ns"], "native motion completed in anchor selection step")
    gate.acknowledge(projected)
    _equal(gate.authorize_step(anchor["anchor_ns"]), True, "replayed motion gate")
    expected_terminal = gate.finish()
    _equal(intent_records, [json.loads(line) for line in output.getvalue().splitlines()], "motion journal replay")
    _equal(intent_terminal, expected_terminal, "motion gate terminal")
    current, persisted = [0], []
    policy = AnchoredPolicy(lambda: anchor["proof"] if current[0] >= selected else None, persisted.append)
    cursor = 0
    for pre, post in steps:
        ns = current[0] = pre["sim_ns"]
        force = policy.step(ns, STEP, unarmed_wall_ns=pre["wall_ns"], wall_ns=pre["wall_ns"])
        if not any(force):
            continue
        if cursor >= len(forces):
            raise ValueError("missing recorded physical force")
        row = forces[cursor]
        _shape(row, ("sim_ns", "dt_ns", "force_world_n", "per_link", "call_returned", "wall_ns"), "force record")
        _equal(row["sim_ns"], ns, "force epoch")
        _equal(row["dt_ns"], STEP, "force step")
        _equal(row["force_world_n"], force, "frozen force waveform")
        _equal(row["call_returned"], True, "force API completion")
        _integer(row["wall_ns"], max(pre["wall_ns"], now[0]), post["wall_ns"], "force after native authorization")
        if type(row["per_link"]) is not list or len(row["per_link"]) != len(MASSES):
            raise ValueError("incomplete distributed force")
        names = set()
        for link in row["per_link"]:
            _shape(link, ("name", "force_world_n", "call_returned"), "link force")
            name = link["name"]
            if name not in MASSES or name in names:
                raise ValueError("unknown/duplicate force link")
            names.add(name)
            _equal(link["call_returned"], True, "link force completion")
            _equal(link["force_world_n"], [v * MASSES[name] / sum(MASSES.values()) for v in force], "link force distribution")
        cursor += 1
    _equal(cursor, len(forces), "no extra physical force")
    _equal(persisted, [anchor], "single immutable anchor")
    expected_motion = dict(
        policy.finish(), motion_intent_prepared=True, close_errors=[], recorded_commands=cursor, last_attempt=forces[-1]
    )
    for key, value in expected_motion.items():
        _equal(motion_terminal[key], value, "motion terminal " + key)
    return dict(
        anchor_ns=anchor["anchor_ns"],
        support_steps=cursor,
        lateral_steps=policy.active_steps,
        motion_intent_replayed=True,
        all_recorded_forces_match_profile=True,
        anchor_source_attribution_qualified=False,
        per_step_readiness_calls_observed=False,
        flight_controller_authenticated=False,
        live_qualified=False,
        fusion_qualified=False,
    )


def audit_gauge_records(*, states, reference, policy, anchor, motion_profile, health_terminal, result):
    """Reuse the prospective gauge without clipping startup or choosing an origin."""
    validate_trajectory_gauge_policy(policy)
    _equal(motion_profile, anchored_profile(), "gauge motion profile")
    contract = trajectory_contract(
        anchor_ns=anchor["anchor_ns"],
        total_duration_ns=motion_profile["total_duration_ns"],
        lateral_start_offset_ns=motion_profile["lateral_start_after_anchor_ns"],
    )
    truth = []
    for row in reference:
        _equal(row["truth_for_abort_audit_only"], True, "isolated truth scope")
        truth.append(dict(row, sim_ns=row["post_ns"], truth_for_fixture_audit_only=True))
    session = dict(
        session_id=health_terminal["session_id"],
        reset_counter=health_terminal["reset_counter"],
        reset_observed=health_terminal["reset_total"] != 0,
        quality=health_terminal["last_quality"],
        covariance_calibrated=False,
    )
    scored = audit_trajectory(states, truth, session, dict(status=result["status"], end_sim_ns=result["end_sim_ns"]), contract)
    return dict(scored, live_qualified=False, fusion_qualified=False)


def audit_anchor_records(*, anchor, sources, fanout, heartbeat_records, estimator_records, acknowledgements):
    """Attribute the saved anchor to journals, without granting capture coverage.

    The whole-study caller separately checks full source/native coverage. A
    retained subset can exercise these joins but cannot prove omitted history.
    Heartbeat write/flush completion lacks its own timestamp: the saved receipt
    is bounded by observation/reconciliation, never invented as an extra event.
    """
    from tools.benchmark.estimator_aware_readiness import EstimatorAwareReadiness
    from tools.benchmark.readiness_anchor import JournaledReadiness
    from tools.benchmark.ready_shadow_fanout import digest

    def index(rows, field):
        result = {}
        for row in rows:
            seq = row[field]
            _integer(seq, 0, 2**63 - 1, field)
            if seq in result:
                raise ValueError("duplicate " + field)
            result[seq] = row
        return result

    proof = anchor["proof"]
    _shape(
        proof,
        ("checked_wall_ns", "records", "freshness", "scope", "estimator_internal", "first_estimator_internal", "truth_used"),
        "anchor proof",
    )
    checked = proof["checked_wall_ns"]
    _integer(checked, 1, 2**63 - 1, "anchor wall time")
    _shape(proof["records"], ("imu", "rgb", "info", "heartbeat"), "anchor receipts")
    by_source = index(sources, "source_sequence")
    deliveries = index([r for r in fanout if r["event"] == "source_delivery"], "source_sequence")
    intents = index([r for r in fanout if r["event"] == "source_intent"], "source_sequence")
    _equal(set(deliveries), set(by_source), "source delivery membership")
    _equal(set(intents), set(by_source), "source intent membership")
    _equal(len(fanout), 2 * len(sources), "fanout event coverage")
    previous_end = 0
    for source in sources:
        seq = source["source_sequence"]
        delivery, intent = deliveries[seq], intents[seq]
        for record in (intent, delivery):
            _equal(record["source_sha256"], digest(source), "fanout source identity")
        _equal(delivery["dispositions"], dict(shadow="returned", readiness="returned"), "committed delivery")
        _equal(intent["begin_ns"], delivery["begin_ns"], "fanout start")
        times = [
            delivery["begin_ns"],
            delivery["consumers"]["shadow"]["start_ns"],
            delivery["consumers"]["shadow"]["returned_ns"],
            delivery["consumers"]["readiness"]["start_ns"],
            delivery["consumers"]["readiness"]["returned_ns"],
            delivery["end_ns"],
        ]
        for stamp in times:
            _integer(stamp, previous_end, 2**63 - 1, "fanout clock")
            previous_end = stamp

    # Reuse the actual estimator projection; require one record for every
    # initialized C acknowledgement supplied by the full workload audit.
    camera = index([a for a in acknowledgements if a["kind"] == "C" and a["internal_initialized"]], "sequence")
    records = index(estimator_records, "native_sequence")
    _equal(set(records), set(camera), "estimator journal membership")
    clock, stream = [0], io.StringIO()
    guard = EstimatorAwareReadiness(".", JournaledReadiness(), clock=lambda: clock[0], stream=stream)
    committed = []
    for row in estimator_records:
        seq = row["source_sequence"]
        if seq not in by_source:
            raise ValueError("estimator source absent")
        bounds = deliveries[seq]["consumers"]["shadow"]
        clock[0] = row["journal_ack_monotonic_ns"]
        _integer(clock[0], bounds["start_ns"], bounds["returned_ns"], "estimator journal inside shadow call")
        guard.observe_ack_batch([camera[row["native_sequence"]]], by_source[seq])
        if deliveries[seq]["end_ns"] <= checked:
            committed.append(row)
    _equal([json.loads(line) for line in stream.getvalue().splitlines()], estimator_records, "estimator projection")
    if not committed:
        raise ValueError("no committed estimator state at anchor")
    _equal(proof["first_estimator_internal"], committed[0], "first estimator anchor state")
    _equal(proof["estimator_internal"], committed[-1], "latest estimator anchor state")
    _integer(checked - committed[-1]["acknowledged_monotonic_ns"], 0, 2_000_000_000, "estimator freshness")

    # Independently observed heartbeat identities must reconcile in FIFO order.
    observed, reconciled, pending = [], {}, []
    last_wall = last_arrival = last_sim = 0
    for row in heartbeat_records:
        event = row["event"]
        if event == "heartbeat_observed":
            _shape(
                row,
                ("event", "observation_sequence", "source_sha256", "arrival_monotonic_ns", "observed_ns", "original"),
                "heartbeat observation",
            )
            _equal(row["observation_sequence"], len(observed), "heartbeat observation sequence")
            original = row["original"]
            _shape(
                original,
                ("kind", "arrival_monotonic_ns", "observed_sim_ns", "system_id", "base_mode", "custom_mode"),
                "raw heartbeat",
            )
            _equal(original["kind"], "heartbeat", "heartbeat kind")
            _equal(original["system_id"], 9, "heartbeat system")
            _integer(original["base_mode"], 0, 127, "unarmed heartbeat")
            _integer(original["custom_mode"], 0, 2**32 - 1, "heartbeat mode")
            _equal(row["source_sha256"], digest(original), "heartbeat raw identity")
            _equal(row["arrival_monotonic_ns"], original["arrival_monotonic_ns"], "heartbeat arrival")
            _integer(original["arrival_monotonic_ns"], last_arrival + 1, 2**63 - 1, "heartbeat arrival order")
            _integer(original["observed_sim_ns"], last_sim, 2**63 - 1, "heartbeat simulation order")
            now = row["observed_ns"]
            _integer(
                now,
                max(last_wall, original["arrival_monotonic_ns"]),
                original["arrival_monotonic_ns"] + 2_000_000_000,
                "heartbeat observation time",
            )
            if len(pending) >= 32:
                raise ValueError("heartbeat pending capacity")
            pending.append(row)
            observed.append(row)
            last_arrival, last_sim = original["arrival_monotonic_ns"], original["observed_sim_ns"]
        elif event == "heartbeat_reconciled":
            _shape(
                row,
                ("event", "observation_sequence", "source_sequence", "source_sha256", "reconciled_ns"),
                "heartbeat reconciliation",
            )
            if not pending:
                raise ValueError("heartbeat reconciliation without observation")
            item = pending[0]
            _equal(row["observation_sequence"], item["observation_sequence"], "heartbeat FIFO")
            _equal(row["source_sha256"], item["source_sha256"], "heartbeat reconciliation hash")
            source = by_source.get(row["source_sequence"])
            if source is None:
                raise ValueError("heartbeat queued source absent")
            original = {
                k: v
                for k, v in source.items()
                if k not in {"source_sequence", "writer_begin_monotonic_ns", "recorded_monotonic_ns"}
            }
            _equal(original, item["original"], "heartbeat queued original")
            now = row["reconciled_ns"]
            bounds = deliveries[row["source_sequence"]]["consumers"]["readiness"]
            _integer(now, max(last_wall, bounds["start_ns"]), bounds["returned_ns"], "heartbeat reconciliation time")
            reconciled[item["observation_sequence"]] = row
        else:
            raise ValueError("unexpected heartbeat journal event")
        if pending and now - pending[0]["arrival_monotonic_ns"] > 2_000_000_000:
            raise ValueError("heartbeat reconciliation deadline")
        if event == "heartbeat_reconciled":
            pending.pop(0)
        last_wall = now
    if pending or len(observed) != sum(r["kind"] == "heartbeat" for r in sources):
        raise ValueError("incomplete heartbeat reconciliation")

    receipts = []
    for kind in ("imu", "rgb", "info"):
        candidates = [r for r in sources if r["kind"] == kind and deliveries[r["source_sequence"]]["end_ns"] <= checked]
        if not candidates:
            raise ValueError("missing committed anchor source")
        latest = candidates[-1]
        saved = proof["records"][kind]
        _equal({k: v for k, v in saved.items() if k != "journal_ack_monotonic_ns"}, latest, "latest committed source receipt")
        bounds = deliveries[latest["source_sequence"]]["consumers"]["readiness"]
        _integer(saved["journal_ack_monotonic_ns"], bounds["start_ns"], bounds["returned_ns"], "source receipt call bounds")
        receipts.append(saved)
    at_anchor = [r for r in observed if r["observed_ns"] <= checked][-32:]
    eligible = [r for r in at_anchor if r["original"]["observed_sim_ns"] <= proof["records"]["imu"]["observed_sim_ns"]]
    if not eligible:
        raise ValueError("no eligible heartbeat at anchor")
    item = eligible[-1]
    saved = proof["records"]["heartbeat"]
    expected = dict(item["original"], writer_begin_monotonic_ns=item["observed_ns"], recorded_monotonic_ns=item["observed_ns"])
    _equal({k: v for k, v in saved.items() if k != "journal_ack_monotonic_ns"}, expected, "selected heartbeat receipt")
    _integer(
        saved["journal_ack_monotonic_ns"],
        item["observed_ns"],
        min(checked, reconciled[item["observation_sequence"]]["reconciled_ns"]),
        "heartbeat receipt bound",
    )
    receipts.append(saved)
    replay_clock = [0]
    readiness = JournaledReadiness(clock=lambda: replay_clock[0])
    for receipt in sorted(receipts, key=lambda r: r["journal_ack_monotonic_ns"]):
        replay_clock[0] = receipt["journal_ack_monotonic_ns"]
        readiness.on_record({k: v for k, v in receipt.items() if k != "journal_ack_monotonic_ns"}, None)
    replay_clock[0] = checked
    replay = readiness.proof()
    if replay is None:
        raise ValueError("anchor source freshness refused")
    replay["freshness"]["latest_heartbeat_ahead_ns"] = max(
        0, at_anchor[-1]["original"]["observed_sim_ns"] - proof["records"]["imu"]["observed_sim_ns"]
    )
    replay.update(
        estimator_internal=committed[-1],
        first_estimator_internal=committed[0],
        truth_used=False,
        scope="sensor fan-out commit plus independent heartbeat write/flush; heartbeat reconciliation is separate; not fsync durability",
    )
    _equal(proof, replay, "anchor proof replay")
    return dict(
        recorded_anchor_attribution_passed=True,
        estimator_records=len(records),
        heartbeat_observations=len(observed),
        **{k: replay["freshness"][k] for k in ("heartbeat_wall_age_ns", "heartbeat_sim_age_ns")},
        per_step_readiness_calls_observed=False,
        heartbeat_flush_timestamp_independently_observed=False,
        full_capture_coverage_proven=False,
        live_qualified=False,
        fusion_qualified=False,
    )
