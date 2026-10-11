"""Freeze committed source bytes for the one-off v12 offline preparer."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    if git("status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("tracked worktree is not clean")
    head = git("rev-parse", "HEAD").decode().strip()
    if len(head) != 40:
        raise ValueError("unexpected Git commit identity")
    source = {}
    for raw in git("ls-files", "-z", "*.py").split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8").replace("\\", "/")
        if relative.startswith(("src/", "tools/")):
            source[relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    preparer = HERE / "prepare-v12.py"
    doc = dict(head=head, tracked_worktree_clean=True,
               preparer_sha256=hashlib.sha256(preparer.read_bytes()).hexdigest(),
               source_sha256=source)
    path = HERE / "committed-source-v12.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(doc, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(path, len(source))


if __name__ == "__main__":
    main()
