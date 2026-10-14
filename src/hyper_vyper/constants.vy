# pragma version 0.4.3
# SPDX-License-Identifier: MIT

"""
@title HyperEVM Constants
@notice Addresses, CoreWriter action headers, chain IDs, token indices and enum
        values for HyperEVM and HyperCore.
@dev The values come from HLConstants.sol, PrecompileLib.sol and
     CoreWriterLib.sol in hyper-evm-lib at the pinned commit. Import the module
     and use its names:

        from hyper_vyper import constants

        core_writer.place_limit_order(asset, True, px, sz, False, constants.TIF_GTC, 0)
"""

# CoreWriter system contract
CORE_WRITER: constant(address) = 0x3333333333333333333333333333333333333333

# Read precompile addresses (0x0800 - 0x0813)
# 0x0800 is the legacy position precompile. It stays here for completeness only.
# The library reads POSITION2 (0x0813).
POSITION_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000800
SPOT_BALANCE_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000801
VAULT_EQUITY_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000802
WITHDRAWABLE_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000803
DELEGATIONS_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000804
DELEGATOR_SUMMARY_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000805
MARK_PX_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000806
ORACLE_PX_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000807
SPOT_PX_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000808
L1_BLOCK_NUMBER_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000809
PERP_ASSET_INFO_PRECOMPILE: constant(address) = 0x000000000000000000000000000000000000080a
SPOT_INFO_PRECOMPILE: constant(address) = 0x000000000000000000000000000000000000080b
TOKEN_INFO_PRECOMPILE: constant(address) = 0x000000000000000000000000000000000000080C
TOKEN_SUPPLY_PRECOMPILE: constant(address) = 0x000000000000000000000000000000000000080D
BBO_PRECOMPILE: constant(address) = 0x000000000000000000000000000000000000080e
ACCOUNT_MARGIN_SUMMARY_PRECOMPILE: constant(address) = 0x000000000000000000000000000000000000080F
CORE_USER_EXISTS_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000810
BORROW_LEND_USER_STATE_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000811
BORROW_LEND_RESERVE_STATE_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000812
POSITION2_PRECOMPILE: constant(address) = 0x0000000000000000000000000000000000000813

# System addresses
HYPE_SYSTEM_ADDRESS: constant(address) = 0x2222222222222222222222222222222222222222
BASE_SYSTEM_ADDRESS: constant(address) = 0x2000000000000000000000000000000000000000

# Token registry: an on-chain map from EVM contract address to HyperCore token index.
# Entries come from precompile data, but anyone can write them, and an entry can be
# stale. conversions.token_index checks each answer against token_info.
# See TokenRegistry in hyper-evm-lib.
TOKEN_REGISTRY: constant(address) = 0x0b51d1A9098cf8a72C325003F44C194D41d7A85B

# Core deposit wallet (Circle) for bridging USDC EVM -> Core
CORE_DEPOSIT_WALLET_MAINNET: constant(address) = 0x6B9E773128f453f5c2C60935Ee2DE2CBc5390A24
CORE_DEPOSIT_WALLET_TESTNET: constant(address) = 0x0B80659a4076E9E93C7DbE0f10675A16a3e5C206

# USDC
USDC_MAINNET: constant(address) = 0xb88339CB7199b77E23DB6E890353E22632Ba630f
USDC_TESTNET: constant(address) = 0x2B3370eE501B4a559b57D449569354196457D8Ab
USDC_TOKEN_INDEX: constant(uint64) = 0

# HYPE, the native gas token. Its token index differs by chain.
HYPE_TOKEN_INDEX_MAINNET: constant(uint64) = 150
HYPE_TOKEN_INDEX_TESTNET: constant(uint64) = 1105
HYPE_EVM_EXTRA_DECIMALS: constant(uint256) = 10

# Chain IDs
MAINNET_CHAIN_ID: constant(uint256) = 999
TESTNET_CHAIN_ID: constant(uint256) = 998

# CoreWriter action headers (version 0x01 + 3-byte action ID, packed)
# Format: 0x01XXYYZZ where XXYYZZ is the action ID as big-endian uint24
LIMIT_ORDER_HEADER: constant(bytes4) = 0x01000001
VAULT_TRANSFER_HEADER: constant(bytes4) = 0x01000002
TOKEN_DELEGATE_HEADER: constant(bytes4) = 0x01000003
STAKING_DEPOSIT_HEADER: constant(bytes4) = 0x01000004
STAKING_WITHDRAW_HEADER: constant(bytes4) = 0x01000005
SPOT_SEND_HEADER: constant(bytes4) = 0x01000006
USD_CLASS_TRANSFER_HEADER: constant(bytes4) = 0x01000007
FINALIZE_EVM_CONTRACT_HEADER: constant(bytes4) = 0x01000008
ADD_API_WALLET_HEADER: constant(bytes4) = 0x01000009
CANCEL_ORDER_BY_OID_HEADER: constant(bytes4) = 0x0100000a
CANCEL_ORDER_BY_CLOID_HEADER: constant(bytes4) = 0x0100000b
APPROVE_BUILDER_FEE_HEADER: constant(bytes4) = 0x0100000c
SEND_ASSET_HEADER: constant(bytes4) = 0x0100000d
BORROW_LEND_HEADER: constant(bytes4) = 0x0100000f
SET_ABSTRACTION_HEADER: constant(bytes4) = 0x01000010

# Limit order time-in-force (tif of core_writer.place_limit_order)
TIF_ALO: constant(uint8) = 1
TIF_GTC: constant(uint8) = 2
TIF_IOC: constant(uint8) = 3

# Borrow/lend operations (operation of core_writer.borrow_lend)
BLP_SUPPLY: constant(uint8) = 0
BLP_WITHDRAW: constant(uint8) = 1

# Account abstraction modes (abstraction of core_writer.set_abstraction)
ABSTRACTION_DISABLED: constant(uint8) = 1
ABSTRACTION_UNIFIED_ACCOUNT: constant(uint8) = 2
ABSTRACTION_PORTFOLIO_MARGIN: constant(uint8) = 3

# DEX indices for send_asset and the USDC bridge functions
SPOT_DEX: constant(uint32) = max_value(uint32)
DEFAULT_PERP_DEX: constant(uint32) = 0

# Spot market index -> order asset ID offset (asset = spot_index + 10000)
SPOT_ASSET_OFFSET: constant(uint64) = 10_000
