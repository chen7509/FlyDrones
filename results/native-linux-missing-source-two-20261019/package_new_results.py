"""Seal only this newly produced two-file restoration result and its progress document."""

import ast
import hashlib
import json
from pathlib import Path
import zipfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
BASE = ROOT/'evidence/native-linux-missing-source-two-20261019'
paths = sorted([p for p in OUT.rglob('*') if p.is_file() and 'postseal' not in p.relative_to(OUT).parts]
               + [ROOT/'docs/NATIVE_LINUX_MISSING_SOURCE_TWO_PROGRESS.md'])
assert not any(p.is_symlink() for p in paths)
for path in paths:
    if path.suffix == '.py':
        ast.parse(path.read_text(encoding='utf-8'),filename=path.name)
mapping = [dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,
                sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]
manifest = json.dumps(dict(schema='exact-two-restoration-new-files-map-v1',files=mapping,
                           only_new_phase_files=True,old_payload_archives_checked=False,
                           all_qualifications=False,dispatchable=False),ensure_ascii=False,indent=2).encode()+b'\n'
archive = Path(str(BASE)+'.zip')
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as target:
    for item in mapping:
        target.write(ROOT/item['path'],item['path'])
    target.writestr('MANIFEST.json',manifest)
with zipfile.ZipFile(archive,'r') as target:
    assert target.testzip() is None
    assert len(target.infolist()) == len(mapping)+1
    for item in mapping:
        payload = target.read(item['path'])
        assert len(payload) == item['bytes'] and hashlib.sha256(payload).hexdigest() == item['sha256']
    assert target.read('MANIFEST.json') == manifest
receipt = dict(schema='new-exact-two-restoration-archive-receipt-v1',archive=archive.relative_to(ROOT).as_posix(),
               bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
               members=len(mapping)+1,mapped_members=len(mapping),mapped_bytes=sum(i['bytes'] for i in mapping),
               manifest_bytes=len(manifest),whole_member_bytes=sum(i['bytes'] for i in mapping)+len(manifest),
               executor_new_crc_memberhash_only=True,old_archives_or_payloads_checked=False,
               source_native_delivery_review=False,all_qualifications=False,dispatchable=False)
with Path(str(BASE)+'.map.json').open('x',encoding='utf-8',newline='\n') as target:
    json.dump(dict(files=mapping,manifest_sha256=hashlib.sha256(manifest).hexdigest()),target,indent=2)
    target.write('\n')
with Path(str(BASE)+'.receipt.json').open('x',encoding='utf-8',newline='\n') as target:
    json.dump(receipt,target,indent=2)
    target.write('\n')
print(json.dumps(receipt))
