# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
# SPDX-License-Identifier: MIT

"""
@title Spot round trip example
@notice Moves USDC from EVM to Core spot and back. The testing quick start
        runs it against the HyperCore simulator.
@dev An example for the documentation. Nobody has audited it. It has no
     access control. Do not deploy it with real funds.
"""

from ethereum.ercs import IERC20

from hyper_vyper import bridge
from hyper_vyper import constants
from hyper_vyper import conversions
from hyper_vyper import core_writer
from hyper_vyper import precompiles


@external
def deposit_to_spot(amount: uint256):
    """Send EVM USDC (6 decimals) to the Core spot balance of this contract."""
    bridge.bridge_usdc_to_core(amount, constants.SPOT_DEX)


@external
def move_to_perp(amount: uint64):
    """Move USDC from Core spot to perp. The amount is in perp units (6 decimals)."""
    core_writer.transfer_usd_class(amount, True)


@external
def return_from_spot(amount: uint256):
    """Return USDC (6 decimals) from Core spot to the EVM address of this contract."""
    bridge.bridge_usdc_to_evm(amount, constants.SPOT_DEX)


@external
@view
def core_spot_usdc() -> uint64:
    """Core spot USDC in 8-decimal units, as of the start of this block."""
    return precompiles.spot_balance(self, constants.USDC_TOKEN_INDEX).total


@external
@view
def evm_usdc() -> uint256:
    """EVM USDC in 6-decimal units."""
    return staticcall IERC20(conversions.usdc_address()).balanceOf(self)
