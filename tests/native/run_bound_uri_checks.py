"""Bound local candidate checks; never start Gazebo physics."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(binary):
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        a, b = root / 'a', root / 'b'
        a.mkdir()
        b.mkdir()
        source = root / 'world.sdf'
        source.write_text('<sdf version="1.6"/>')
        env = dict(os.environ, GZ_SIM_RESOURCE_PATH=f'{a}:{b}', SDF_PATH='', GZ_FILE_PATH='')

        def check(label, kind, uri, success, verify=lambda _: None, source_path=None):
            proc = subprocess.run([str(binary), 'bound-uri', kind, str(source_path or source), uri],
                                  env=env, cwd=root, text=True, capture_output=True, timeout=10)
            failure = None
            try:
                assert (proc.returncode == 0) is success, proc.stderr
                doc = json.loads(proc.stdout)
                assert doc['local_profile'] == 'fixed-local-files-v1'
                assert doc['local_candidates_qualified'] is success
                if success:
                    assert len(doc['local_candidates']) == 1
                    assert doc['local_candidates'][0] == doc['selected']
                    verify(doc)
            except (AssertionError, ValueError, KeyError) as exc:
                failure = repr(exc)
            rows.append(dict(label=label, returncode=proc.returncode, stdout=proc.stdout,
                             stderr=proc.stderr, failure=failure))

        (a / 'image.png').write_bytes(b'a')
        check('local-model-texture', 'texture', 'model://image.png', True)
        (b / 'image.png').write_bytes(b'b')
        check('two-texture-roots', 'texture', 'model://image.png', False)
        (b / 'image.png').unlink()
        (b / 'image.png').symlink_to(a / 'image.png')
        check('same-canonical-alias', 'texture', 'model://image.png', True)
        (b / 'image.png').unlink()
        (b / 'image.png').symlink_to(b / 'missing')
        check('dangling-alternate', 'texture', 'model://image.png', False)
        model = a / 'model'
        model.mkdir()
        (model / 'model.config').write_text('<model><name>x</name><version>1</version><sdf version="1.6">body.sdf</sdf></model>')
        (model / 'body.sdf').write_text('<sdf version="1.6"><model name="x"/></sdf>')
        def model_check(doc):
            assert doc['candidate_dependencies'] == [str(model / 'model.config')]
        check('include-config', 'include', 'model://model', True, model_check)
        (root / 'image.png').write_bytes(b'direct')
        check('source-relative-absolute-selection', 'texture', 'image.png', True)
        for value in ['https://example.invalid/a', 'model://x?y', '../image.png']:
            check('unsupported-' + value, 'texture', value, False)
        model_root = root / 'collada-model'
        meshes = model_root / 'meshes'
        fallback = model_root / 'materials' / 'textures'
        meshes.mkdir(parents=True)
        fallback.mkdir(parents=True)
        dae = meshes / 'body.dae'
        dae.write_text('<COLLADA/>')
        direct = meshes / 'ordered.png'
        shadowed = fallback / 'ordered.png'
        direct.write_bytes(b'direct')
        shadowed.write_bytes(b'different shadowed bytes')

        def ordered_check(doc):
            assert doc['selection_profile'] == 'material-ordered-fallback-v1'
            assert doc['local_candidates'] == [str(direct)]
            assert doc['shadowed_candidates'] == [str(shadowed)]

        check('collada-ordered-direct-wins', 'collada-image', 'ordered.png', True,
              ordered_check, dae)
    print(json.dumps(dict(cases=rows, failures=sum(x['failure'] is not None for x in rows),
                          checks=len(rows), physics_started=False), indent=2))
    return not any(row['failure'] for row in rows)


if __name__ == '__main__':
    sys.exit(0 if run(Path(sys.argv[1]).resolve(strict=True)) else 1)
