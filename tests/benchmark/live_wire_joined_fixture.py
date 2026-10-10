"""Shared synthetic clock for joined offline tests; never a physical producer.

Real observed-session, pinned codec and journal classes are used. Datagram and
daemon transports, owner observations and physical states are explicitly fake.
No leaf auditor is replaced. This is a foundation for the full study fixture,
not that fixture's completion or a live-run qualification.
"""

import copy
import json
from datetime import timedelta
from types import SimpleNamespace

from tests.benchmark.test_openvins_observed_wire_session import Datagram
from tests.benchmark.test_openvins_wire_bootstrap import OWNER, Backend, Connection, body, frame, mav
from tests.benchmark.test_openvins_wire_heartbeat import heartbeat
from tests.benchmark.test_openvins_wire_maintenance import status
from tools.benchmark.openvins_ekf2_disarmed_preflight import RemoteMonotonicClock
from tools.benchmark.openvins_observed_wire_session import ObservedWireSession
from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal
from tools.benchmark.openvins_simulation_clock import JournaledSimulationClock

END = 25_000_000_000
STEP = 1_000_000
SESSION = "normal-v1.clock"
DAEMON = "/tmp/px4-sock-8"


class SyntheticBackend(Backend):
    def connect(self, path, timeout):
        if path != DAEMON:
            raise ValueError("unexpected synthetic daemon path")
        connection = self.connections[len(self.used)]
        self.used.append(connection)
        return connection


def build_joined_wire_physics(directory, *, owner=None):
    """Generate original records once with zero-origin and one monotonic clock.

    The synthetic physics clock advances at 2x wall speed, permitting the fixed
    500-sample startup inside eight wall seconds. This is chosen test timing,
    not measured RTF. Sensor/native/motion/gauge evidence is not supplied yet.
    """
    directory.mkdir(parents=True)
    backend, sock = SyntheticBackend(), Datagram()
    owner = copy.deepcopy(OWNER if owner is None else owner)
    backend.owner = copy.deepcopy(owner)
    retention = SegmentedWireJournal(directory / "wire-segments")
    attempts, reference, trace = [], [], []
    step = 0
    state = dict(
        position=[0.0, 0.0, 0.5],
        velocity_world=[0.0, 0.0, 0.0],
        accel_world=[0.0, 0.0, 0.0],
        angular_world=[0.0, 0.0, 0.0],
        quaternion_xyzw=[0.0, 0.0, 0.0, 1.0],
    )
    with (directory / "wire-clock.jsonl").open("x", encoding="utf8") as stream:

        def journal(row):
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            attempts.append(copy.deepcopy(row))
            backend.now += 1

        lane = JournaledSimulationClock(SESSION, backend.clock, journal, 10, lambda: None)
        remote = RemoteMonotonicClock(SESSION, sim_origin_ns=0, remote_origin_ns=0)
        session = ObservedWireSession(
            SimpleNamespace(pid=owner["pid"]),
            owner,
            DAEMON,
            remote,
            lane,
            sock,
            10,
            lambda event: None,
            lambda value: None,
            backend=backend,
            heartbeat_sink=lambda row: None,
            interval_transaction=True,
            retention=retention,
        )

        def advance(target):
            nonlocal step
            while step * STEP < target:
                step += 1
                ns, wall = step * STEP, 10 + step * STEP // 2
                if backend.now > wall:
                    raise ValueError("synthetic shared monotonic clock regressed")
                backend.now = wall
                trace.append(
                    dict(
                        copy.deepcopy(state),
                        phase="pre",
                        sim_ns=ns,
                        dt_ns=STEP,
                        state_time_ns=ns - STEP,
                        state_time_basis="callback_phase_only",
                        component_refresh_verified=False,
                        wall_ns=wall,
                        available=True,
                        truth_for_diagnostics_only=True,
                    )
                )
                backend.now += 1
                lane.post_update(
                    SimpleNamespace(
                        iterations=step, paused=False, dt=timedelta(milliseconds=1), sim_time=timedelta(milliseconds=step)
                    )
                )
                backend.now += 1
                reference.append(
                    dict(
                        copy.deepcopy(state),
                        rpy=[0.0, 0.0, 0.0],
                        parent_entity=24,
                        child_entity=69,
                        pre_ns=ns,
                        post_ns=ns,
                        canary_overwritten=True,
                        wall_ns=backend.now,
                        truth_for_abort_audit_only=True,
                        eligible_for_px4_fusion=False,
                    )
                )
                backend.now += 1
                trace.append(
                    dict(
                        copy.deepcopy(state),
                        phase="post",
                        sim_ns=ns,
                        dt_ns=STEP,
                        state_time_ns=ns,
                        state_time_basis="callback_phase_only",
                        component_refresh_verified=False,
                        wall_ns=backend.now,
                        available=True,
                        truth_for_diagnostics_only=True,
                    )
                )

        def receive(*messages):
            encoder = mav.MAVLink(None, srcSystem=9, srcComponent=1)
            sock.input.append(heartbeat() + b"".join(message.pack(encoder) for message in messages))
            session.poll_datagram()

        def ack(command=511):
            return mav.MAVLink_command_ack_message(command, 0, 0, 0, 254, 191)

        def query(value):
            session.poll_interval()
            receive(ack(510), mav.MAVLink_message_interval_message(111, value))
            session.poll_interval()

        def timesync(index):
            request, response, _ = body(index)
            # Zero-offset mapping needs an actually observed response epoch,
            # rather than adding 1ms to a different observed simulation stamp.
            advance(response)
            receive(mav.MAVLink_timesync_message(0, request))

        try:
            session.poll_listener()
            session.poll_listener()
            advance(1_000_000)
            query(100000)
            session.poll_interval()
            receive(ack())
            session.poll_interval()
            query(10000)
            timesync(0)
            for _ in range(3):
                session.poll_listener()
            for index in range(1, 500):
                timesync(index)
                backend.connections[2].reads.append(frame(index))
                session.poll_listener()
            backend.connections[2].reads.extend([b"\0\0", b""])
            session.poll_listener()
            session.poll_listener()
            session.poll_interval()
            receive(ack())
            session.poll_interval()
            query(100000)
            query(100000)
            session.begin_maintenance(300_000_000_010)
            backend.connections.append(Connection([status(499, 1)]))
            session.poll_listener()
            # Sustain observations over the rest of 25s rather than leaving a
            # final multi-second gap behind a static success summary.
            maintenance = 0
            for index in range(500, 1245, 5):
                timesync(index)
                maintenance += 1
                backend.connections[3].reads.append(status(index, maintenance + 1))
                session.poll_listener()
            advance(END)
        finally:
            session.close()
        terminal = retention.close()
        clock = lane.evidence
        lifecycle = session.evidence
    disk_attempts = [json.loads(line) for line in (directory / "wire-clock.jsonl").read_text().splitlines()]
    if disk_attempts != attempts:
        raise ValueError("synthetic journal changed during generation")
    for name, rows in (("native-reference.jsonl", reference), ("physics-substeps.jsonl", trace)):
        with (directory / name).open("x", encoding="utf8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
    return dict(
        directory=directory,
        retention=terminal,
        clock=clock,
        clock_attempts=disk_attempts,
        context=dict(owner=copy.deepcopy(owner), start_ns=10, total_deadline_ns=300_000_000_010, clock_signature=[SESSION, 0, 0]),
        session=lifecycle,
        physical=dict(
            reference=reference,
            trace=trace,
            observations=clock["observations"],
            terminal=dict(
                pre_count=25000,
                post_count=25000,
                failure=None,
                close_errors=[],
                complete=True,
                eligible_for_px4_fusion=False,
                native=dict(failed=False, pending=False, last_ns=END),
                last_attempt=dict(phase="post", ns_repr=str(END), wall_ns=reference[-1]["wall_ns"]),
            ),
            trace_terminal=dict(
                records=50000,
                unavailable_records=0,
                failure=None,
                close_errors=[],
                complete=True,
                backend_recorded=True,
                eligible_for_px4_fusion=False,
                last_attempt=dict(phase="post", sim_ns_repr=str(END), record_index=49999),
            ),
        ),
        synthetic_provenance=True,
        physical_execution_qualified=False,
        live_qualified=False,
    )


def add_joined_sources(evidence, *, initialized_at_ns=None):
    """Attach synthetic inputs/ACKs and real CameraInfo bytes on the same clock.

    Native ACKs default to uninitialized. Optional initialized output remains
    synthetic: no estimator ran and the full normal study is still incomplete.
    """
    from tests.benchmark.live_wire_source_fixture import build_chain, synthetic_fast_records
    from tests.benchmark.test_live_wire_camera_info import fixture as camera_fixture
    from tools.benchmark.openvins_online_shadow import OnlineHealthEvidence, SourceWatchdog

    camera = camera_fixture()
    payloads = {
        row["sample_ns"]: camera["payloads"][row["source_sequence"]] for row in camera["sources"] if row["kind"] == "info"
    }
    used = {}

    def arrival(stamp):
        used[stamp] = used.get(stamp, 0) + 1
        # These callbacks run after the retained PostUpdate epoch. Multiple
        # sources at one stamp use disjoint delivery intervals inside the step.
        post = evidence["physical"]["trace"][2 * (stamp // STEP - 1) + 1]
        return post["wall_ns"] + used[stamp] * 100

    source = build_chain(
        arrival_clock=arrival,
        info_payloads=payloads,
        session_id="online-native-322",
        initialized_at_ns=initialized_at_ns,
    )
    directory = evidence["directory"] / "shadow"
    directory.mkdir()
    if initialized_at_ns is not None:
        from tests.benchmark.live_wire_motion_fixture import build_motion

        build_motion(source, evidence["physical"]["trace"], directory)
    fast = synthetic_fast_records(source["acknowledgements"])
    health = OnlineHealthEvidence(directory, session_id=source["session_id"])
    for state in source["states"]:
        health.observe_camera(state)
    health_terminal = health.finish()
    source["terminal"]["health_last"] = health_terminal["last_health"]
    guard = SourceWatchdog(startup_timeout_ns=10_000_000_000)
    guard.start(evidence["context"]["start_ns"])
    for row in source["sources"]:
        if row["kind"] in ("imu", "rgb", "info"):
            guard.observe(row["kind"], row["arrival_monotonic_ns"])
    evidence.update(
        source=source,
        fast=dict(records=fast, acknowledgements=source["acknowledgements"], end_sim_ns=END),
        camera=dict(
            sources=source["sources"],
            payloads=source["payloads"],
            manifest=camera["manifest"],
            first_payload=camera["first_payload"],
        ),
        health=dict(
            states=source["states"],
            records=[json.loads(line) for line in (directory / "health-evidence.jsonl").read_text().splitlines()],
            terminal=health_terminal,
            shadow_last=source["terminal"]["health_last"],
            session_id=source["session_id"],
            profile_name="px4-d6f12ad-gate-floor-v1",
        ),
        source_health=dict(
            sources=source["sources"],
            trace=evidence["physical"]["trace"],
            terminal=guard.snapshot(),
            capture_start_ns=evidence["context"]["start_ns"],
            watchdog_failure=None,
        ),
    )
    capture = evidence["directory"]
    for name, rows in (
        ("events.jsonl", source["sources"]),
        ("source-fanout.jsonl", source["fanout"]),
        ("shadow/native-requests.jsonl", source["requests"]),
        ("shadow/native-acks.jsonl", source["acknowledgements"]),
        ("shadow/states.jsonl", source["states"]),
        ("shadow/synthetic-fast-state.jsonl", fast),
    ):
        with (capture / name).open("x", encoding="utf8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
    for name, value in (
        ("camera-info.json", camera["manifest"]),
        ("shadow/shadow-input-result.json", source["terminal"]),
        ("synthetic-wire-session.json", evidence["session"]),
        ("synthetic-context.json", evidence["context"]),
        ("synthetic-physical-terminal.json", evidence["physical"]["terminal"]),
        ("synthetic-trace-terminal.json", evidence["physical"]["trace_terminal"]),
        ("synthetic-source-health.json", guard.snapshot()),
        (
            "synthetic-provenance.json",
            dict(
                schema="joined-offline-fixture-v2",
                synthetic_provenance=True,
                fake_interfaces=["datagram", "daemon", "owner", "physical_state", "native_ack", "fast_prediction"],
                synthetic_initialization_ns=initialized_at_ns,
                synthetic_motion=initialized_at_ns is not None,
                force_calls_executed=False,
                physical_state_independent_of_force_commands=True,
                shared_clock="simulation_ns/2+10, test scheduling only; not measured RTF",
                omitted=["runtime_maps", "resource_graph", "ULog", "full_file_entry"]
                + ([] if initialized_at_ns is not None else ["motion", "anchor", "gauge"]),
                native_estimator_run=False,
                physical_execution_qualified=False,
                whole_study_qualified=False,
                live_qualified=False,
                fusion_qualified=False,
            ),
        ),
    ):
        with (capture / name).open("x", encoding="utf8") as stream:
            json.dump(value, stream)
    (capture / "camera-info.pb").write_bytes(camera["first_payload"])
    (capture / "camera-info-messages").mkdir()
    (capture / "rgb-frames").mkdir()
    for row in source["sources"]:
        if row["kind"] == "info":
            (capture / row["payload_path"]).write_bytes(source["payloads"][row["source_sequence"]])
        elif row["kind"] == "rgb":
            (capture / "rgb-frames" / f"{row['sample_ns']}.ppm").write_bytes(
                b"P6\n160 120\n255\n" + source["payloads"][row["source_sequence"]]
            )
    return evidence


def read_joined_fixture(directory):
    """Read the partial synthetic bundle from disk, using the production reader."""
    from tools.benchmark.audit_live_wire_study import StudyEvidenceReader, read_segmented_wire_records

    reader = StudyEvidenceReader()

    def document(name):
        return reader.document(reader.member(directory, name))

    def lines(name, maximum=30000):
        return reader.lines(reader.member(directory, name), maximum_rows=maximum)

    provenance = document("synthetic-provenance.json")
    if provenance["schema"] != "joined-offline-fixture-v2":
        raise ValueError("this reader expects the new synthetic schema; do not rewrite old evidence")
    if provenance["synthetic_provenance"] is not True or any(
        provenance[key] is not False
        for key in (
            "native_estimator_run",
            "force_calls_executed",
            "physical_execution_qualified",
            "whole_study_qualified",
            "live_qualified",
            "fusion_qualified",
        )
    ):
        raise ValueError("synthetic fixture cannot grant actual execution")
    if provenance["physical_state_independent_of_force_commands"] is not True:
        raise ValueError("synthetic fixture cannot claim mechanical consistency")
    session = document("synthetic-wire-session.json")
    context = document("synthetic-context.json")
    retained = read_segmented_wire_records(directory / "wire-segments", session["retention"])
    for identity in retained["members"]:
        reader.files[identity["requested"]] = identity
    clock = session["clock"]
    physical = dict(
        reference=lines("native-reference.jsonl"),
        trace=lines("physics-substeps.jsonl", 50000),
        observations=clock["observations"],
        terminal=document("synthetic-physical-terminal.json"),
        trace_terminal=document("synthetic-trace-terminal.json"),
    )
    sources, payloads = lines("events.jsonl"), {}
    for row in sources:
        if row["kind"] == "info":
            payloads[row["source_sequence"]] = reader.raw(reader.member(directory, row["payload_path"]))
        elif row["kind"] == "rgb":
            raw = reader.raw(reader.member(directory, f"rgb-frames/{row['sample_ns']}.ppm"))
            header = b"P6\n160 120\n255\n"
            if not raw.startswith(header):
                raise ValueError("synthetic image header")
            payloads[row["source_sequence"]] = raw[len(header) :]
    source = dict(
        sources=sources,
        payloads=payloads,
        fanout=lines("source-fanout.jsonl"),
        requests=lines("shadow/native-requests.jsonl"),
        acknowledgements=lines("shadow/native-acks.jsonl"),
        states=lines("shadow/states.jsonl"),
        terminal=document("shadow/shadow-input-result.json"),
        session_id="online-native-322",
    )
    value = dict(
        directory=directory,
        records=retained["records"],
        context=context,
        clock=clock,
        clock_attempts=lines("wire-clock.jsonl"),
        physical=physical,
        source=source,
        fast=dict(
            records=lines("shadow/synthetic-fast-state.jsonl"),
            acknowledgements=source["acknowledgements"],
            end_sim_ns=END,
        ),
        camera=dict(
            sources=sources,
            payloads=payloads,
            manifest=document("camera-info.json"),
            first_payload=reader.raw(reader.member(directory, "camera-info.pb")),
        ),
        health=dict(
            states=source["states"],
            records=lines("shadow/health-evidence.jsonl"),
            terminal=document("shadow/health-result.json"),
            shadow_last=source["terminal"]["health_last"],
            session_id=source["session_id"],
            profile_name="px4-d6f12ad-gate-floor-v1",
        ),
        source_health=dict(
            sources=sources,
            trace=physical["trace"],
            terminal=document("synthetic-source-health.json"),
            capture_start_ns=context["start_ns"],
            watchdog_failure=None,
        ),
        physical_execution_qualified=False,
        provenance=provenance,
    )
    if provenance["synthetic_motion"]:
        anchor = document("shadow/synthetic-readiness-anchor.json")
        value["motion"] = dict(
            anchor=anchor,
            profile=anchor["profile"],
            forces=lines("shadow/synthetic-forces.jsonl"),
            trace=physical["trace"],
            intent_records=lines("shadow/synthetic-motion-intent.jsonl"),
            requests=source["requests"],
            acknowledgements=source["acknowledgements"],
            intent_terminal=document("shadow/synthetic-motion-intent-result.json"),
            motion_terminal=document("shadow/synthetic-motion-result.json"),
            session_id=source["session_id"],
        )
        value["anchor"] = dict(
            anchor=anchor,
            sources=sources,
            fanout=source["fanout"],
            heartbeat_records=lines("shadow/synthetic-heartbeat-observation.jsonl"),
            estimator_records=lines("shadow/estimator-readiness.jsonl"),
            acknowledgements=source["acknowledgements"],
        )
        value["gauge"] = dict(
            states=source["states"],
            reference=physical["reference"],
            policy=document("shadow/synthetic-gauge-policy.json"),
            anchor=anchor,
            motion_profile=anchor["profile"],
            health_terminal=value["health"]["terminal"],
            result=document("shadow/synthetic-capture-result.json"),
        )
    reader.finish()
    value["consumed_files"] = reader.files
    return value
