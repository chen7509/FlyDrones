"""Real SDK lookup checks, without loading plugin instances or physics."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(binary):
    cases = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        env = dict(os.environ, GZ_SIM_SYSTEM_PLUGIN_PATH=str(root),
                   GZ_PLUGIN_PATH='', IGN_PLUGIN_PATH='', GZ_SIM_RESOURCE_PATH=str(root),
                   SDF_PATH='', GZ_FILE_PATH='')

        def check(label, args, success, verify=lambda _: None, parse_failure=False):
            result = subprocess.run([str(binary), *args], env=env, cwd=root,
                                    capture_output=True, text=True, timeout=10)
            error = None
            try:
                assert (result.returncode == 0) is success, result.stderr
                if success or parse_failure:
                    verify(json.loads(result.stdout))
            except (AssertionError, KeyError, ValueError) as exc:
                error = repr(exc)
            cases.append(dict(label=label, args=args, expected_success=success,
                              returncode=result.returncode, stdout=result.stdout,
                              stderr=result.stderr, assertion_error=error))

        winner = root / 'libfly-context.so'
        winner.write_bytes(b'lookup only')
        check('single', ['plugin', 'fly-context'], True)
        for name in ['fly-context.so', 'fly-context', 'fly-context.DLL',
                     'libfly-context.dylib', 'Release/fly-context.dll']:
            alternate = root / name
            alternate.parent.mkdir(exist_ok=True)
            alternate.write_bytes(b'different file')
            def refusal(doc):
                assert doc['ok'] is False and doc['error']
                assert str(alternate) in doc['examined_paths']
                assert len(doc['candidates']) == 2
            check('ambiguous-' + name, ['plugin', 'fly-context'], False,
                  refusal, parse_failure=True)
            alternate.unlink()
        alias = root / 'fly-context.so'
        alias.symlink_to(winner)
        check('same-identity-symlink', ['plugin', 'fly-context'], True)
        alias.unlink()
        alias.mkdir()
        def nonregular(doc):
            assert doc['ok'] is False and str(alias) in doc['error']
            assert str(alias) in doc['examined_paths']
        check('nonregular-alias', ['plugin', 'fly-context'], False,
              nonregular, parse_failure=True)
        alias.rmdir()
        check('relative-path-refusal', ['plugin', '../fly-context'], False)
        check('absolute-short-circuit', ['plugin', str(winner)], True)
        other = root / 'deprecated'
        other.mkdir()
        (other / winner.name).write_bytes(b'deprecated conflicting root')
        env['IGN_PLUGIN_PATH'] = str(other)
        check('deprecated-conflict', ['plugin', 'fly-context'], False)

        def context_assert(doc):
            assert doc['before_environment']['IGN_PLUGIN_PATH'] == str(other)
            assert doc['cwd'] == str(root)
            assert str(root) + '/' in doc['file_paths']
            assert str(other) + '/' in doc['plugin_paths']
            assert Path(doc['sdf_share_path']).is_dir()
            assert doc['runtime_closure_qualified'] is False
            assert doc['search_context_qualified'] is False
            assert isinstance(doc['sdf_uri_paths'], dict)
            assert type(doc['sdf_callback_present']) is bool
            assert doc['common_file_callbacks_present'] is None
            assert doc['common_uri_callbacks_present'] is None
            assert doc['common_callback_observation'] == 'unavailable: SDK has no callback inspection API'
            assert doc['before_environment']['SDF_PATH'] == ''
            assert str(root) in doc['after_environment']['SDF_PATH']

        check('sdk-context', ['context'], True, context_assert)
        assert env['SDF_PATH'] == ''  # Child API must not modify this caller.
        check('bad-context-args', ['context', 'extra'], False)
    report = dict(cases=cases, checks=len(cases),
                  failures=sum(row['assertion_error'] is not None for row in cases),
                  physics_started=False, plugin_instances_created=False)
    print(json.dumps(report, indent=2))
    return report['failures'] == 0


if __name__ == '__main__':
    sys.exit(0 if run(Path(sys.argv[1]).resolve(strict=True)) else 1)
