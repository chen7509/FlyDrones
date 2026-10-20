import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICY = 'blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol'


def diff_check(tmp_path, added, policy=None):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], env=env, capture_output=True)
    assert git('init', '-q').returncode == 0
    assert git('config', 'core.autocrlf', 'false').returncode == 0
    file = tmp_path / 'a.cpp'
    file.write_bytes(b'int a = 1;\r\n')
    assert git('add', 'a.cpp').returncode == 0
    file.write_bytes(b'int a = 1;\r\n' + added)
    return git(*(['-c', f'core.whitespace={policy}'] if policy else []), 'diff', '--check')


@pytest.mark.skipif(shutil.which('git') is None, reason='actual Git required')
def test_original_crlf_refusal_is_real(tmp_path):
    result = diff_check(tmp_path, b'int b = 2;\r\n')
    assert result.returncode != 0
    assert b'trailing whitespace' in result.stdout


@pytest.mark.parametrize('added,accepted', [(b'int b = 2;\r\n', True),
    (b'int b = 2; \r\n', False), (b'int b = 2; \n', False),
    (b'int b = 2;\r\n\r\n', False), (b' \tint b = 2;\r\n', False)])
def test_new_executable_policy_keeps_real_whitespace_refusal(tmp_path, added, accepted):
    script = (ROOT/'tools/benchmark/ego_causal_build_v3.sh').read_text()
    line = next(line for line in script.splitlines() if line.endswith('diff --check'))
    words = shlex.split(line)
    policy = words[words.index('-c')+1].split('=', 1)[1] if '-c' in words else None
    result = diff_check(tmp_path, added, policy)
    assert (result.returncode == 0) is accepted
