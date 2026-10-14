# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
# SPDX-License-Identifier: MIT

"""
@title Tutorial: move USDC between Core spot and perp
@notice The owner moves USDC between the spot balance and the perp balance of
        this contract on HyperCore. Spot USDC has 8 decimals. Perp USD has 6.
@dev Tutorial code. Nobody has audited it.
"""

from hyper_vyper import constants
from hyper_vyper import conversions
from hyper_vyper import core_writer
from hyper_vyper import precompiles


struct Status:
    evm_block: uint256
    core_exists: bool
    spot_usdc: uint64  # Core USDC, 8 decimals
    spot_usdc_hold: uint64  # Core USDC, 8 decimals
    spot_hype: uint64  # Core HYPE, 8 decimals
    perp_account_value: int64  # perp USD, 6 decimals
    withdrawable: uint64  # perp USD, 6 decimals


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
    usdc: precompiles.SpotBalance = precompiles.spot_balance(self, constants.USDC_TOKEN_INDEX)
    perp: precompiles.AccountMarginSummary = precompiles.account_margin_summary(
        constants.DEFAULT_PERP_DEX, self
    )
    return Status(
        evm_block=block.number,
        core_exists=precompiles.core_user_exists(self),
        spot_usdc=usdc.total,
        spot_usdc_hold=usdc.hold,
        spot_hype=precompiles.spot_balance(self, conversions.hype_token_index()).total,
        perp_account_value=perp.account_value,
        withdrawable=precompiles.withdrawable(self),
    )


@external
def move_usdc(ntl: uint64, to_perp: bool):
    """Move ntl perp USD (6 decimals) from spot to perp (to_perp) or back.
    Core debits ntl * 100 Core wei (8 decimals) from spot for a move to perp.
    A move that Core rejects fails silently. The EVM transaction succeeds."""
    self._only_owner()
    assert precompiles.core_user_exists(self), "Core account not activated"
    assert ntl > 0, "Zero amount"
    core_writer.transfer_usd_class(ntl, to_perp)


@external
def sweep(token: uint64, amount_wei: uint64):
    """Send Core spot funds of this contract to the owner on Core (cleanup).
    amount_wei is in Core wei: 8 decimals for USDC and for HYPE."""
    self._only_owner()
    assert precompiles.core_user_exists(self), "Core account not activated"
    core_writer.send_asset(
        OWNER, empty(address), constants.SPOT_DEX, constants.SPOT_DEX, token, amount_wei
    )
