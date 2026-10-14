"""Test helpers for contracts that use hyper_vyper. Needs the `testing` extra.

`CoreSim` is a small, deterministic HyperCore simulator for Titanoboa tests.
The testing quick start in the docs lists what it models and what it leaves
out. `forward_precompiles` answers the HyperCore read precompiles from a live
node instead, for Titanoboa fork and network mode.
"""

from hyper_vyper.testing.live import forward_precompiles
from hyper_vyper.testing.sim import (
    CORE_WRITER,
    HYPE_SYSTEM,
    HYPE_TOKEN,
    SPOT_DEX,
    USDC,
    USDC_TOKEN,
    WALLET,
    CoreSim,
    Policy,
    live_reply,
    system_address,
)

__all__ = [
    "CORE_WRITER",
    "HYPE_SYSTEM",
    "HYPE_TOKEN",
    "SPOT_DEX",
    "USDC",
    "USDC_TOKEN",
    "WALLET",
    "CoreSim",
    "Policy",
    "forward_precompiles",
    "live_reply",
    "system_address",
]
