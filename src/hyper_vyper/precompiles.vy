# pragma version 0.4.3
# SPDX-License-Identifier: MIT

"""
@title HyperEVM Precompile Reader
@notice Typed Vyper wrappers for HyperEVM read precompiles.
        Precompiles return HyperCore state as of the start of the current EVM block,
        so CoreWriter actions are never visible to precompiles in the same block.
        Gas cost: 2000 + 65 * (input_len + output_len) per call.
@dev All functions are internal so this file can be imported as a module:

        from hyper_vyper import precompiles

        bal: precompiles.SpotBalance = precompiles.spot_balance(user, token)

     Dynamic responses (token_info, token_supply, delegations, perp_asset_info,
     spot_info) are decoded into bounded types. If a response exceeds the bound,
     the call reverts. The constants below set the limits.

     Reply length: a read with a fixed-size reply reverts if the reply is longer
     than expected. If the precompile format changes, these reads stop working,
     so a contract that holds funds needs an upgrade or escape path. A read with
     a variable-length reply accepts trailing bytes up to the decode bound of its
     type.

     Gas: a failed precompile read consumes its whole gas cap (SMALL_READ_GAS or
     LARGE_READ_GAS), which can use most of a small block's gas.
     spot_index_for_token and spot_index_for_pair read spot_info for each market
     of the token, up to MAX_SPOT_MARKETS reads.
"""

from . import constants

# Decode bounds for dynamic precompile responses
MAX_NAME: constant(uint256) = 64
MAX_SPOT_MARKETS: constant(uint256) = 256
MAX_DELEGATIONS: constant(uint256) = 64
MAX_NON_CIRCULATING: constant(uint256) = 256

# Reply buffers. LARGE_REPLY fits the largest token_info, token_supply or
# delegations reply within the decode bounds above, with the outer ABI tuple
# offset. SMALL_REPLY fits every other reply.
SMALL_REPLY: constant(uint256) = 1024
LARGE_REPLY: constant(uint256) = 16608

# Gas caps for one read, with headroom for the largest reply (see the read cost
# in the module docstring). A read never forwards all gas.
SMALL_READ_GAS: constant(uint256) = 75_000
LARGE_READ_GAS: constant(uint256) = 1_100_000


struct SpotBalance:
    total: uint64
    hold: uint64
    entry_ntl: uint64


struct Position:
    szi: int64
    entry_ntl: uint64
    isolated_raw_usd: int64
    leverage: uint32
    is_isolated: bool


struct UserVaultEquity:
    equity: uint64
    locked_until_timestamp: uint64


struct DelegatorSummary:
    delegated: uint64
    undelegated: uint64
    total_pending_withdrawal: uint64
    n_pending_withdrawals: uint64


struct Delegation:
    validator: address
    amount: uint64
    locked_until_timestamp: uint64


struct PerpAssetInfo:
    coin: String[MAX_NAME]
    margin_table_id: uint32
    sz_decimals: uint8
    max_leverage: uint8
    only_isolated: bool


struct SpotInfo:
    name: String[MAX_NAME]
    tokens: uint64[2]


struct TokenInfo:
    name: String[MAX_NAME]
    spots: DynArray[uint64, MAX_SPOT_MARKETS]
    deployer_trading_fee_share: uint64
    deployer: address
    evm_contract: address
    sz_decimals: uint8
    wei_decimals: uint8
    evm_extra_wei_decimals: int8


struct UserBalance:
    user: address
    balance: uint64


struct TokenSupply:
    max_supply: uint64
    total_supply: uint64
    circulating_supply: uint64
    future_emissions: uint64
    non_circulating_user_balances: DynArray[UserBalance, MAX_NON_CIRCULATING]


struct AccountMarginSummary:
    account_value: int64
    margin_used: uint64
    ntl_pos: uint64
    raw_usd: int64


struct Bbo:
    bid: uint64
    ask: uint64


struct BasisAndValue:
    basis: uint64
    value: uint64


struct BorrowLendUserTokenState:
    borrow: BasisAndValue
    supply: BasisAndValue


struct BorrowLendReserveState:
    borrow_yearly_rate_bps: uint64
    supply_yearly_rate_bps: uint64
    balance: uint64
    utilization_bps: uint64
    oracle_px: uint64
    ltv_bps: uint64
    total_supplied: uint64
    total_borrowed: uint64


@internal
@view
def _call(addr: address, data: Bytes[64]) -> Bytes[SMALL_REPLY]:
    return raw_call(addr, data, max_outsize=SMALL_REPLY, gas=SMALL_READ_GAS, is_static_call=True)


@internal
@view
def _call_big(addr: address, data: Bytes[64]) -> Bytes[LARGE_REPLY]:
    return raw_call(addr, data, max_outsize=LARGE_REPLY, gas=LARGE_READ_GAS, is_static_call=True)


# --- Price feeds ---

@internal
@view
def mark_px(perp_index: uint32) -> uint64:
    """Perp mark price. Divide by 10**(6 - sz_decimals) for the price in USD."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.MARK_PX_PRECOMPILE,
        abi_encode(perp_index),
    )
    return abi_decode(response, uint64)


@internal
@view
def oracle_px(perp_index: uint32) -> uint64:
    """Perp oracle price. Divide by 10**(6 - sz_decimals) for the price in USD."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.ORACLE_PX_PRECOMPILE,
        abi_encode(perp_index),
    )
    return abi_decode(response, uint64)


@internal
@view
def spot_px(spot_index: uint64) -> uint64:
    """Spot price. Divide by 10**(8 - sz_decimals of the base token) for the price."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.SPOT_PX_PRECOMPILE,
        abi_encode(spot_index),
    )
    return abi_decode(response, uint64)


@internal
@view
def bbo(asset: uint64) -> Bbo:
    """Best bid and offer for an asset."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.BBO_PRECOMPILE,
        abi_encode(asset),
    )
    return abi_decode(response, Bbo)


# --- Balances & positions ---

@internal
@view
def spot_balance(user: address, token: uint64) -> SpotBalance:
    """Spot balance of a token for a user."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.SPOT_BALANCE_PRECOMPILE,
        abi_encode(user, token),
    )
    return abi_decode(response, SpotBalance)


@internal
@view
def position(user: address, perp_index: uint32) -> Position:
    """Perp position for a user."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.POSITION2_PRECOMPILE,
        abi_encode(user, perp_index),
    )
    return abi_decode(response, Position)


@internal
@view
def withdrawable(user: address) -> uint64:
    """Withdrawable USDC amount for a user (perp USD, 6 decimals).
    In unified account or portfolio margin mode, Core can report the funds
    through spot instead of perp. No precompile reads the current mode.
    See core_writer.set_abstraction."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.WITHDRAWABLE_PRECOMPILE,
        abi_encode(user),
    )
    return abi_decode(response, uint64)


@internal
@view
def account_margin_summary(perp_dex_index: uint32, user: address) -> AccountMarginSummary:
    """Account margin summary for a user on a perp DEX.
    In unified account or portfolio margin mode, Core can report the funds
    through spot instead of perp. No precompile reads the current mode.
    See core_writer.set_abstraction."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.ACCOUNT_MARGIN_SUMMARY_PRECOMPILE,
        abi_encode(perp_dex_index, user),
    )
    return abi_decode(response, AccountMarginSummary)


# --- Vault ---

@internal
@view
def user_vault_equity(user: address, vault: address) -> UserVaultEquity:
    """User's equity in a HyperCore vault."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.VAULT_EQUITY_PRECOMPILE,
        abi_encode(user, vault),
    )
    return abi_decode(response, UserVaultEquity)


# --- Staking ---

@internal
@view
def delegator_summary(user: address) -> DelegatorSummary:
    """Staking delegator summary for a user."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.DELEGATOR_SUMMARY_PRECOMPILE,
        abi_encode(user),
    )
    return abi_decode(response, DelegatorSummary)


@internal
@view
def delegations(user: address) -> DynArray[Delegation, MAX_DELEGATIONS]:
    """All active delegations for a user."""
    response: Bytes[LARGE_REPLY] = self._call_big(
        constants.DELEGATIONS_PRECOMPILE,
        abi_encode(user),
    )
    return abi_decode(response, DynArray[Delegation, MAX_DELEGATIONS])


# --- Asset metadata ---

@internal
@view
def token_info(token: uint64) -> TokenInfo:
    """Token metadata: decimals, linked EVM contract, spot markets."""
    response: Bytes[LARGE_REPLY] = self._call_big(
        constants.TOKEN_INFO_PRECOMPILE,
        abi_encode(token),
    )
    return abi_decode(response, TokenInfo)


@internal
@view
def spot_info(spot_index: uint64) -> SpotInfo:
    """Spot market metadata: name and [base, quote] token indices."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.SPOT_INFO_PRECOMPILE,
        abi_encode(spot_index),
    )
    return abi_decode(response, SpotInfo)


@internal
@view
def perp_asset_info(perp_index: uint32) -> PerpAssetInfo:
    """Perp asset metadata: coin name, size decimals, max leverage."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.PERP_ASSET_INFO_PRECOMPILE,
        abi_encode(perp_index),
    )
    return abi_decode(response, PerpAssetInfo)


@internal
@view
def token_supply(token: uint64) -> TokenSupply:
    """Token supply breakdown including non-circulating balances."""
    response: Bytes[LARGE_REPLY] = self._call_big(
        constants.TOKEN_SUPPLY_PRECOMPILE,
        abi_encode(token),
    )
    return abi_decode(response, TokenSupply)


# --- Derived helpers ---

@internal
@view
def _find_spot_index(token: uint64, quote: uint64) -> (bool, uint64):
    # First of the token's spot markets quoted in `quote`, in token_info order.
    info: TokenInfo = self.token_info(token)
    for spot: uint64 in info.spots:
        market: SpotInfo = self.spot_info(spot)
        if market.tokens[1] == quote:
            return True, spot
    return False, 0


@internal
@view
def spot_index_for_token(token: uint64) -> uint64:
    """Spot market index for the token's USDC pair (quote token index 0).
    Reverts if no market is quoted in USDC, even if the token has only one market."""
    found: bool = False
    spot: uint64 = 0
    found, spot = self._find_spot_index(token, constants.USDC_TOKEN_INDEX)
    assert found, "No USDC spot market"
    return spot


@internal
@view
def spot_index_for_pair(token: uint64, quote: uint64) -> uint64:
    """Spot market index for the token's pair quoted in `quote` (a token index).
    Reverts if the token has no such market."""
    found: bool = False
    spot: uint64 = 0
    found, spot = self._find_spot_index(token, quote)
    assert found, "No spot market for pair"
    return spot


# --- Normalized prices ---

@internal
@view
def normalized_spot_px(spot_index: uint64) -> uint256:
    """Spot price with 8 decimals, in units of the market's quote token.
    Equals spot_px * 10**(sz_decimals of the base token). Reverts on overflow."""
    market: SpotInfo = self.spot_info(spot_index)
    sz_decimals: uint8 = self.token_info(market.tokens[0]).sz_decimals
    return convert(self.spot_px(spot_index), uint256) * 10 ** convert(sz_decimals, uint256)


@internal
@view
def normalized_mark_px(perp_index: uint32) -> uint256:
    """Perp mark price with 6 decimals (USD).
    Equals mark_px * 10**sz_decimals. Reverts on overflow."""
    sz_decimals: uint8 = self.perp_asset_info(perp_index).sz_decimals
    return convert(self.mark_px(perp_index), uint256) * 10 ** convert(sz_decimals, uint256)


@internal
@view
def normalized_oracle_px(perp_index: uint32) -> uint256:
    """Perp oracle price with 6 decimals (USD).
    Equals oracle_px * 10**sz_decimals. Reverts on overflow."""
    sz_decimals: uint8 = self.perp_asset_info(perp_index).sz_decimals
    return convert(self.oracle_px(perp_index), uint256) * 10 ** convert(sz_decimals, uint256)


# --- Borrow / lend ---

@internal
@view
def borrow_lend_user_state(user: address, token: uint64) -> BorrowLendUserTokenState:
    """A user's borrow and supply position for a token. Reverts for a user that has
    never supplied or borrowed, because the precompile fails. After the first use,
    a closed position reads as zeros."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.BORROW_LEND_USER_STATE_PRECOMPILE,
        abi_encode(user, token),
    )
    return abi_decode(response, BorrowLendUserTokenState)


@internal
@view
def borrow_lend_reserve_state(token: uint64) -> BorrowLendReserveState:
    """Borrow/lend reserve state for a token: rates (bps), balances and oracle price.
    Reverts for a token without borrow/lend state."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.BORROW_LEND_RESERVE_STATE_PRECOMPILE,
        abi_encode(token),
    )
    return abi_decode(response, BorrowLendReserveState)


# --- Chain state ---

@internal
@view
def l1_block_number() -> uint64:
    """Latest HyperCore L1 block number."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.L1_BLOCK_NUMBER_PRECOMPILE,
        b"",
    )
    return abi_decode(response, uint64)


@internal
@view
def core_user_exists(user: address) -> bool:
    """Whether a user has an activated HyperCore account.
    Returns false for an account that is not activated. HYPE and linked tokens
    sent to it go into an escrow that the precompiles do not show. An account that
    is not activated cannot send CoreWriter actions."""
    response: Bytes[SMALL_REPLY] = self._call(
        constants.CORE_USER_EXISTS_PRECOMPILE,
        abi_encode(user),
    )
    return abi_decode(response, bool)
