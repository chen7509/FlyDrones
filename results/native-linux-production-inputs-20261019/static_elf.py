"""Bounded static ELF dynamic-section parser; no executable loading."""
import collections
import struct
ROOT = None
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
