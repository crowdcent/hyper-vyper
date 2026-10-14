# pragma version 0.4.3
# SPDX-License-Identifier: MIT

"""
@title HyperEVM Amount Conversions
@notice Converts token amounts between the decimal systems of HyperEVM and
        HyperCore. A wrong unit is a common bridging error. A raw EVM amount in
        a CoreWriter action can be wrong by many orders of magnitude. Then Core
        moves a very small amount, or the action fails silently.

        Decimal systems:
        - EVM amount:  the ERC-20 amount (for example 18 decimals)
        - Core wei:    the HyperCore token unit (wei_decimals of the token)
        - Core sz:     the order size unit (sz_decimals of the token)
        - Perp USD:    USDC in the perp balance (6 decimals, while spot USDC has 8)
@dev All functions are internal. Import the module:

        from hyper_vyper import conversions

        core_amount: uint64 = conversions.evm_to_wei(token_index, evm_amount)

     Each token-index conversion reads the decimals from the token_info
     precompile. If your contract converts often, read the metadata once with
     checked_token_info and use evm_to_wei_with_info.
"""

from . import constants
from . import precompiles


@internal
@view
def _require_network():
    assert chain.id == constants.MAINNET_CHAIN_ID or chain.id == constants.TESTNET_CHAIN_ID, "Unsupported chain"


@internal
@view
def hype_token_index() -> uint64:
    """HYPE's HyperCore token index for the current chain."""
    self._require_network()
    if chain.id == constants.TESTNET_CHAIN_ID:
        return constants.HYPE_TOKEN_INDEX_TESTNET
    return constants.HYPE_TOKEN_INDEX_MAINNET


@internal
@view
def is_hype(token: uint64) -> bool:
    """Whether a token index is HYPE on the current chain. Reverts on other chains."""
    return token == self.hype_token_index()


@internal
@view
def usdc_address() -> address:
    """USDC's EVM contract address for the current chain."""
    self._require_network()
    if chain.id == constants.TESTNET_CHAIN_ID:
        return constants.USDC_TESTNET
    return constants.USDC_MAINNET


@internal
@view
def core_deposit_wallet() -> address:
    """Circle CoreDepositWallet for bridging USDC EVM -> Core on the current chain."""
    self._require_network()
    if chain.id == constants.TESTNET_CHAIN_ID:
        return constants.CORE_DEPOSIT_WALLET_TESTNET
    return constants.CORE_DEPOSIT_WALLET_MAINNET


@internal
@view
def system_address(token: uint64) -> address:
    """The system address for a token. Transferring ERC-20 tokens to this address
    bridges them EVM -> Core, and a send_asset to it returns them Core -> EVM."""
    if self.is_hype(token):
        return constants.HYPE_SYSTEM_ADDRESS
    return convert(
        convert(constants.BASE_SYSTEM_ADDRESS, uint160) + convert(token, uint160),
        address,
    )


# --- EVM amount <-> Core wei ---

@internal
@view
def checked_token_info(token: uint64) -> precompiles.TokenInfo:
    """token_info for a token index that fits in uint32.
    The Solidity library narrows it to uint32 and can read the wrong token. Reverts instead."""
    assert token <= convert(max_value(uint32), uint64), "Token index too large"
    return precompiles.token_info(token)


@internal
@view
def evm_to_wei(token: uint64, amount_evm: uint256) -> uint64:
    """Convert an EVM ERC-20 amount to a Core wei amount.
    Reverts if the token has no linked EVM contract (unless HYPE).
    WARNING: truncates. If amount_evm is smaller than one Core wei unit the
    result is 0, so callers bridging funds must reject zero results."""
    return self.evm_to_wei_with_info(token, self.checked_token_info(token), amount_evm)


@internal
@view
def evm_to_wei_with_info(token: uint64, info: precompiles.TokenInfo, amount_evm: uint256) -> uint64:
    """evm_to_wei with metadata that the caller already read with checked_token_info.
    Use it to avoid a second token_info read."""
    if info.evm_contract == empty(address):
        assert self.is_hype(token), "Token not linked to EVM"
        return convert(amount_evm // 10 ** constants.HYPE_EVM_EXTRA_DECIMALS, uint64)

    if info.evm_extra_wei_decimals == 0:
        return convert(amount_evm, uint64)
    if info.evm_extra_wei_decimals > 0:
        return convert(
            amount_evm // 10 ** convert(info.evm_extra_wei_decimals, uint256),
            uint64,
        )
    return convert(
        amount_evm * 10 ** convert(-info.evm_extra_wei_decimals, uint256),
        uint64,
    )


@internal
@view
def wei_to_evm(token: uint64, amount_wei: uint64) -> uint256:
    """Convert a Core wei amount to an EVM ERC-20 amount.
    Reverts if the token has no linked EVM contract (unless HYPE).
    Truncates when EVM has fewer decimals than Core (for example USDC: 8 -> 6)."""
    info: precompiles.TokenInfo = self.checked_token_info(token)
    if info.evm_contract == empty(address):
        assert self.is_hype(token), "Token not linked to EVM"
        return convert(amount_wei, uint256) * 10 ** constants.HYPE_EVM_EXTRA_DECIMALS

    if info.evm_extra_wei_decimals == 0:
        return convert(amount_wei, uint256)
    if info.evm_extra_wei_decimals > 0:
        return convert(amount_wei, uint256) * 10 ** convert(info.evm_extra_wei_decimals, uint256)
    return convert(amount_wei, uint256) // 10 ** convert(-info.evm_extra_wei_decimals, uint256)


# --- Core sz (order size) <-> Core wei ---

@internal
@view
def sz_to_wei(token: uint64, sz: uint64) -> uint64:
    """Convert an order size (sz_decimals) to a Core wei amount (wei_decimals)."""
    info: precompiles.TokenInfo = self.checked_token_info(token)
    return sz * convert(
        10 ** convert(info.wei_decimals - info.sz_decimals, uint256),
        uint64,
    )


@internal
@view
def wei_to_sz(token: uint64, amount_wei: uint64) -> uint64:
    """Convert a Core wei amount (wei_decimals) to an order size (sz_decimals). Truncates."""
    info: precompiles.TokenInfo = self.checked_token_info(token)
    return amount_wei // convert(
        10 ** convert(info.wei_decimals - info.sz_decimals, uint256),
        uint64,
    )


# --- USDC spot wei (8 decimals) <-> perp USD (6 decimals) ---

@internal
@pure
def wei_to_perp(amount_wei: uint64) -> uint64:
    """Convert USDC spot wei (8 decimals) to perp USD (6 decimals). Truncates."""
    return amount_wei // 100


@internal
@pure
def perp_to_wei(perp_amount: uint64) -> uint64:
    """Convert perp USD (6 decimals) to USDC spot wei (8 decimals)."""
    return perp_amount * 100


# --- Spot market index <-> order asset ID ---

@internal
@pure
def spot_to_asset_id(spot_index: uint64) -> uint32:
    """Asset ID used in limit orders for a spot market (spot_index + 10000)."""
    return convert(spot_index + constants.SPOT_ASSET_OFFSET, uint32)


@internal
@pure
def asset_to_spot_id(asset: uint64) -> uint64:
    """Spot market index from an order asset ID.
    Assumes a spot asset ID (spot index + 10000). For other asset IDs the result
    has no meaning."""
    return asset - constants.SPOT_ASSET_OFFSET


# --- Token address -> Core token index ---

interface TokenRegistry:
    def getTokenIndex(evmContract: address) -> uint32: view


@internal
@view
def token_index(token_address: address) -> uint64:
    """HyperCore token index for a linked EVM contract address.
    The chain's USDC ERC-20 maps to index 0. Other addresses are looked up in the
    TokenRegistry, which reverts with TokenNotFound(address) if unregistered.
    Anyone can write to the registry, so the result is checked against token_info.
    Index 0 is only returned for the USDC token itself. The registry also maps the
    CoreDepositWallet to 0, because Core links USDC to it, but it is not a token."""
    if token_address == self.usdc_address():
        return constants.USDC_TOKEN_INDEX
    index: uint64 = convert(
        staticcall TokenRegistry(constants.TOKEN_REGISTRY).getTokenIndex(token_address), uint64
    )
    assert index != constants.USDC_TOKEN_INDEX, "Registry mismatch"
    assert self.checked_token_info(index).evm_contract == token_address, "Registry mismatch"
    return index


# --- Misc ---

@internal
@pure
def is_usdc(token: uint64) -> bool:
    """Whether a token index is USDC (index 0 on every chain)."""
    return token == constants.USDC_TOKEN_INDEX


@internal
@pure
def to_milliseconds(timestamp: uint64) -> uint64:
    """Seconds to milliseconds, the unit of HyperCore timestamps (for example vault locks).
    Reverts on overflow."""
    return timestamp * 1000
