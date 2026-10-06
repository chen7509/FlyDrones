"""Run with a built resolver path; no simulator or plugin instance is created."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(binary):
    count = 0
    cases = []

    def call(*args, ok=True, env=None):
        nonlocal count
        p = subprocess.run([str(binary), *map(str, args)], capture_output=True, text=True, timeout=10, env=env)
        cases.append(dict(args=list(map(str, args)), expected_success=ok, returncode=p.returncode,
                          stdout=p.stdout, stderr=p.stderr,
                          plugin_path=env.get('GZ_SIM_SYSTEM_PLUGIN_PATH') if env else None))
        assert (p.returncode == 0) is ok, (args, p.returncode, p.stdout, p.stderr)
        count += 1
        return json.loads(p.stdout) if ok else p

    dirs = call('installation')
    assert Path(dirs['media'], 'gazebo.material').is_file()
    assert Path(dirs['plugins']).is_dir()
    selected = call('plugin', 'gz-sim-physics-system')
    assert Path(selected['selected']).is_file() and selected['candidates']
    call('plugin', 'definitely-absent-flydrones-plugin', ok=False)
    call('plugin', '', ok=False)
    call('plugin', 'x\ny', ok=False)
    call('unknown', ok=False)
    call('installation', 'extra', ok=False)
    call('model', 'relative', ok=False)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        call('model', root / 'missing', ok=False)
        model = root / 'model'
        model.mkdir()
        (model / 'model.config').write_text('<model><name>test</name><version>1</version><sdf version="1.6">selected.sdf</sdf></model>')
        (model / 'selected.sdf').write_text('<sdf version="1.6"><model name="test"/></sdf>')
        r = call('model', model)
        assert Path(r['selected']) == model / 'selected.sdf'
        # Real distinct candidate files: resolver must not load or instantiate either.
        a, b = root / 'a', root / 'b'
        a.mkdir()
        b.mkdir()
        (a / 'libfly-test.so').write_bytes(b'not an ELF, lookup only')
        (b / 'libfly-test.so').write_bytes(b'other file')
        import os
        env = dict(os.environ, GZ_SIM_SYSTEM_PLUGIN_PATH=f'{a}:{b}')
        call('plugin', 'fly-test', env=env, ok=False)
        env['GZ_SIM_SYSTEM_PLUGIN_PATH'] = str(a)
        r = call('plugin', 'fly-test', env=env)
        assert Path(r['selected']) == a / 'libfly-test.so'
    print(json.dumps(dict(checks=count, cases=cases, passed=True, simulator_started=False, plugins_instantiated=False)))


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve(strict=True))
