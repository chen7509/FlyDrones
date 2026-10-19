"""Analyze only this new exact-two result plus prior saved JSON fields; no Linux access."""

import ast
import collections
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(name, value):
    with (OUT/name).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


selection = load(OUT/'selection.json')
result = load(OUT/'collection-result.json')
prior = load(ROOT/'results/native-linux-required-input-refresh-20261019/source-coverage.json')
metadata = (OUT/'metadata.jsonl').read_bytes()
rows = [json.loads(raw) for raw in metadata.splitlines()]
counts = dict(collections.Counter(row['type'] for row in rows))
assert len(rows) == 14
# There are six per-file records plus one start/completion pair.
assert counts == dict(start=1, identity=2, create_intent=2, created=2, write_complete=2, begin=2, end=2, completion=1)
assert result['collection_complete'] and not result['errors'] and result['readers_closed']
assert result['exit'] == 0 and not result['outer_exceeded'] and result['active_partial'] is None
assert result['stream_payload_bytes'] == 48249
assert result['stream_metadata_bytes'] + len(rows) == len(metadata)
assert result['linux_completion']['target_bytes_written'] == 48249
assert result['linux_completion']['created_paths'] == selection['allowed_content_endpoints']
assert result['linux_completion']['completed_files'] == 2
submitted = (OUT/'submitted-script.py').read_bytes()
start = load(OUT/'start.json')
assert hashlib.sha256(submitted).hexdigest() == start['script_sha256']
assert len(submitted) == start['script_bytes']
files, pins = {}, {}
for item, actual in zip(selection['selected'], result['observed_files'], strict=True):
    path = item['path']
    assert actual['path'] == actual['resolved'] == path
    assert actual['stable'] and actual['matches_fixed_manifest']
    assert actual['prior_target'] is None
    assert actual['action'] == 'created_from_verified_retained_bytes'
    assert actual['before'] == actual['after']
    assert actual['bytes'] == item['expected_bytes']
    assert actual['sha256'] == item['expected_sha256']
    assert actual['git_blob_sha1'] == item['expected_git_blob_sha1']
    payload = (OUT/actual['blob']).read_bytes()
    assert len(payload) == actual['bytes'] and hashlib.sha256(payload).hexdigest() == actual['sha256']
    assert hashlib.sha1(b'blob '+str(len(payload)).encode()+b'\0'+payload).hexdigest() == actual['git_blob_sha1']
    pin = dict(path=path, resolved=path, bytes=actual['bytes'], sha256=actual['sha256'])
    pins[path] = pin
    files[path] = dict(file_pin=pin, before=actual['before'], after=actual['after'],
                       actual_action=actual['action'], prior_target=None, blob=actual['blob'],
                       fixed_git_blob_sha1=actual['git_blob_sha1'], stable=True, admitted=False)
assert set(files) == set(selection['allowed_content_endpoints'])
save('file-bindings.json', dict(schema='exact-two-restored-file-bindings-v1',files=files,
                               acquisition_time_only=True, admitted=False))
save('new-file-pins.json', dict(schema='exact-two-restored-current-content-pins-v1',files=pins,
                               future_fresh_continuity_proven=False, admitted=False))
coverage = dict(schema='fixed-upstream-cross-time-content-coverage-v1',
                commit='69488123ed9362dd44b6f28e7f4680abbff1442b',required_files=143,
                earlier_actual141=dict(phase='results/native-linux-required-input-refresh-20261019',
                                       count=prior['actual_current_refreshed'],matches=prior['matches_fixed_manifest_fields'],
                                       earlier_payload_not_rehashed=True,not_refreshed_this_selection=True),
                new_actual2=dict(phase=OUT.name,files=pins),
                observed_content_entries_across_phases=143, missing_entries_across_these_phases=[],
                all143_observed_at_same_time=False, earlier141_currently_revalidated=False,
                actual_build_consumption_proven=False, old_library_history_proven=False,
                full_build_stage_complete=False, dispatchable=False)
assert coverage['earlier_actual141']['count'] == coverage['earlier_actual141']['matches'] == 141
assert set(prior['missing_current_payload_paths']) == set(pins)
save('source-coverage.json',coverage)
save('missing-evidence.json',dict(schema='remaining-build-frontier-after-exact-two-v1',
    selected_two_restoration_complete=True,
    fixed143_content_observations='143 across phases; not an atomic or future-fresh snapshot',
    build_stage_blockers=[
        'Current Linux deployed production/capture source manifest and bindings',
        'Explicit current bound toolchain_file/toolchain_receipt',
        'Complete current named header/package/config/implicit link/recursive loader inputs',
        'Fresh separate once-build admission under original resource/no-competition/cgroup/pidfd/budget/cleanup gates'],
    post_build_pre_run_requirements=[
        'Actual successful new library and adapter build receipts plus owned inside/host release',
        'Actual new library/adapter ABI and recursive/lazy loaded closure',
        'Measured calibration/noise and source/clock/runtime/wire bindings',
        'Separate applicable run admission; no automatic build-to-run'],
    no_current_source_manifest_or_request_fabricated=True, old_library_history_unknown=True,
    all_qualifications=False, dispatchable=False))
save('analysis-summary.json',dict(schema='exact-two-restoration-summary-v1',
    human_authorization='允许精确两份条件恢复及回读', exact_selection_complete=True,
    actual_created_files=2,existing_targets_overwritten=0,target_bytes_written=48249,
    full_stable_readbacks=2,readback_bytes=48249,partial_files=0,errors=result['errors'],
    parent_elapsed_s=result['elapsed_s'],linux_elapsed_s=result['linux_completion']['elapsed_s'],
    exit=result['exit'],readers_closed=result['readers_closed'],
    metadata_body_bytes=result['stream_metadata_bytes'],metadata_rows=len(rows),
    metadata_jsonl_bytes=len(metadata),metadata_counts=counts,stderr_bytes=result['stderr_bytes'],
    submitted_script_bytes=len(submitted),copy_input_payloads_verified_only=2,
    prior_payload_archive_audit=False, prior141_not_recollected=True,
    source_coverage_across_phases=143,atomic_snapshot=False,
    compile_native_resources_or_sdk=False, no_linux_writes_except_two_targets=True,
    first_stage_complete=False,all_qualifications=False,dispatchable=False))
for name in ('linux_restore.py','run_once.py','analyze_saved.py'):
    ast.parse((OUT/name).read_text(encoding='utf-8'),filename=name)
print(json.dumps(dict(created=2,stable_readbacks=2,bytes=48249,metadata_rows=len(rows),
                      metadata_body_bytes=result['stream_metadata_bytes'],metadata_jsonl_bytes=len(metadata),
                      parent_s=result['elapsed_s'],linux_s=result['linux_completion']['elapsed_s'],
                      cross_time_source_entries=143,first_stage_complete=False)))
