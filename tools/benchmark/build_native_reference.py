"""Build the diagnostic bridge without changing simulator installation."""

import argparse
import hashlib
import json
import subprocess
import sysconfig
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
p.add_argument("--testing", action="store_true")
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
source = Path(__file__).with_name("native_reference_probe.cc")
name = "_fly_native_reference_test" if a.testing else "_fly_native_reference"
binary = a.output / (name + sysconfig.get_config_var("EXT_SUFFIX"))
flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "gz-sim8"], text=True).split()
includes = subprocess.check_output(["python3-config", "--includes"], text=True).split()
cmd = ["g++", "-std=c++17", "-O1", "-shared", "-fPIC", str(source), "-o", str(binary), *includes, *flags]
if a.testing:
    cmd.insert(1, "-DFLY_REFERENCE_TESTING")
r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
result = dict(
    command=cmd,
    exit=r.returncode,
    stdout=r.stdout,
    stderr=r.stderr,
    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    testing=a.testing,
)
if r.returncode == 0:
    result.update(binary=str(binary.resolve()), binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
(a.output / "build.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result))
raise SystemExit(r.returncode)
