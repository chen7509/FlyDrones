# Supported online VIO: incomplete capture and readiness queue failure

## Outcome
The sole prospective supported-ready-shadow-v1 physical capture failed at pre-step6.417s; server chunk ended6.420s. It is not a25s success or VIO accuracy qualification. Producer262bd44 used exact PR36 online_probe/config and PR43 native reference with PR47 fan-out. No estimator rebuild, noise tuning, training, ODOMETRY, arming or EKF2. All275 selected source/config/model/binary/dependency manifest entries match before/after; copied text entries were additionally checked against their hashes. Workerexit2/capture_failed retained; PX4exit0 and original owned group absent.

## Observations
Readiness selected1.422s and fixed anchor1.622s. Lift and1600 lateral force steps completed;4795support commands ended6.416s. At6.417s the force policy rejected readiness; no subsequent force command is recorded. Fresh reference6416complete cycles plus pending pre6.417s; old trace12833rows. These are incomplete, not25000/50000normal evidence.

Source journal1807rows:1606IMU,65eachRGB/CameraInfo/depth,6unarmed heartbeats. Fan-out1801commits,1partial ShadowInput delivery without readiness commit,5refusals; every receipt identity matched original source. Native1667acks,65images,321fast targets(200success/121unavailable). Native completed the in-progress6.4s image despite gate rejection; this is retained partial delivery, not rolled back.

Readiness checkwall26379186945ns used heartbeatarrival24368055879ns, age2.011131066s beyond unchanged2s threshold. Other source ages remained below2s. A newer unarmed heartbeat arrived26330965388ns (age48.221557ms), but writer journaled it26383439245ns, after rejection, and fan-out refused it after failure. Queue/commit delay was involved in this observed failure. This does not establish that future stalls are harmless or authorize bypassing native/source health. No threshold relaxed; no retry.

## Accuracy and latency limits
41internal states and37public states: initializer reference1.304s; first successful image/state2.4s; first public2.8s. These are distinct times, not initialization compute durations. The prospectively required pre-anchor internal origin does not exist (initialization occurred during lift), so fixed-gauge position/velocity/attitude screens are indeterminate. No favorable later origin substitutes for it.

Exploratory rotation-invariant displacement-norm differences from first internal state2.4s: maximum0.040369875m, terminal0.007435998m at6.4s. These are lower bounds on possible vector error, not upper accuracy bounds or qualification. Full records retained. Sample-bracket raw integration errors are below original.02/.05m/s thresholds (exact values and intervals in audit.json); only the partial supported motion was observed, not a full25s settled trajectory. Initial contact and uncalibrated zero-bias-diffusion assumptions remain.

RGB callback-to-native-processing-end P95=97.736146ms includes downstream queue/processing and excludes pre-callback rendering/transport. It is not full fly-policy latency or a capacity pass. Quality/reset unknown, covariance uncalibrated, fusion=false.

Native camera start-to-end processing P95=3.286467ms, maximum4.670456ms. The difference of percentile values is not itself a queue percentile. The preserved native log has37MSCKF update summaries(24zero-feature),37SLAM summaries(1zero-feature),37delayed-init summaries; per-row counts are in native-log-summary.json. Camera rows have zero latched-ZUPT-true flags; that flag count is not a separately instrumented count of accepted ZUPT updates. No reset/loss fault was deliberately injected in this study; the observed readiness refusal is not evidence of all reset/health paths.

## Cleanup and verification
Independent review found2Important issues and1Minor. The metrics adapter initially accepted10values while the real producer emits16including biases. A real-schema counterexample failed, then strict16value validation fixed it; nonfinite biases are also refused. Noncommuting nonidentity-origin rotation coverage was added (GREEN on existing correct formula, not falsely calledRED). No physical/estimator rerun follows this offline fix.

The275entry freeze is **selected coverage only**, not the spec's full runtime-input invariant. Gazebo simulation/Python binding binaries and PX4rootfs/gz_env.sh/startup scripts were not included in the before manifest. Their historical pre-run hashes cannot be backfilled; complete_runtime_freeze_qualified=false. The prospective launcher metadata also incorrectly inherited wall_budget_s60/supervisor_s90 from a fault launcher; actual non-fault capture and supervisor limits were300/300s, visible in frozen source/supervisor.json. The15.51883s run ended through readiness, not these limits. This is a prospective metadata defect, not a reason to rewrite the old profile. A new study must reconcile configuration and actual enforced limits before launch.

Supervisor7disk events equal in-memory events. Original owned group492/session492/start_ticks1010 retained leader withWNOWAIT, observed zombie only, reaped then confirmed empty. No supervisor group signal; noexecuting andgroupabsent separately checked. No claim about internal individual signals or setsid-escaped descendants. ULogSHAf06c1477173604e80f522ebcf62f90c5ed15023614089eb142d4f9cbb3b27c80,14vehicle_status records allarming_state1;6heartbeats unarmed. Runtime scan empty.

- Verified: synthetic fixed-gauge direction/velocity/drift/refusal tests;102targeted preflight tests; actual causal native processing and partial dual delivery; fresh reference/force refusal; retained ULog/owned-group cleanup;275entry immutability.
- Implemented: offline FixedGauge diagnostics, not applied to qualify this capture because required origin absent.
- Failed: complete25s study, continuous readiness, prospective origin availability. PreviousPR37drift,PR39groundaliasing,PR40startup failures remain separate.
- Not qualified: complete reliable publicVIO, reset/quality/covariance health, EKF2, flight, fly learning speed, fair baseline comparison. Five-camera0.873RTF<0.95 unchanged.

## Research and next dependency
Source decisions and snapshots in results/supported-online-vio-dev-1701/research.md and sources/manifest.json. FixedOpenVINS6948812GPL3 is nonarchived with observed lastpush2025-11-30, not a2026activity claim. Official metrics distinguish ATE/RPE/consistency; this adapter is fixed-first-pose diagnostics, not upstream best-fitATE.

Next: fixed-evidence source-health/clock and queue design, not blind physical rerun. Examine fixed PX4 heartbeat simulated-clock cadence vs real wall delay and journal sequencing. Preserve2s source/native fail-closed contracts; investigate a separately journaled observational health channel with explicit downstream failure gating versus bounded source scheduling. Do not merely move readiness ahead of estimator without preserving failure/force ordering. Independently design an honest motion-origin method when no stationary internal state is available before lift; no Gazebo attitude initialization and no retrospective pass of this capture. Then a separately named prospective study after synthetic concurrency/loss/refusal tests. Do not expand lifecycle governance.

## Final verification
Post-review full regression1021passed,2existing loaderwarnings(240.72s); targeted105passed. Changed-fileRuff and gitdiffcheck pass. Whole-treeRuff52errors/33files identical tobase50a710a; not a full lint pass. Independent review complete; code-schema defect fixed, historic freeze gap explicitly unresolved/false. No physical or native replay after review fixes. Final resource scan empty.

## Publication
Draft PR48 https://github.com/chen7509/FlyDrones/pull/48, stacked onPR47. EvidenceZIP evidence/supported-online-vio-dev-1701.zip:423members,6082887bytes,SHA25607a2a247b87ff43304ec4c0fe787640264772ad12c272b354d5a5116cdecaeb2; allmemberhashes/CRCverified, sibling supervisorjournalincluded. Sealed producer/report snapshot80d5d82; physicalproducer262bd44. Later publication text does not alter sealed inputs.
