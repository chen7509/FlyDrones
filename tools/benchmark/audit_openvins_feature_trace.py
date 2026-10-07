import argparse
import json
from pathlib import Path

from tools.benchmark.openvins_feature_trace import audit_fixed_replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", required=True)
    parser.add_argument("--diagnostic", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--patch", required=True)
    parser.add_argument("--library-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit_fixed_replay(
        args.control,
        args.diagnostic,
        diagnostic_binary=args.binary,
        diagnostic_patch=args.patch,
        diagnostic_library_sha256=args.library_sha256,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
