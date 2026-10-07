"""Explicit Linux fixture: ordinary local sockets, never a PX4 daemon."""
import argparse
import hashlib
import json
import os
import selectors
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]

from tools.benchmark.owned_daemon_connection import ConnectionRefusal, connect_owned_daemon, observe_owner  # noqa: E402


def save(path,value):
    with path.open('x',encoding='utf-8') as stream:
        data=json.dumps(value,indent=2)+'\n'
        assert stream.write(data)==len(data)
        stream.flush()


def child(args):
    listener=socket.socket(fileno=args.fd) if args.fd is not None else socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    if args.fd is None:
        listener.bind(args.socket)
        listener.listen(1)
    listener.settimeout(5)
    print(json.dumps(dict(ready=True,pid=os.getpid())),flush=True)
    result=dict(application_bytes=None,error=None)
    try:
        connection,_=listener.accept()
        with connection:
            connection.settimeout(3)
            result['application_bytes']=connection.recv(4096).hex()
    except Exception as exc:
        result['error']=repr(exc)
    finally:
        listener.close()
        save(args.result,result)
    return 0 if result['error'] is None else 2


def main(args):
    out=args.output.absolute()
    out.mkdir(parents=True,exist_ok=False)
    files=[Path(__file__),ROOT/'tools/benchmark/owned_daemon_connection.py',
           ROOT/'tools/benchmark/owned_group_evidence.py',Path(sys.executable).resolve()]
    def hashes():
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    baseline=hashes()
    cases=['matching','wrong-owner','inherited-listener','owner-exited','journal-refusal']
    save(out/'prospective.json',dict(producer=args.producer,cases=cases,files=baseline,
         expected_match=['matching'],connect_budget_ns=2000000000,ready_budget_s=5,
         px4_started=False,application_send_allowed=False,
         resource_scope='explicit source/parser/python files; not complete OS/runtime closure'))
    results=[]
    for case in cases:
        folder=out/case
        folder.mkdir()
        server=sentinel=None
        inherited=None
        with tempfile.TemporaryDirectory(prefix='fly-peer-') as temp:
            path=str(Path(temp)/'socket')
            argv=[sys.executable,'-I',str(Path(__file__).resolve()),'--child','--socket',path,
                  '--result',str(folder/'server.json')]
            pass_fds=()
            if case=='inherited-listener':
                inherited=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
                inherited.bind(path)
                inherited.listen(1)
                argv+=['--fd',str(inherited.fileno())]
                pass_fds=(inherited.fileno(),)
            before=time.monotonic_ns()
            evidence=None
            exception=None
            events=[]
            connection=None
            cleanup=[]
            with (folder/'stderr.txt').open('xb') as stderr:
                try:
                    server=subprocess.Popen(argv,cwd=temp,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},
                                            stdout=subprocess.PIPE,stderr=stderr,pass_fds=pass_fds,start_new_session=True)
                    if inherited:
                        inherited.close()
                        inherited=None
                    with selectors.DefaultSelector() as selector:
                        selector.register(server.stdout,selectors.EVENT_READ)
                        if not selector.select(5):
                            raise TimeoutError('fixture readiness')
                    ready=json.loads(server.stdout.readline())
                    assert ready==dict(ready=True,pid=server.pid)
                    target=server
                    if case=='wrong-owner':
                        sentinel=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)'],
                                                  cwd=temp,stdout=subprocess.DEVNULL,stderr=stderr,start_new_session=True)
                        # No workload dependency: Popen has completed exec before return.
                        target=sentinel
                    expected=observe_owner(target)
                    save(folder/'owner.json',expected)
                    if case=='owner-exited':
                        server.terminate()
                        server.wait(timeout=3)

                    def journal(event,events=events,folder=folder,case=case):
                        events.append(event)
                        save(folder/f'event-{len(events):02}.json',event)
                        if case=='journal-refusal' and event['kind']=='peer_observed':
                            raise OSError('prospective fixture journal refusal after retained write')

                    try:
                        connection,evidence=connect_owned_daemon(target,expected,path,
                            deadline_ns=time.monotonic_ns()+2000000000,journal=journal)
                    except ConnectionRefusal as exc:
                        exception=str(exc)
                        evidence=exc.evidence
                    finally:
                        if connection is not None:
                            connection.close()
                    assert evidence['connection_peer_matched']==(case=='matching'),evidence
                    assert evidence['network_authorized'] is False and evidence['fusion_qualified'] is False
                    server.wait(timeout=4)
                    if case!='owner-exited':
                        payload=json.loads((folder/'server.json').read_text())
                        assert payload==dict(application_bytes='',error=None),payload
                        assert server.returncode==0
                    else:
                        assert server.returncode==-15
                finally:
                    if inherited:
                        inherited.close()
                    for name,process in [('server',server),('sentinel',sentinel)]:
                        if process is None:
                            continue
                        signals=[]
                        if process.poll() is None:
                            signals.append('TERM')
                            process.terminate()
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                signals.append('KILL')
                                process.kill()
                                process.wait(timeout=3)
                        if process.stdout:
                            process.stdout.close()
                        cleanup.append(dict(role=name,pid=process.pid,signals=signals,exit=process.returncode))
                    save(folder/'cleanup.json',cleanup)
            result=dict(case=case,evidence=evidence,error=exception,elapsed_ns=time.monotonic_ns()-before,cleanup=cleanup)
            save(folder/'result.json',result)
            results.append(result)
    after=hashes()
    save(out/'post-hashes.json',after)
    assert after==baseline
    save(out/'summary.json',results)
    print('5 kernel peer-identity cases matched; zero command bytes; owned children reaped')
    return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--socket')
    parser.add_argument('--fd',type=int)
    parser.add_argument('--result',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--producer')
    args=parser.parse_args()
    raise SystemExit(child(args) if args.child else main(args))
