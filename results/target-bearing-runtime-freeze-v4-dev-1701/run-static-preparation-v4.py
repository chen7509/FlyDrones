"""Literal once entry; source creation alone is not an actual attempt."""

import os
import sys

if __name__ == "__main__":
    if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules or sys.argv[1:] != ["--execute-once"]:
        raise SystemExit("production once entry denied before child/output")
    root = __file__.replace("\\", "/").rsplit("/", 3)[0]
    if os.getcwd().replace("\\", "/") != root:
        raise SystemExit("literal current cwd required")
    sys.path[:0] = [root, root + "/src"]
    from tools.benchmark.static_v4_executor import execute_once

    execute_once()
