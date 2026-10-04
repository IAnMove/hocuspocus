"""Agents read the bound port from a file instead of the server log."""
import json
import os

from services.server_endpoint import publish_server_endpoint, withdraw_server_endpoint


def test_the_effective_port_is_published_and_withdrawn_by_its_own_process(tmp_path):
    path = tmp_path / 'settings' / 'server-endpoint.json'
    record = publish_server_endpoint(path, host='0.0.0.0', display_host='127.0.0.1', port=42053)
    stored = json.loads(path.read_text())
    assert stored == record
    assert stored['url'] == 'http://127.0.0.1:42053'
    assert stored['mcp_url'] == 'http://127.0.0.1:42053/api/v1/mcp'
    assert (stored['host'], stored['port'], stored['pid']) == ('0.0.0.0', 42053, os.getpid())
    assert list(path.parent.iterdir()) == [path], 'no temporary file is left behind'

    withdraw_server_endpoint(path, os.getpid() + 1)
    assert path.exists(), 'another process never removes a record it does not own'
    withdraw_server_endpoint(path, os.getpid())
    assert not path.exists()
    withdraw_server_endpoint(path, os.getpid())
