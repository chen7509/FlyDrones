"""POSIX setup-failure injection. Starts only disposable sleeping synthetic children."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tools.benchmark.openvins_online_shadow import NativeClient  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    records = []
    for case in ["early_file", "pipe", "post_popen", "session_file", "session_write"]:
        directory = args.output / case
        directory.mkdir()
        if case == "early_file":
            (directory / "native-acks.jsonl").write_text("preserve")
        if case == "session_file":
            (directory / "native-session.json").write_text("preserve")
        children = []
        original_popen = subprocess.Popen

        def spawn(*a, original_popen=original_popen, children=children, **kw):
            p = original_popen(*a, **kw)
            children.append(p)
            return p

        before = set(os.listdir("/proc/self/fd"))
        caught = None
        try:
            with mock.patch("subprocess.Popen", side_effect=spawn):
                if case == "pipe":
                    patch = mock.patch("os.pipe", side_effect=OSError("injected pipe failure"))
                elif case == "post_popen":
                    patch = mock.patch("os.set_blocking", side_effect=OSError("injected blocking setup failure"))
                elif case == "session_write":
                    patch = mock.patch("json.dump", side_effect=OSError("injected metadata write failure"))
                else:
                    patch = mock.patch("os.getpid", wraps=os.getpid)
                with patch:
                    NativeClient([sys.executable, "-c", "import time; time.sleep(30)"], directory)
        except (OSError, ValueError) as exc:
            caught = repr(exc)
        running = [p.pid for p in children if p.poll() is None]
        after = set(os.listdir("/proc/self/fd"))
        records.append(dict(case=case, error=caught, live_children=running, leaked_descriptors=sorted(after - before)))
        # Test harness contains the original bug's child, retaining failure evidence.
        for p in children:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=3)
            if p.stdin:
                p.stdin.close()
    with (args.output / "summary.json").open("x") as f:
        json.dump(records, f, indent=2)
    print(json.dumps(records, indent=2))
    assert all(r["error"] and not r["live_children"] and not r["leaked_descriptors"] for r in records), (
        "setup cleanup contract failed"
    )


if __name__ == "__main__":
    main()
