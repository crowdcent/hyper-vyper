"""Answer HyperCore read precompiles from a live node, for Titanoboa fork and network mode.

Titanoboa runs every call on a local copy of the chain first, and that copy has no
HyperCore precompiles (0x0800 to 0x0813). `forward_precompiles` registers each of
them as a raw precompile that sends the same input to the node with `eth_call`, so
a contract that reads HyperCore works in `boa.fork` and `boa.set_network_env`:

    import boa
    from hyper_vyper.testing import forward_precompiles

    with forward_precompiles(RPC_URL):
        boa.fork(RPC_URL)
        contract = boa.load("my_contract.vy")
        contract.core_usdc_balance(user)  # the live Core balance

The node answers with the HyperCore state at its latest block, not at the block of
the fork. The testing quick start in the docs explains the warning that network mode
prints.
"""

from __future__ import annotations

import time

from boa.rpc import EthereumRPC, RPCError
from eth.exceptions import Revert
from requests import RequestException

from hyper_vyper.testing import _precompiles

MAINNET_RPC = "https://rpc.hyperliquid.xyz/evm"
TESTNET_RPC = "https://rpc.hyperliquid-testnet.xyz/evm"


class RetryingRPC(EthereumRPC):
    """Titanoboa's JSON-RPC client with retries. It retries after a temporary error: a
    rate limit, a dropped connection, or a node behind the load balancer that does not
    have the newest block yet. It never retries a revert."""

    def __init__(self, url: str, attempts: int = 6):
        super().__init__(url)
        self.attempts = attempts

    def fetch(self, method, params):
        for attempt in range(self.attempts):
            try:
                return super().fetch(method, params)
            except RPCError as exc:
                if "revert" in str(exc).lower() or attempt == self.attempts - 1:
                    raise
            except RequestException:  # includes HTTP 429 and timeouts
                if attempt == self.attempts - 1:
                    raise
            time.sleep(min(2**attempt, 8))

    def fetch_multi(self, payloads):
        return [self.fetch(method, params) for method, params in payloads]


class _LivePrecompiles:
    """The registered precompiles. Call `close` (or leave the `with` block) to remove them."""

    def __init__(self, rpc: str | EthereumRPC):
        self.rpc = RetryingRPC(rpc) if isinstance(rpc, str) else rpc
        self.calls = 0
        _precompiles.register(self._handler)

    def close(self) -> None:
        _precompiles.deregister()

    def __enter__(self) -> _LivePrecompiles:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def eth_call(self, to: str, data: bytes) -> bytes:
        """The node's reply. A revert on the node raises `Revert`."""
        try:
            reply = self.rpc.fetch("eth_call", [{"to": to, "data": "0x" + data.hex()}, "latest"])
        except RPCError as exc:
            if "revert" in str(exc).lower():
                raise Revert(str(exc).encode()) from None
            raise
        self.calls += 1
        return bytes.fromhex(reply.removeprefix("0x"))

    def _handler(self, suffix: int):
        address = _precompiles.address(suffix)

        def handler(computation):
            data = computation.msg.data_as_bytes
            reply = self.eth_call(address, data)
            computation.consume_gas(_precompiles.read_gas(data, reply), "HyperCore read")
            computation.output = reply
            return computation

        return handler


def forward_precompiles(rpc: str | EthereumRPC) -> _LivePrecompiles:
    """Answer the HyperCore read precompiles from a node. `rpc` is the node's URL, or a
    Titanoboa RPC object to share with `boa.fork` or `NetworkEnv`."""
    return _LivePrecompiles(rpc)
