"""Static ELF/package/CMake frontier from retained declared input bytes; no Linux access/execution."""

import collections
import json
from pathlib import Path
import struct

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save(name,value):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,indent=2);f.write('\n')


refs=load(OUT/'prior-pin-references.json')['files']
for phase in ('production','dependencies'):
    r=load(OUT/phase/'collection-result.json')
    assert r['collection_complete'] and not r['errors']
    for row in r['observed_files']:
        refs[row['path']]=dict(pin={k:row[k] for k in ('path','resolved','bytes','sha256')},
                             phase=(OUT/phase).relative_to(ROOT).as_posix(),blob=row['blob'])
save('combined-pin-references-before-frontier.json',dict(files=refs,cross_time=True,not_admission=True))
by_endpoint={v['pin']['resolved']:v for v in refs.values()}
by_name=collections.defaultdict(set)
for name,rec in refs.items():
    by_name[Path(name).name].add(rec['pin']['resolved'])
    by_name[Path(rec['pin']['resolved']).name].add(rec['pin']['resolved'])

# Newly current package-list bytes are the only path index used for follow-up selection.
package_paths=set()
for path,rec in refs.items():
    if path.startswith('/var/lib/dpkg/info/') and path.endswith('.list'):
        raw=(ROOT/rec['phase']/rec['blob']).read_bytes()
        for line in raw.decode('utf-8',errors='strict').splitlines():
            if line.startswith('/') and '/..' not in line and '\x00' not in line:
                package_paths.add(line)
package_names=collections.defaultdict(set)
for path in package_paths:
    package_names[Path(path).name].add(path)


def elf(path,rec):
    file=ROOT/rec['phase']/rec['blob']
    with file.open('rb') as f:
        hdr=f.read(64)
        if not hdr.startswith(b'\x7fELF'):
            return None
        if len(hdr)<64 or hdr[4:6]!=b'\x02\x01':
            return dict(error='unsupported ELF class/endian; not executed')
        machine=struct.unpack_from('<H',hdr,18)[0]
        phoff=struct.unpack_from('<Q',hdr,32)[0]
        entsize,num=struct.unpack_from('<HH',hdr,54)
        if entsize!=56 or num>4096 or phoff+num*entsize>rec['pin']['bytes']:
            return dict(error='bounded ELF program-header structure refused')
        f.seek(phoff);raw=f.read(num*entsize)
        loads=[];dynamic=None;interp=None
        for i in range(num):
            typ,flags,offset,vaddr,paddr,filesz,memsz,align=struct.unpack_from('<IIQQQQQQ',raw,i*56)
            if offset+filesz>rec['pin']['bytes']:
                return dict(error='ELF segment outside saved input')
            if typ==1:loads.append((vaddr,filesz,offset))
            if typ==2:dynamic=(offset,filesz)
            if typ==3:
                if filesz>4096:return dict(error='interpreter string bound')
                f.seek(offset);interp=f.read(filesz).rstrip(b'\0').decode('utf-8','strict')
        result=dict(machine=machine,class_bits=64,endianness='little',interpreter=interp,
                    needed=[],soname=None,rpath=None,runpath=None,executed=False)
        if not dynamic:return result
        offset,size=dynamic
        if size>2*1024**2 or size%16:return dict(error='dynamic table bound')
        f.seek(offset);data=f.read(size);tags=collections.defaultdict(list)
        for i in range(0,size,16):
            tag,value=struct.unpack_from('<qQ',data,i)
            if tag==0:break
            tags[tag].append(value)
        if not tags[5] or not tags[10]:return result
        address,strsize=tags[5][0],tags[10][0]
        if strsize>2*1024**2:return dict(error='dynamic strings bound')
        candidates=[base+(address-v) for v,n,base in loads if v<=address and address+strsize<=v+n]
        if len(candidates)!=1:return dict(error='dynamic string file mapping unresolved')
        f.seek(candidates[0]);strings=f.read(strsize)
        def text(index):
            if index>=len(strings):raise ValueError('dynamic string index')
            end=strings.find(b'\0',index)
            if end<0:raise ValueError('dynamic string terminator')
            return strings[index:end].decode('utf-8','strict')
        result['needed']=[text(i) for i in tags[1]]
        for tag,name in ((14,'soname'),(15,'rpath'),(29,'runpath')):
            result[name]=text(tags[tag][0]) if tags[tag] else None
        return result


elfs={};errors=[]
# Read only ELF/header/config/package content necessary for this authorized closure analysis,
# not old archives or a full retained-payload hash audit.
for path,rec in sorted(by_endpoint.items()):
    if (path.startswith('/usr/bin/') or path.startswith('/usr/libexec/')
            or '.so' in Path(path).name or path.endswith('.o')):
        try:
            item=elf(path,rec)
            if item:
                elfs[path]=item
                if item.get('soname'):by_name[item['soname']].add(path)
        except Exception as exc:
            errors.append(dict(path=path,error=repr(exc)))

unresolved=collections.defaultdict(list)
ambiguities={};relations=[]
for path,obs in elfs.items():
    for name in obs.get('needed',[]):
        matches=sorted(by_name.get(name,()))
        relations.append(dict(consumer=path,needed=name,known_candidate_endpoints=matches,
                              actual_loader_choice_proven=False))
        if not matches:unresolved[name].append(path)
        if len(matches)>1:ambiguities[name]=matches
    interp=obs.get('interpreter')
    if interp and not by_name.get(Path(interp).name):unresolved[Path(interp).name].append(path)

new={};unindexed={}
for name,consumers in sorted(unresolved.items()):
    candidates=set(package_names.get(name,()))
    # Exact SONAME symlink and versioned siblings all come from the current package-list index.
    stem=name.split('.so')[0]+'.so' if '.so' in name else name
    siblings={p for p in package_paths if Path(p).name==stem or Path(p).name.startswith(stem+'.')}
    candidates|=siblings
    if not candidates:unindexed[name]=consumers
    for candidate in candidates:
        new.setdefault(candidate,set()).add('ELF-needed:'+name)

# The shared-library and PIE startup files differ from crtbegin.o/crtend.o.
startup_names={'Scrt1.o','crt1.o','crti.o','crtn.o','crtbeginS.o','crtendS.o','libc.so','libm.so','libgcc_s.so'}
for name in startup_names:
    for path in package_names.get(name,()):
        new.setdefault(path,set()).add('startup-or-linker-script:'+name)
for path in package_paths:
    if path.endswith('.cmake') and '/cmake/' in path:
        new.setdefault(path,set()).add('indexed-dependency-package-cmake-config')
for path in ('/etc/ld.so.cache','/etc/ld.so.conf'):
    new.setdefault(path,set()).add('loader-search-input-not-resource-query')
for path in package_paths:
    if path.startswith('/etc/ld.so.conf.d/') and path.endswith('.conf'):
        new.setdefault(path,set()).add('indexed-loader-search-config')
new={p:roles for p,roles in new.items() if p not in refs and p not in by_endpoint
     and not p.startswith('/home/') and '/.git/' not in p}
selected=[dict(path=p,roles=sorted(roles)) for p,roles in sorted(new.items())]
base=load(OUT/'dependencies/selection.json')
total_payload=sum(load(OUT/p/'collection-result.json')['stream_payload_bytes'] for p in ('production','dependencies'))
total_metadata=sum(load(OUT/p/'collection-result.json')['stream_metadata_bytes'] for p in ('production','dependencies'))
caps=dict(base['caps'],total_payload_bytes=base['caps']['total_payload_bytes']-total_payload,
          metadata_bytes=base['caps']['metadata_bytes']-total_metadata)
assert 0<len(selected)<6000 and caps['total_payload_bytes']>0 and caps['metadata_bytes']>8192
selection=dict(base,schema='newly-discovered-static-closure-frontier-v1',selected=selected,
               allowed_content_endpoints=sorted(new),caps=caps,
               excluded={p:dict(saved_pin=v['pin'],phase=v['phase']) for p,v in refs.items()},
               static_scope='Newly discovered references after complete129/1046 selections, not cap refill or retry',
               earlier_phase_payload_bytes=total_payload,earlier_phase_metadata_bytes=total_metadata)
selection['excluded'].update({p:dict(saved_pin=v['pin'],phase=v['phase']) for p,v in by_endpoint.items()})
save('frontier/selection.json',selection)
save('static-dependency-analysis-before-frontier.json',dict(elfs=elfs,relations=relations,
    unbound_needed_names=dict(unresolved),names_without_indexed_candidates=unindexed,
    multiple_candidate_names=ambiguities,parser_errors=errors,new_frontier_paths=len(selected),
    package_index_paths=len(package_paths),actual_loader_selection_proven=False,
    all_runtime_python_and_cmake_consumption_proven=False))
for name in ('linux_reader.py','run_collection.py'):
    script=(OUT/'dependencies'/name).read_text(encoding='utf-8')
    if name=='run_collection.py':script=script.replace('production-inputs-dependencies','production-inputs-frontier')
    with (OUT/'frontier'/name).open('x',encoding='utf-8',newline='\n') as f:f.write(script)
print(json.dumps(dict(static_elf_files=len(elfs),elf_needed_edges=len(relations),
    unbound_needed_names=len(unresolved),names_without_package_index=len(unindexed),
    new_exact_frontier_paths=len(selected),remaining_payload_bound=caps['total_payload_bytes'],
    remaining_metadata_bound=caps['metadata_bytes'],parser_errors=len(errors))))
