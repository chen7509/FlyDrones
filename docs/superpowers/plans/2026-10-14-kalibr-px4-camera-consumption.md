# Kalibr/PX4 camera consumer implementation plan

Execute inline under the user's autonomous production-interface authorization. Spec: ../specs/2026-10-14-kalibr-px4-camera-consumption.md. Existing worktree/branch; personal/PR65 only.

- [x] Read actual source/rig/native configuration paths, current reports/roadmap/failures, upstream Kalibr/OpenVINS conventions/license/pin, available toolchain/actual resource/process evidence; select operational artifact application rather than repeated exporters/probes.
- [x] Write behavioral REDs for missing artifact consumer, inverse/noncommuting transform and projection, signed/quantized timestamp state selection, original and shifted health refusal; implement bounded byte-bound consumer.
- [x] Integrate into Px4UlogCameraSource.produce and existing CLI as declared opt-in with preserved input snapshots/old defaults and no qualifier promotion. Verify actual producer/CLI behavior using clearly constructed protocol fixtures; no previous actual study dispatch.
- [x] Necessary adjacent tests/Ruff/diff, independent read-only code review, behavior RED/GREEN repairs, explicit no measured-artifact/native/PX4 execution claim.
- [ ] Preserve failures, report/byte-seal/CRC/hash independent audit, commit/push personal and precise PR65 head/body check. Distinguish prepublication plan from later ledger. Genuine own-rig spatial/time measurement and physical association remain pending.
