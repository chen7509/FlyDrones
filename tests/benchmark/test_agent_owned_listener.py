import pytest

from tools.benchmark.agent_owned_listener import parse_owned_udp_listener


def test_exact_owned_udp_listener():
    row = 'UNCONN 0 0 0.0.0.0:18888 0.0.0.0:* users:(("MicroXRCEAgent",pid=1234,fd=6))\n'
    assert parse_owned_udp_listener(row, 1234, 18888) == row.strip()


@pytest.mark.parametrize('row', [
    '',
    'UNCONN 0 0 0.0.0.0:18888 0.0.0.0:*',
    'UNCONN 0 0 0.0.0.0:18888 0.0.0.0:* users:(("other",pid=9,fd=6))',
    'UNCONN 0 0 0.0.0.0:18889 0.0.0.0:* users:(("MicroXRCEAgent",pid=1234,fd=6))',
    'tcp LISTEN 0 0 0.0.0.0:18888 0.0.0.0:* users:(("MicroXRCEAgent",pid=1234,fd=6))',
    'UNCONN 0 0 [::]:18888 [::]:* users:(("MicroXRCEAgent",pid=1234,fd=6))',
    'UNCONN 0 0 0.0.0.0:18888 0.0.0.0:* users:(("MicroXRCEAgent",pid=1234,fd=6))\n'
    'UNCONN 0 0 0.0.0.0:18888 0.0.0.0:* users:(("other",pid=9,fd=6))',
])
def test_wrong_or_unattributed_listener_refuses(row):
    with pytest.raises(ValueError):
        parse_owned_udp_listener(row, 1234, 18888)
