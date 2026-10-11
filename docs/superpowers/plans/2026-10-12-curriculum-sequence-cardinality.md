# Execution plan

1. Add a failing loader test with all declared train seeds present and an
   additional path duplicating one train seed, plus the valid path control.
2. Add an exact one-per-seed check in the full curriculum preflight, before
   parameter or connectome loading.
3. Run the focused test, connectome regression tests, Ruff and diff checks.
4. Record the result and limits; leave the v2 54-job evidence binder as the
   next independent dependency.
