"""Bind saved actual observations and declare static completeness limits; no Linux or native execution."""

import collections
import hashlib
import json
from pathlib import Path
import re
import static_elf

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
static_elf.ROOT=ROOT
LINUX_ROOT='/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility'


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save(name,value):
    with (OUT/'final-v2'/name).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,indent=2);f.write('\n')


refs=load(OUT/'combined-pin-references-after-frontier.json')['files']
r=load(OUT/'cache-libraries/collection-result.json')
assert r['collection_complete'] and len(r['observed_files'])==4
for row in r['observed_files']:
    refs[row['path']]=dict(pin={k:row[k] for k in ('path','resolved','bytes','sha256')},
                         phase=(OUT/'cache-libraries').relative_to(ROOT).as_posix(),blob=row['blob'])
for extra_phase in ('cache-audit-library','cache-capng-library','native-toolchain-observation'):
    extra=load(OUT/extra_phase/'collection-result.json')
    assert extra['collection_complete'] and not extra['errors']
    for row in extra['observed_files']:
        refs[row['path']]=dict(pin={k:row[k] for k in ('path','resolved','bytes','sha256')},
            phase=(OUT/extra_phase).relative_to(ROOT).as_posix(),blob=row['blob'])
byend={v['pin']['resolved']:v for v in refs.values()}
names=collections.defaultdict(set)
for path,rec in refs.items():
    names[Path(path).name].add(rec['pin']['resolved'])
    names[Path(rec['pin']['resolved']).name].add(rec['pin']['resolved'])
elfs={}
for path,rec in byend.items():
    if path.startswith(('/usr/bin/','/usr/libexec/')) or '.so' in Path(path).name or path.endswith('.o'):
        obs=static_elf.elf(path,rec)
        if obs:
            elfs[path]=obs
            if obs.get('soname'):names[obs['soname']].add(path)
missing=collections.defaultdict(list)
edges=[]
for path,obs in elfs.items():
    for name in obs.get('needed',[]):
        candidates=sorted(names[name])
        edges.append(dict(consumer=path,needed=name,observed_candidate_endpoints=candidates,
                          actual_loader_choice_proven=False))
        if not candidates:missing[name].append(path)
save('static-elf-closure.json',dict(files=elfs,needed_edges=edges,unbound_needed_names=dict(missing),
    every_observed_needed_name_has_candidate=not missing,actual_loader_choices_proven=False,
    symbol_versions_or_abi_verified=False,recursive_lazy_loaded_closure_verified=False,
    old_library_or_new_build_outputs_examined=False))

groups={k:[] for k in ('tools','system_headers','cmake_modules','link_implicit','libraries','packages')}
link_scripts=[]
for path in sorted(refs):
    name=Path(path).name
    if path.startswith(('/usr/bin/','/usr/libexec/')):
        groups['tools'].append(path)
    if path.startswith('/usr/include/') or '/include/' in path and path.startswith('/usr/lib/gcc/'):
        groups['system_headers'].append(path)
    if name.endswith('.cmake'):
        groups['cmake_modules'].append(path)
    if name.endswith(('.o','.a','.specs')) or name=='specs' or path.startswith('/etc/ld.so'):
        groups['link_implicit'].append(path)
    if path.startswith('/var/lib/dpkg/') or path=='/usr/lib/os-release':
        groups['packages'].append(path)
    if '.so' in name:
        rec=refs[path]
        if rec['pin']['resolved'] in elfs:
            groups['libraries'].append(path)
        else:
            # A linker script is an input, not an ELF library or ABI receipt.
            raw=(ROOT/rec['phase']/rec['blob']).read_bytes()
            if b'GNU ld script' in raw[:256] or b'GROUP' in raw[:512] or b'INPUT' in raw[:512]:
                groups['link_implicit'].append(path)
                paths=re.findall(r'/[A-Za-z0-9_+./:-]+',raw.decode('utf-8',errors='strict'))
                link_scripts.append(dict(path=path,absolute_references=paths,
                    unbound_exact_references=[p for p in paths if p not in refs and p not in byend],
                    actual_linker_search_selection_proven=False))
for key in groups:
    groups[key]=sorted(set(groups[key]))
assert all(groups.values())
save('linker-script-relations.json',dict(scripts=link_scripts,absolute_paths_only_not_full_grammar=True,
                                        compiler_builtin_specs_and_implicit_search_execution_proven=False))
graph=load(OUT/'source-graph.json')
save('header-package-manifest.json',dict(schema='native-offset-build-input-closure-v1',groups=groups,
    observation_refs='input-pin-references.json',all_named_group_entries_have_actual_saved_pins=True,
    static_named_candidate_set_complete=True,full_input_closure_complete=False,
    actual_build_consumption_proven=False,actual_recursive_loader_closure_proven=False,
    signed_package_origin_authenticated=False,generated_new_build_inputs_not_fabricated=True,
    current_header_search_for_new35_tus_proven=False,all_qualifications=False,dispatchable=False))

tools=['/usr/bin/cmake','/usr/bin/x86_64-linux-gnu-g++-13','/usr/bin/make',
       '/usr/bin/x86_64-linux-gnu-ar','/usr/bin/x86_64-linux-gnu-ranlib',
       '/usr/bin/x86_64-linux-gnu-ld.bfd','/usr/bin/x86_64-linux-gnu-as',
       '/usr/bin/python3.12','/usr/bin/env','/usr/bin/time','/usr/bin/timeout',
       '/usr/bin/systemd-run','/usr/bin/systemctl']
assert all(path in refs for path in tools)
variant=OUT/'toolchain-native.cmake'
variant_bytes=variant.read_bytes()
variant_path=LINUX_ROOT+'/'+variant.relative_to(ROOT).as_posix()
variant_pin=dict(path=variant_path,resolved=variant_path,bytes=len(variant_bytes),
                 sha256=hashlib.sha256(variant_bytes).hexdigest())
save('toolchain-receipt.json',dict(schema='native-linux-toolchain-declaration-receipt-v1',
    source_head='68c648e12f6850abbfde30441f9dfd43d36dcaef',toolchain_file=variant_path,
    prepared_file_pin=variant_pin,toolchain_file_linux_readback_pending=False,
    toolchain_file_actual_linux_pin=refs[variant_path]['pin'],
    earlier_draft_observed_but_not_selected=load(OUT/'observed-toolchain-pin.json'),
    tool_files={path:refs[path] for path in tools},sysroot='/',
    declared_search_prefixes=['/usr'],ignored_search_prefixes=['/usr/local','/opt'],
    user_and_system_package_registries=False,cmake_or_compiler_executed=False,
    try_compile_not_bypassed=True,driver_builtin_specs_consumption_proven=False,
    static_elf_needed_name_candidates_complete=not missing,full_sysroot_contents_bound=False,
    abi_verified=False,admission_granted=False,all_qualifications=False,dispatchable=False))
save('input-pin-references.json',dict(files=refs,cross_time_observations=True,
                                    no_future_fresh_continuity_proof=True,admitted=False))
save('binding-candidates.json',dict(schema='production-build-binding-candidates-v1',
    request_schema='native-offset-fresh-source-request-v1',
    bindings=dict(deployed_repo=LINUX_ROOT,
        upstream_source_tree='/home/yuchen7509/flydrones-upstream/open_vins',
        capture_script=LINUX_ROOT+'/tools/benchmark/capture_disarmed_sensors.py',
        pinned_cmake='/usr/bin/cmake',pinned_gxx='/usr/bin/x86_64-linux-gnu-g++-13',
        pinned_make='/usr/bin/make',pinned_python='/usr/bin/python3.12',
        current_linux_source_manifest=LINUX_ROOT+'/'+(OUT/'current-linux-source-manifest.json').relative_to(ROOT).as_posix(),
        toolchain_file=variant_path,
        toolchain_receipt=LINUX_ROOT+'/'+(OUT/'final-v2/toolchain-receipt.json').relative_to(ROOT).as_posix(),
        header_package_manifest=LINUX_ROOT+'/'+(OUT/'final-v2/header-package-manifest.json').relative_to(ROOT).as_posix(),
        eigen_config_dir='/usr/share/eigen3/cmake',opencv4_config_dir='/usr/lib/x86_64-linux-gnu/cmake/opencv4',
        boost_config_dir='/usr/lib/x86_64-linux-gnu/cmake/Boost-1.83.0',ceres_config_dir='/usr/lib/x86_64-linux-gnu/cmake/Ceres',
        exclusive_build_dir=LINUX_ROOT+'/results/native-offset-once-attempt-v1/build/artifacts'),
    exclusive_build_dir_not_created_or_probed=True,production_templates_unmodified=True,
    source12_and_static128_observed=True,new_receipt_readback_pending=True,
    full_request_complete=False,admission_granted=False,dispatchable=False))
save('missing-evidence.json',dict(schema='production-toolchain-input-frontier-v1',
    linux_production_source_binding='128 observed files; required12 covered; static local graph only',
    toolchain='native declaration with13 observed tool refs and actual Linux toolchain-file readback; receipt-file readback pending',
    named_group_entries={key:len(value) for key,value in groups.items()},
    static_elf_files=len(elfs),needed_edges=len(edges),needed_names_without_observed_candidates=dict(missing),
    actual_consumption_and_completeness_blockers=[
        'New35-TU actual system depfiles, selected compiler builtins/specs/search inputs and actual CMake trace/config selections do not exist before a separately admitted build.',
        'Loader cache path strings and ELF SONAME candidates are not actual context/hwcaps/search/symbol-version/lazy-loaded maps proof; no native program was run.',
        'ld.so.conf include glob directory was not enumerated; only indexed exact loader configuration files were observed.',
        'Static Python local graph has2 dynamic-loading sites and external module names; complete runtime Python/SDK/FFI inputs are not authenticated.',
        'Observed package status/list/md5 bytes do not authenticate signed origin or establish an atomic/future-fresh environment.'],
    dynamic_import_sites=graph['dynamic_import_sites'],external_module_names=graph['external_module_names'],
    full_input_closure_complete=False,fresh_build_admission_granted=False,
    resource_cgroup_pidfd_gates_not_refreshed=True,old_library_history_unknown=True,
    all_qualifications=False,dispatchable=False))
print(json.dumps(dict(bound_refs=len(refs),groups={k:len(v) for k,v in groups.items()},
    elf_files=len(elfs),needed_edges=len(edges),unbound_needed_names=list(missing),
    tool_refs=13,source_files=128,full_input_closure_complete=False)))
