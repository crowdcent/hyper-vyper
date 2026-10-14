# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
# SPDX-License-Identifier: MIT

"""
@title Tutorial: read HyperCore state
@notice Reads the Core balances and the perp account of any address, and the
        prices of one perp market. It has no storage and no write functions.
@dev Tutorial code. Nobody has audited it.
"""

from hyper_vyper import constants
from hyper_vyper import conversions
from hyper_vyper import precompiles


struct UserView:
    evm_block: uint256
    l1_block: uint64
    core_exists: bool
    spot_usdc: precompiles.SpotBalance  # Core USDC, 8 decimals
    spot_hype: precompiles.SpotBalance  # Core HYPE, 8 decimals
    perp: precompiles.AccountMarginSummary  # perp USD, 6 decimals
    withdrawable: uint64  # perp USD, 6 decimals


struct PerpView:
    evm_block: uint256
    coin: String[64]
    sz_decimals: uint8
    mark_px: uint64  # divide by 10 ** (6 - sz_decimals)
    oracle_px: uint64  # divide by 10 ** (6 - sz_decimals)


@external
@view
def read_user(user: address) -> UserView:
    """All Core reads for one address, from one call. They share one EVM block."""
    return UserView(
        evm_block=block.number,
        l1_block=precompiles.l1_block_number(),
        core_exists=precompiles.core_user_exists(user),
        spot_usdc=precompiles.spot_balance(user, constants.USDC_TOKEN_INDEX),
        spot_hype=precompiles.spot_balance(user, conversions.hype_token_index()),
        perp=precompiles.account_margin_summary(constants.DEFAULT_PERP_DEX, user),
        withdrawable=precompiles.withdrawable(user),
    )


@external
@view
def read_perp(perp: uint32) -> PerpView:
    """The name, size decimals, mark price and oracle price of one perp market."""
    info: precompiles.PerpAssetInfo = precompiles.perp_asset_info(perp)
    return PerpView(
        evm_block=block.number,
        coin=info.coin,
        sz_decimals=info.sz_decimals,
        mark_px=precompiles.mark_px(perp),
        oracle_px=precompiles.oracle_px(perp),
    )
