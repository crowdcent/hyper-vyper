"""forward_precompiles, against a fake JSON-RPC node on localhost (no network)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import boa
import pytest
from eth_abi import encode

from hyper_vyper.testing import _precompiles as pc
from hyper_vyper.testing import forward_precompiles
from tests.support import USER

READER = """
# pragma version 0.4.3
from hyper_vyper import constants
from hyper_vyper import precompiles

@external
@view
def usdc(user: address) -> uint64:
    return precompiles.spot_balance(user, constants.USDC_TOKEN_INDEX).total

@external
@view
def l1_block() -> uint64:
    return precompiles.l1_block_number()
"""


class FakeNode(BaseHTTPRequestHandler):
    calls: list = []
    replies: dict = {}
    transient = 0  # answer this many requests with a non-revert error first

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        call = body["params"][0]
        FakeNode.calls.append((call["to"], call["data"]))
        reply = FakeNode.replies.get(int(call["to"], 16))
        if FakeNode.transient:
            FakeNode.transient -= 1
            out = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "invalid block"}}
        elif reply is None:
            out = {"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}}
        else:
            out = {"jsonrpc": "2.0", "id": 1, "result": "0x" + reply.hex()}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def node():
    FakeNode.calls, FakeNode.replies, FakeNode.transient = [], {}, 0
    server = HTTPServer(("127.0.0.1", 0), FakeNode)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_reads_go_to_the_node(node):
    boa.reset_env()
    FakeNode.replies[pc.SPOT_BALANCE] = encode(["uint64", "uint64", "uint64"], [123 * 10**8, 0, 0])
    FakeNode.replies[pc.L1_BLOCK_NUMBER] = encode(["uint64"], [777])
    reader = boa.loads(READER)
    with forward_precompiles(node) as live:
        assert reader.usdc(USER) == 123 * 10**8
        assert reader.l1_block() == 777
        assert live.calls == 2
    to, data = FakeNode.calls[0]
    assert int(to, 16) == pc.SPOT_BALANCE
    assert data == "0x" + encode(["address", "uint64"], [USER, 0]).hex()


def test_a_node_revert_reverts_the_read(node):
    boa.reset_env()
    reader = boa.loads(READER)
    with forward_precompiles(node), boa.reverts():
        reader.usdc(USER)


def test_close_removes_the_precompiles(node):
    boa.reset_env()
    FakeNode.replies[pc.L1_BLOCK_NUMBER] = encode(["uint64"], [5])
    reader = boa.loads(READER)
    live = forward_precompiles(node)
    assert reader.l1_block() == 5
    live.close()
    with boa.reverts():  # no precompile: the empty reply fails to decode
        reader.l1_block()
    assert len(FakeNode.calls) == 1


def test_a_transient_node_error_is_tried_again(node, monkeypatch):
    monkeypatch.setattr("hyper_vyper.testing.live.time.sleep", lambda s: None)
    boa.reset_env()
    FakeNode.replies[pc.L1_BLOCK_NUMBER] = encode(["uint64"], [9])
    FakeNode.transient = 2
    reader = boa.loads(READER)
    with forward_precompiles(node):
        assert reader.l1_block() == 9
    assert len(FakeNode.calls) == 3
