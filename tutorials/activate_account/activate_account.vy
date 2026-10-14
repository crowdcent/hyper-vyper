# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
# SPDX-License-Identifier: MIT

"""
@title Tutorial: activate the Core account of a contract
@notice A new contract has a HyperCore account that is not activated. This
        contract shows the account before and after activation. It can also send
        HYPE to Core before activation, to show the escrow.
@dev Tutorial code. Nobody has audited it.
"""

from hyper_vyper import bridge
from hyper_vyper import constants
from hyper_vyper import conversions
from hyper_vyper import core_writer
from hyper_vyper import precompiles


struct Status:
    evm_block: uint256
    core_exists: bool
    spot_usdc: uint64  # Core USDC, 8 decimals
    spot_hype: uint64  # Core HYPE, 8 decimals


OWNER: public(immutable(address))


@deploy
def __init__():
    OWNER = msg.sender


@internal
@view
def _only_owner():
    assert msg.sender == OWNER, "Only the owner"


@external
@view
def status() -> Status:
    """The precompile view of this account. It never shows escrow, and core_exists
    stays false until activation."""
    return Status(
        evm_block=block.number,
        core_exists=precompiles.core_user_exists(self),
        spot_usdc=precompiles.spot_balance(self, constants.USDC_TOKEN_INDEX).total,
        spot_hype=precompiles.spot_balance(self, conversions.hype_token_index()).total,
    )


@external
@payable
def hype_to_core():
    """Send the HYPE of this call (18 decimals) to the Core account of this contract.
    Before activation, Core holds it in an escrow. Activation moves it to spot."""
    self._only_owner()
    bridge.bridge_hype_to_core(msg.value)


@external
def sweep(token: uint64, amount_wei: uint64):
    """Send Core spot funds of this contract to the owner on Core (cleanup).
    amount_wei is in Core wei: 8 decimals for USDC and for HYPE."""
    self._only_owner()
    assert precompiles.core_user_exists(self), "Core account not activated"
    core_writer.send_asset(
        OWNER, empty(address), constants.SPOT_DEX, constants.SPOT_DEX, token, amount_wei
    )
