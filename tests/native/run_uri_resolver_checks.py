"""Real installed URI selection checks; no simulator, renderer or pixel decoding."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(binary):
    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_dir, cwd, models = (root / x for x in ('source', 'cwd', 'models'))
        for path in (source_dir, cwd, models):
            path.mkdir()
        source = source_dir / 'world.sdf'
        source.write_text('<sdf/>')
        (source_dir / 'texture.png').write_bytes(b'source texture')
        (cwd / 'texture.png').write_bytes(b'wrong cwd texture')
        env = dict(os.environ, GZ_SIM_RESOURCE_PATH=str(models), SDF_PATH='', GZ_FILE_PATH='')
        env.pop('GZ_MESH_FORCE_ASSIMP', None)
        before = dict(env)

        def call(kind, uri, *, ok=True, environment=None, src=source):
            p = subprocess.run([str(binary), 'uri', kind, str(src), uri], cwd=cwd,
                               env=environment or env, capture_output=True, text=True, timeout=10)
            row = dict(kind=kind, uri=uri, source=str(src), returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
            cases.append(row)
            assert (p.returncode == 0) is ok, row
            result = json.loads(p.stdout)
            assert result['ok'] is ok
            assert result['runtime_closure_qualified'] is False
            assert result['ambiguity_qualified'] is False
            assert result['cwd'] == str(cwd)
            return result

        r = call('texture', 'texture.png')
        assert r['selected'] == str(source_dir / 'texture.png')
        assert r['before_environment']['SDF_PATH'] == ''
        assert str(models) in r['after_environment']['SDF_PATH']
        assert env == before  # helper process must not change caller's environment
        model = models / 'test-model'
        model.mkdir()
        (model / 'model.config').write_text('<model><name>x</name><version>1</version><sdf version="1.6">body.sdf</sdf></model>')
        (model / 'body.sdf').write_text('<sdf version="1.6"><model name="x"/></sdf>')
        r = call('include', 'model://test-model')
        assert r['selected'] == str(model / 'body.sdf')
        assert r['model_config'] == str(model / 'model.config')
        # Includes use native cwd/search semantics, not the material's source dir.
        (cwd / 'local.sdf').write_text('<sdf/>')
        (source_dir / 'local.sdf').write_text('<sdf/>')
        assert call('include', 'local.sdf')['selected'] == str(cwd / 'local.sdf')
        (models / 'a.dae').write_text('<COLLADA/>')
        assert call('mesh-path', 'model://a.dae')['selected'] == str(models / 'a.dae')
        texture_dir = root / 'materials' / 'textures'
        texture_dir.mkdir(parents=True)
        (texture_dir / 'fallback.png').write_bytes(b'fallback')
        assert call('collada-image', 'fallback.png')['selected'] == str(texture_dir / 'fallback.png')
        call('texture', 'missing.png', ok=False)
        call('include', 'model://absent', ok=False)
        call('texture', 'https://example.invalid/x', ok=False)
        call('texture', 'model://x\ny', ok=False)
        call('texture', ' texture.png', ok=False)
        call('texture', 'texture.png', src=Path('relative.sdf'), ok=False)
        call('collada-image', 'fallback.png', environment=dict(env, GZ_MESH_FORCE_ASSIMP='1'), ok=False)
        call('unsupported', 'texture.png', ok=False)
    print(json.dumps(dict(passed=True, cases=cases, count=len(cases), physical_run=False)))


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve(strict=True))
