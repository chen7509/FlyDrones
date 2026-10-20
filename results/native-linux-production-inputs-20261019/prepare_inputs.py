"""Prepare exact current-source and dependency observations; no product imports or Linux invocation."""

import ast
import collections
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
LINUX_ROOT = '/mnt/c/Users/yuche/.codex/worktrees/FlyDrones/track-eligibility'


def load(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


old = load('results/native-linux-fresh-input-bindings-20261019/file-observations.json')['files']
recent = {}
for path,row in old.items():
    pin = row.get('native_current_content_pin')
    if pin:
        recent[path] = dict(pin=pin,phase='results/native-linux-fresh-input-bindings-20261019',blob=row['new_blob'])
for phase in ('native-linux-compiler-five-20261019','native-linux-build-headers-20261019',
              'native-linux-required-input-refresh-20261019','native-linux-missing-source-two-20261019'):
    for path,pin in load('results/'+phase+'/new-file-pins.json')['files'].items():
        recent[path] = dict(pin=pin,phase='results/'+phase,blob='blobs/'+pin['sha256'])
recent_endpoints = {row['pin']['resolved']:row for row in recent.values()}

# Static local graph; imports are parsed, never executed. Include current production roots and new once chain.
roots = set(load('results/native-offset-run-plan-20261018/current-source-manifest.json')['selected_roots'])
once = ast.parse((ROOT/'tools/benchmark/native_offset_once.py').read_bytes())
for node in once.body:
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_NAMES' for t in node.targets):
        roots.update('tools/benchmark/'+name for name in ast.literal_eval(node.value))
roots.add('tools/benchmark/native_offset_reset_v2/CMakeLists.txt')


def local_module(module):
    if not module or module.split('.')[0] not in ('tools','flydrones'):
        return None
    base=ROOT/('src/' if module.startswith('flydrones') else '')/module.replace('.','/')
    for path in (base.with_suffix('.py'),base/'__init__.py'):
        if path.is_file():
            return path.relative_to(ROOT).as_posix()
    return None


pending=set(roots)
files,edges,dynamic,external={ },[],[],set()
while pending:
    name=min(pending);pending.remove(name)
    if name in files:
        continue
    path=ROOT/name
    raw=path.read_bytes()
    files[name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    if path.suffix!='.py':
        continue
    tree=ast.parse(raw,filename=name)
    module=name.removeprefix('src/').removesuffix('.py').replace('/','.')
    package=module.rsplit('.',1)[0]
    for node in ast.walk(tree):
        targets=[]
        if isinstance(node,ast.Import):
            targets=[a.name for a in node.names]
        elif isinstance(node,ast.ImportFrom):
            prefix=node.module or ''
            if node.level:
                parents=package.split('.')
                prefix='.'.join(parents[:len(parents)-node.level+1]+([prefix] if prefix else []))
            targets=[prefix]+[prefix+'.'+a.name for a in node.names if a.name!='*']
        elif isinstance(node,ast.Call) and isinstance(node.func,(ast.Name,ast.Attribute)):
            if ast.unparse(node.func) in ('__import__','importlib.import_module','import_module',
                                         'spec_from_file_location','importlib.util.spec_from_file_location'):
                dynamic.append(dict(file=name,line=node.lineno,expression=ast.unparse(node)[:500]))
        for target in targets:
            if not target:
                continue
            if target.split('.')[0] not in ('tools','flydrones'):
                external.add(target.split('.')[0]);continue
            resolved=local_module(target)
            if resolved:
                edges.append(dict(source=name,line=node.lineno,module=target,path=resolved))
                pending.add(resolved)
                for index in range(1,len(target.split('.'))):
                    parent=local_module('.'.join(target.split('.')[:index]))
                    if parent:
                        pending.add(parent)
assert len(files)<512
save(OUT/'source-graph.json',dict(roots=sorted(roots),files=files,static_import_edges=edges,
                                dynamic_import_sites=dynamic,external_module_names=sorted(external),
                                only_static_local_graph=True,full_runtime_python_closure=False))
toolchain='''# Declared input only: not configured/compiled/executed by this phase.
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_CXX_COMPILER "/usr/bin/x86_64-linux-gnu-g++-13" CACHE FILEPATH "Pinned C++ driver" FORCE)
set(CMAKE_MAKE_PROGRAM "/usr/bin/make" CACHE FILEPATH "Pinned make" FORCE)
set(CMAKE_AR "/usr/bin/x86_64-linux-gnu-ar" CACHE FILEPATH "Declared ar" FORCE)
set(CMAKE_RANLIB "/usr/bin/x86_64-linux-gnu-ranlib" CACHE FILEPATH "Declared ranlib" FORCE)
set(CMAKE_LINKER "/usr/bin/x86_64-linux-gnu-ld.bfd" CACHE FILEPATH "Declared linker; driver consumption unproven" FORCE)
set(CMAKE_SYSROOT "/")
set(CMAKE_FIND_ROOT_PATH "/")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
set(CMAKE_SYSTEM_PREFIX_PATH "/usr")
set(CMAKE_PREFIX_PATH "/usr")
set(CMAKE_IGNORE_PREFIX_PATH "/usr/local;/opt")
set(CMAKE_FIND_USE_CMAKE_ENVIRONMENT_PATH OFF)
set(CMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH OFF)
set(CMAKE_FIND_USE_PACKAGE_REGISTRY OFF)
set(CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY OFF)
set(CMAKE_CXX_COMPILER_LAUNCHER "")
set(Eigen3_DIR "/usr/share/eigen3/cmake" CACHE PATH "Declared Eigen config" FORCE)
set(OpenCV_DIR "/usr/lib/x86_64-linux-gnu/cmake/opencv4" CACHE PATH "Declared OpenCV4 config" FORCE)
set(Boost_DIR "/usr/lib/x86_64-linux-gnu/cmake/Boost-1.83.0" CACHE PATH "Declared Boost config" FORCE)
set(Ceres_DIR "/usr/lib/x86_64-linux-gnu/cmake/Ceres" CACHE PATH "Declared Ceres config" FORCE)
# No try-compile shortcut, ABI claim, legacy library or generated once output.
'''
with (OUT/'toolchain.cmake').open('x',encoding='utf-8',newline='\n') as stream:
    stream.write(toolchain)
name=(OUT/'toolchain.cmake').relative_to(ROOT).as_posix()
files_for_observation=dict(files)
files_for_observation[name]=dict(bytes=len(toolchain.encode()),sha256=hashlib.sha256(toolchain.encode()).hexdigest())

caps=load('results/native-linux-build-headers-20261019/selection.json')['caps']
forbidden=load('results/native-linux-required-input-refresh-20261019/selection.json')['forbidden_prefixes']
base=dict(caps=caps,forbidden_prefixes=forbidden,all_qualifications=False,dispatchable=False,
          excluded={},excluded_native_identities=[],linux_file_writes=False,compile=False,resource_query=False)
source_selection=dict(base,schema='linux-visible-production-source-selection-v1',
    selected=[dict(path=LINUX_ROOT+'/'+name,roles=['current-production-source' if name in files else 'toolchain-text'])
              for name in sorted(files_for_observation)],
    allowed_content_endpoints=[LINUX_ROOT+'/'+name for name in sorted(files_for_observation)],
    expected_content={LINUX_ROOT+'/'+name:row for name,row in files_for_observation.items()})
save(OUT/'production/selection.json',source_selection)

# Only named existing index endpoints without an actual retained Linux current-content pin.
# Never resample recent headers/compiler components/upstream143 or old build/objects/logs.
missing,nonregular,unavailable,already={ },[],[],[]
for path,row in old.items():
    identity=row.get('identity') or {}
    if identity.get('status')!='observed':
        unavailable.append(path);continue
    endpoint=identity['resolved'];s=identity['stat']
    if s['mode'] & 0o170000 != 0o100000:
        nonregular.append(path);continue
    if endpoint in recent_endpoints:
        already.append(path);continue
    if '/.git/' in endpoint or endpoint.startswith('/home/yuchen7509/flydrones-upstream/open_vins/'):
        continue
    # BlueGeneQ partial remains historical UNKNOWN and irrelevant to the selected Linux recipe.
    if endpoint.endswith('/BlueGeneQ-static.cmake'):
        continue
    rec=missing.setdefault(endpoint,dict(path=endpoint,roles=[],saved_aliases=[],estimated_bytes=s['bytes']))
    rec['roles']=sorted(set(rec['roles']+row['roles']))
    rec['saved_aliases'].append(path)
assert len(missing)<caps['selected_paths']
estimated=sum(row['estimated_bytes'] for row in missing.values())
assert max(row['estimated_bytes'] for row in missing.values())<=caps['file_bytes']
assert estimated<=caps['total_payload_bytes'], 'Do not partition a capped selection for refill/retry'
excluded={k:dict(phase=v['phase'],saved_pin=v['pin']) for k,v in recent.items()}
excluded.update({v['pin']['resolved']:dict(phase=v['phase'],saved_pin=v['pin']) for v in recent.values()})
deps=dict(base,schema='known-unbound-dependency-endpoints-v1',selected=[missing[k] for k in sorted(missing)],
          allowed_content_endpoints=sorted(missing),excluded=excluded,
          reused_actual_linux_observations=len(recent),estimated_unique_payload_bytes=estimated)
save(OUT/'dependencies/selection.json',deps)
save(OUT/'prior-pin-references.json',dict(files=recent,old_payloads_rehashed=False,
                                        cross_time=True,future_fresh_continuity_proven=False))
save(OUT/'selection-disposition.json',dict(production_count=len(source_selection['selected']),
    dependency_endpoints=len(missing),estimated_dependency_bytes=estimated,
    prior_index_aliases_already_with_content=len(already),nonregular=nonregular,
    unavailable=unavailable,bluegeneq_historical_partial_not_repaired=True,
    no_directory_search=True,no_build_or_native_run=True))
reader=(ROOT/'results/native-linux-build-headers-20261019/linux_reader.py').read_text(encoding='utf-8')
source_reader=reader.replace('                      sha256=digest.hexdigest(), stable=True))',
    '                      sha256=digest.hexdigest(), stable=True))\n'
    '            expected = selection["expected_content"][path]\n'
    '            if digest.hexdigest() != expected["sha256"] or size != expected["bytes"]:\n'
    '                raise Stop("Linux production bytes differ from prepared Windows bytes; no deployment/normalization/retry")')
assert source_reader!=reader
parent=(ROOT/'results/native-linux-build-headers-20261019/run_collection.py').read_text(encoding='utf-8')
for folder,script in (('production',source_reader),('dependencies',reader)):
    for fname,data in (('linux_reader.py',script),('run_collection.py',parent.replace('native-linux-build-headers-readonly-parent-v1','native-linux-production-inputs-'+folder+'-parent-v1'))):
        with (OUT/folder/fname).open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(data)
        ast.parse(data,filename=folder+'/'+fname)
print(json.dumps(dict(local_source_files=len(files),static_edges=len(edges),dynamic_sites=len(dynamic),
                      production_observation_count=len(files_for_observation),dependency_endpoints=len(missing),
                      estimated_dependency_bytes=estimated,prior_observation_refs=len(recent))))
