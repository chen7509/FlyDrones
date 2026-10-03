# Fix UDP stress start publication race

1. Save the full-suite failure evidence: `agent-0.json` and `agent-3.json`
   showed `JSONDecodeError` at zero packets; the targeted retry passed.
   Inspect worker and parent synchronization before changing code.
2. Add a deterministic test that blocks the publisher after writing the
   temporary file. Require final `start.json` to stay absent until release,
   then contain parseable JSON with the expected timestamp. Run the new test
   red against the existing implementation.
3. Implement a small atomic start-signal publisher in
   `src/flydrones/distributed_stress.py`: write in the same directory and
   call `os.replace` after close. Keep worker synchronization and all trial
   settings unchanged.
4. Run the deterministic test, repeated four-process trials, Ruff,
   `git diff --check` and full `pytest -q` with this worktree's `src` on
   `PYTHONPATH`. Report any remaining failures rather than assuming the race
   is fixed from one successful run. Commit and request independent review.
