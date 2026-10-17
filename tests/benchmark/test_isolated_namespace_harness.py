import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('isolated_harness', Path(__file__).with_name('check_isolated_namespace.py'))
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def fixture():
    worker = dict(net='net:[20]', user='user:[21]', uid=0, gid=0, euid=0, egid=0,
                  pid=30, pgrp=30, session=30, start_ticks=40)
    marker = dict(identity=dict(worker, pid=31, start_ticks=41), environment={'HOME': '/home/user'}, mode='normal')
    return worker, marker


def test_child_marker_checks_exact_environment_and_owner():
    worker, marker = fixture()
    assert harness.audit_child_marker(marker, worker, {'HOME': '/home/user'}) is True


@pytest.mark.parametrize('key,value', [('net', 'net:[100]'), ('user', 'user:[101]'), ('uid', 1000),
                                     ('pgrp', 31), ('session', 31), ('pid', 30), ('start_ticks', 39)])
def test_child_marker_rejects_identity_drift(key, value):
    worker, marker = fixture()
    marker['identity'][key] = value
    with pytest.raises(ValueError):
        harness.audit_child_marker(marker, worker, {'HOME': '/home/user'})


def test_child_marker_rejects_extra_environment():
    worker, marker = fixture()
    marker['environment']['UNDECLARED'] = '1'
    with pytest.raises(ValueError):
        harness.audit_child_marker(marker, worker, {'HOME': '/home/user'})
