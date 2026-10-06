import pytest

from tools.benchmark.audit_owned_runtime_maps import ldd_paths


def test_ldd_paths_preserve_absolute_dependencies():
    text = "libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x1)\n/lib64/ld-linux-x86-64.so.2 (0x2)\n"
    assert ldd_paths(text) == ["/lib/x86_64-linux-gnu/libc.so.6", "/lib64/ld-linux-x86-64.so.2"]


def test_ldd_missing_dependency_is_refused():
    with pytest.raises(ValueError, match="missing"):
        ldd_paths("libmissing.so => not found")
