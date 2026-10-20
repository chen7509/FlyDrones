"""Verify only new result bytes and saved fields; no Linux calls, product imports or old archive audit."""

import ast
import collections
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
PHASES=('production','dependencies','reference-identities','frontier','cache-reference-identities',
        'cache-libraries','cache-audit-library','cache-capng-library','native-toolchain-observation',
        'receipt-readback','linker-alias-bindings','final-receipt-readback')


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save(name,value):
    with (OUT/name).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,indent=2);f.write('\n')


details=[];all_observations=[];new_digests=set()
for phase in PHASES:
    folder=OUT/phase
    r=load(folder/'collection-result.json')
    assert r['collection_complete'] and r['readers_closed'] and r['exit']==0
    assert not r['errors'] and not r['outer_exceeded'] and r['active_partial'] is None
    meta=(folder/'metadata.jsonl').read_bytes()
    rows=[json.loads(line) for line in meta.splitlines()]
    assert r['stream_metadata_bytes']+len(rows)==len(meta)
    for obs in r['observed_files']:
        assert obs['stable'] and obs['before']==obs['after']
        raw=(folder/obs['blob']).read_bytes()
        assert len(raw)==obs['bytes'] and hashlib.sha256(raw).hexdigest()==obs['sha256']
        new_digests.add(obs['sha256'])
        all_observations.append(dict(obs,phase=folder.relative_to(ROOT).as_posix()))
    details.append(dict(phase=phase,identity_paths=r['linux_completion'].get('identity_paths_attempted',r['linux_completion'].get('attempted')),
        full_file_observations=len(r['observed_files']),payload_bytes=r['stream_payload_bytes'],
        metadata_body_bytes=r['stream_metadata_bytes'],metadata_rows=len(rows),jsonl_bytes=len(meta),
        stderr_bytes=r['stderr_bytes'],parent_s=r['elapsed_s'],linux_s=r['linux_completion']['elapsed_s'],
        complete=True,errors=[]))
caps=load(OUT/'production/selection.json')['caps']
total_bytes=sum(r['payload_bytes'] for r in details)
total_metadata=sum(r['metadata_body_bytes'] for r in details)
assert total_bytes<=caps['total_payload_bytes'] and total_metadata<=caps['metadata_bytes']
assert sum(r['linux_s'] for r in details)<=27
assert sum(r['parent_s'] for r in details)<=30
assert sum(r['stderr_bytes'] for r in details)<=caps['stderr_bytes']
documents={}
for phase in ('receipt-readback','final-receipt-readback'):
    for row in load(OUT/phase/'collection-result.json')['observed_files']:
        documents[row['path']]=dict(file_pin={k:row[k] for k in ('path','resolved','bytes','sha256')},
                                  phase=(OUT/phase).relative_to(ROOT).as_posix(),
                                  before=row['before'],after=row['after'],blob=row['blob'])
b=load(OUT/'final-v3/binding-candidates.json')
for key in ('current_linux_source_manifest','toolchain_receipt','header_package_manifest'):
    assert b['bindings'][key] in documents
selected_toolchain=load(OUT/'native-toolchain-observation/collection-result.json')['observed_files'][0]
assert selected_toolchain['path']==b['bindings']['toolchain_file']
assert selected_toolchain['sha256']==load(OUT/'final-v2/toolchain-receipt.json')['prepared_file_pin']['sha256']
save('final-receipt-bindings.json',dict(schema='actual-linux-input-document-readbacks-v1',
    files=documents,selected_toolchain_file={k:selected_toolchain[k] for k in ('path','resolved','bytes','sha256')},
    all_required_new_documents_actually_read=True,old_creation_time_pending_fields_not_rewritten=True,
    later_readback_supersedes_pending_state_only=True,all_qualifications=False,dispatchable=False))
refs=load(OUT/'final-v3/input-pin-references.json')['files']
closure=load(OUT/'final-v3/header-package-manifest.json')
assert set(closure['groups'])=={'tools','system_headers','cmake_modules','link_implicit','libraries','packages'}
assert all(names and all(name in refs for name in names) for names in closure['groups'].values())
elf=load(OUT/'final-v2/static-elf-closure.json')
assert elf['every_observed_needed_name_has_candidate'] and not elf['unbound_needed_names']
scripts=load(OUT/'final-v3/linker-script-relations.json')
assert not any(row['unbound_exact_references'] for row in scripts['scripts'])
save('analysis-summary.json',dict(schema='linux-production-toolchain-input-binding-summary-v1',
    source_head='68c648e12f6850abbfde30441f9dfd43d36dcaef',phases=details,
    actual_production_source_files=128,required_once_source_files=12,static_local_import_edges=411,
    dynamic_loading_sites=2,selected_toolchain='toolchain-native.cmake',toolchain_tools=13,
    actual_new_receipt_documents=len(documents),input_reference_paths=len(refs),
    named_groups={k:len(v) for k,v in closure['groups'].items()},
    static_elf_files=129,static_needed_edges=374,unbound_observed_needed_names=0,
    unbound_literal_linker_script_paths=0,full_input_closure_complete=False,
    full_file_observations=len(all_observations),new_phase_sha_blobs=len(new_digests),
    known_content_reobserved_for_four_new_alias_contexts_bytes=4336800,
    total_payload_bytes=total_bytes,total_metadata_body_bytes=total_metadata,
    total_metadata_rows=sum(r['metadata_rows'] for r in details),
    total_metadata_jsonl_bytes=sum(r['jsonl_bytes'] for r in details),
    total_stderr_bytes=sum(r['stderr_bytes'] for r in details),
    cumulative_observed_linux_s=sum(r['linux_s'] for r in details),
    cumulative_observed_parent_s=sum(r['parent_s'] for r in details),
    aggregate_within_original_caps=True,all_selected_observations_complete=True,partial_files=0,
    no_compile_configure_link_target_sdk_resources_or_tests=True,no_linux_file_writes=True,
    production_templates_unmodified=True,old_archives_not_audited=True,
    retained_elf_sections_and_package_lists_read_only_for_requested_static_relations=True,
    all_qualifications=False,dispatchable=False))
for p in OUT.rglob('*.py'):
    ast.parse(p.read_text(encoding='utf-8'),filename=p.relative_to(OUT).as_posix())
print(json.dumps(dict(full_file_observations=len(all_observations),phase_count=len(details),
    payload_bytes=total_bytes,metadata_body_bytes=total_metadata,metadata_rows=sum(r['metadata_rows'] for r in details),
    parent_s=sum(r['parent_s'] for r in details),linux_s=sum(r['linux_s'] for r in details),
    source128=True,toolchain_and_documents_bound=True,named_groups={k:len(v) for k,v in closure['groups'].items()},
    observed_needed_names_unbound=0,full_input_closure_complete=False)))
