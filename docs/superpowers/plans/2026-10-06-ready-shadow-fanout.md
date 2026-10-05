# Ready/shadow fan-out plan

Base d880a11; existing isolated worktree, branch codex/ready-shadow-fanout. Inline implementation under standing authorization.

1. Research pinned source/docs/paper and save provenance. Implement tested ReadyShadowFanout with strict source validation, ordered consumer receipt and failure-latched gate. Write failing tests before code.
2. Wire opt-in writer sequence and explicit CLI composition; pre-step wrapper and terminal evidence. Preserve old modes, truth isolation and single native worker. Test source/consumer failures, file lifecycle, locks/races, cleanup and CLI.
3. Freeze producer and run fixed PR43 source-only adapter exercise once with actual ShadowInput/CausalInput and a packet-recording sink (no estimator or simulation), including all input identities and incomplete final frame. Keep replay clock explicit. Run targeted and full regression.
4. One independent read-only whole-branch review; Important fixes in one TDD pass. Report implemented/verified/untested/failed; seal evidence and draft PR stacked on PR46. Prepare next online frozen study, no blind physical replay.

Review focus: readiness cannot qualify a partially delivered/failed record; hidden ShadowInput.failure; mutable cross-consumer copies; source sequence evidence tied to raw journal; lock ordering and timeout semantics; pre-step race wording versus implementation; errors in partial fan-out/close must remain visible; single native worker and truth exclusion; fixed replay is not native estimator/online latency.
