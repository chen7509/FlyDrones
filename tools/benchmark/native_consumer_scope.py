"""Verify the owned cgroup before a bounded native command; no flight authority."""

import json
import os
import resource
import subprocess
import sys
from pathlib import Path


def write(path, value):
    with path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    profile = json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    output = Path(profile['output'])
    cgroup_line = [x for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::')]
    if len(cgroup_line) != 1:
        raise RuntimeError('unified owned cgroup unknown')
    group = cgroup_line[0][3:]
    if not group.endswith('/'+profile['unit']):
        raise RuntimeError('owned unit cgroup mismatch')
    root = Path('/sys/fs/cgroup'+group)
    limits = {k: (root/k).read_text().strip() for k in ('memory.max', 'memory.swap.max', 'cpu.max', 'pids.max')}
    expected = {'memory.max': str(profile['memory']), 'memory.swap.max': '0',
                'cpu.max': '100000 100000', 'pids.max': '64'}
    props = subprocess.run(['systemctl', '--user', 'show', profile['unit'],
                            '--property=InvocationID', '--property=ControlGroup'], capture_output=True, text=True, check=True)
    facts = {'pid': os.getpid(), 'cgroup': group, 'limits': limits,
             'systemd_properties': props.stdout, 'argv': profile['argv'], 'qualification': False}
    write(output/'inside-before.json', facts)
    identity = dict(x.split('=', 1) for x in props.stdout.splitlines() if '=' in x)
    if limits != expected or identity.get('ControlGroup') != group or not identity.get('InvocationID'):
        raise RuntimeError('scope limits/identity not verified')
    resource.setrlimit(resource.RLIMIT_FSIZE, (64*1024**2, 64*1024**2))
    command = ['/usr/bin/time', '-v', '-o', str(output/'resources.txt'), '/usr/bin/timeout',
               '--signal=TERM', '--kill-after=5s', str(profile['seconds'])+'s', *profile['argv']]
    with (output/'stdout.bin').open('xb') as stdout, (output/'stderr.bin').open('xb') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        write(output/'child-start.json', {'pid': process.pid, 'command': command, 'cgroup': group})
        code = process.wait()
    write(output/'inside-completion.json', {'exit_code': code, 'cgroup': group,
          'memory_events': (root/'memory.events').read_text(),
          'memory_peak': (root/'memory.peak').read_text() if (root/'memory.peak').exists() else None,
          'limits_after': {k: (root/k).read_text().strip() for k in expected}, 'qualification': False})
    return code


if __name__ == '__main__':
    raise SystemExit(main())
