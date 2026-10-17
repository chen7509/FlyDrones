"""Full prospective storage quotas using synthetic records and temporary files.

Keeps results/hashes and generator identity; temporary bulk payload is disposable
unit-test data, not physical/capture evidence. Never invokes network or PX4.
"""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from tools.benchmark.openvins_segmented_journal import SegmentedWireJournal


def verify_members(evidence):
    total = 0
    for member in evidence['segments']:
        file = Path(evidence['directory']) / member['name']
        assert file.stat().st_size == member['bytes']
        with file.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == member['sha256']
        count = 0
        with file.open('r', encoding='ascii') as stream:
            for line in stream:
                row = json.loads(line)
                assert row['index'] == total
                assert row['source_index'] == total
                assert row['source'] == 'wire'
                total += 1
                count += 1
        assert count == member['records']
    assert total == evidence['records']


def run(output):
    output.mkdir(parents=False, exist_ok=False)
    source = Path(__file__).resolve()
    production = source.parents[2] / 'tools/benchmark/openvins_segmented_journal.py'
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, production)}
    results = []
    for mode in ('segments', 'bytes'):
        with tempfile.TemporaryDirectory(prefix='flydrones-segmented-capacity-') as root:
            store = SegmentedWireJournal(Path(root) / 'records')
            log = store.channel('wire')
            count = 524288 if mode == 'segments' else 511
            payload = {'kind': 'synthetic-capacity'} if mode == 'segments' else {'kind': 'synthetic-capacity', 'raw': 'x' * 1048576}
            for _ in range(count):
                log.append(payload)
            try:
                log.append(payload)
            except ValueError as exc:
                refusal = str(exc)
            else:
                raise AssertionError('full prospective quota was not enforced')
            store.close()
            evidence = store.evidence
            assert evidence['records'] == count
            assert evidence['failure'] and not evidence['complete_retention']
            assert evidence['bytes'] <= 536870912
            assert not evidence['unsealed']
            assert len(evidence['segments']) == (64 if mode == 'segments' else 1)
            verify_members(evidence)
            result = dict(mode=mode, refusal=refusal, evidence=evidence,
                          all_member_hashes_indices_verified=True, synthetic=True,
                          bulk_temporary_files_retained=False, physical=False)
            (output / f'{mode}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            results.append(dict(mode=mode, records=count, bytes=evidence['bytes'], segments=len(evidence['segments'])))
            print(results[-1], flush=True)
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, production)}
    assert hashes == after
    (output / 'summary.json').write_text(json.dumps(dict(before=hashes, after=after, unchanged=True, results=results),
                                                   indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
