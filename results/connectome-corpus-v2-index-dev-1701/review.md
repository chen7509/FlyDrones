# Independent read-only review

The reviewer found two repeated-read gaps: sequence manifest and samples could
change between hash verification and `load_sequence`, and receipt JSON was
hashed then separately parsed. Deterministic drift tests failed before the
fix. The parser now hashes the exact receipt/manifest bytes it parses and
checks sequence inputs before and after the existing loader; both tests pass.

The reviewer also found that a receipt attachment could hard-link the world
file or another attachment. A Windows hard-link test reproduced acceptance
before the fix. Receipt attachment uniqueness now compares `(device, inode)`
with all reserved files and prior attachments.

The reviewer noted that pre/post hashes around `load_sequence` do not protect
against deliberate A→B→A swapping while it reopens files. This remains an
explicit limitation of the integrity-only consumer. Its three source/training/
comparison qualification flags stay false, and it cannot provide a dataset
to training. A future trusted producer/eligibility gate must not use this
audit as source authentication.

The planned symlink test is skipped on this Windows host because creating a
symlink is unavailable. Source/teacher label tampering and hard-link reuse
have executable refusal coverage.
