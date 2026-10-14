# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
# SPDX-License-Identifier: MIT

"""
@title Tutorial: place IOC spot and perp orders
@notice The owner buys or sells HYPE for USDC on the Core spot market of
        testnet, and opens and closes a small BTC perp position, with
        immediate-or-cancel (IOC) limit orders.
@dev Tutorial code. Nobody has audited it. The markets are fixed: testnet spot
     market 1035 (HYPE/USDC) and testnet perp 3 (BTC). On mainnet the markets
     have other indices.
"""

from hyper_vyper import constants
from hyper_vyper import conversions
from hyper_vyper import core_writer
from hyper_vyper import precompiles


struct Status:
    evm_block: uint256
    core_exists: bool
    spot_usdc: uint64  # Core USDC, 8 decimals
    spot_hype: uint64  # Core HYPE, 8 decimals
    spot_hype_hold: uint64
    withdrawable: uint64  # perp USD, 6 decimals
    btc_szi: int64  # BTC position size, signed, in units of 10**-sz_decimals BTC
    btc_entry_ntl: uint64  # perp USD, 6 decimals


event OrderSubmitted:
    is_buy: bool
    limit_px: uint64
    sz: uint64


HYPE_USDC_SPOT_INDEX: constant(uint64) = 1035  # testnet
HYPE_USDC_ASSET: constant(uint32) = 11035  # 10000 + spot index
BTC_PERP: constant(uint32) = 3  # testnet. A perp's asset ID is its perp index.

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
    hype: precompiles.SpotBalance = precompiles.spot_balance(self, conversions.hype_token_index())
    btc: precompiles.Position = precompiles.position(self, BTC_PERP)
    return Status(
        evm_block=block.number,
        core_exists=precompiles.core_user_exists(self),
        spot_usdc=usdc.total,
        spot_hype=hype.total,
        spot_hype_hold=hype.hold,
        withdrawable=precompiles.withdrawable(self),
        btc_szi=btc.szi,
        btc_entry_ntl=btc.entry_ntl,
    )


@external
@view
def market() -> precompiles.SpotInfo:
    """The name and [base, quote] tokens of the market. Expect [1105, 0]."""
    return precompiles.spot_info(HYPE_USDC_SPOT_INDEX)


@external
@view
def perp_market() -> precompiles.PerpAssetInfo:
    """The name, size decimals and max leverage of the perp. Expect "BTC"."""
    return precompiles.perp_asset_info(BTC_PERP)


@external
def move_usdc(ntl: uint64, to_perp: bool):
    """Move ntl perp USD (6 decimals) between Core spot and Core perp."""
    self._only_owner()
    assert precompiles.core_user_exists(self), "Core account not activated"
    assert ntl > 0, "Zero amount"
    core_writer.transfer_usd_class(ntl, to_perp)


@external
def place_perp_ioc(is_buy: bool, limit_px: uint64, sz: uint64, reduce_only: bool):
    """Place an IOC limit order on the BTC perp. limit_px and sz are 10 ** 8 times
    the human values. A reduce-only order can only make the position smaller."""
    self._only_owner()
    assert chain.id == constants.TESTNET_CHAIN_ID, "Testnet market only"
    assert precompiles.core_user_exists(self), "Core account not activated"
    assert limit_px > 0 and sz > 0, "Zero price or size"
    core_writer.place_limit_order(BTC_PERP, is_buy, limit_px, sz, reduce_only, constants.TIF_IOC, 0)
    log OrderSubmitted(is_buy=is_buy, limit_px=limit_px, sz=sz)


@external
def place_ioc(is_buy: bool, limit_px: uint64, sz: uint64):
    """Place an IOC limit order. limit_px and sz are 10 ** 8 times the human values.
    The caller rounds them to the tick and lot rules of the market. Core rejects
    a bad order silently. The EVM transaction succeeds."""
    self._only_owner()
    assert chain.id == constants.TESTNET_CHAIN_ID, "Testnet market only"
    assert precompiles.core_user_exists(self), "Core account not activated"
    assert limit_px > 0 and sz > 0, "Zero price or size"
    core_writer.place_limit_order(
        HYPE_USDC_ASSET, is_buy, limit_px, sz, False, constants.TIF_IOC, 0
    )
    log OrderSubmitted(is_buy=is_buy, limit_px=limit_px, sz=sz)


@external
def sweep(token: uint64, amount_wei: uint64):
    """Send Core spot funds of this contract to the owner on Core (cleanup).
    amount_wei is in Core wei: 8 decimals for USDC and for HYPE."""
    self._only_owner()
    assert precompiles.core_user_exists(self), "Core account not activated"
    core_writer.send_asset(
        OWNER, empty(address), constants.SPOT_DEX, constants.SPOT_DEX, token, amount_wei
    )
