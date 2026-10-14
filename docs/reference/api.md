# API

All library functions are `@internal` and stateless. You import the modules you
need into your Vyper contract, so there is no separate library to deploy.

The compiler removes any internal function that your contract doesn't call, and
a test checks that unused imports don't change the runtime bytecode of a small
contract.

## `precompiles`: reads

| Function | Returns |
|---|---|
| `spot_balance(user: address, token: uint64)` | `SpotBalance(total, hold, entry_ntl)` |
| `position(user: address, perp_index: uint32)` | `Position(szi, entry_ntl, isolated_raw_usd, leverage, is_isolated)`. Reads `0x0813`. |
| `account_margin_summary(perp_dex_index: uint32, user: address)` | `AccountMarginSummary(account_value, margin_used, ntl_pos, raw_usd)`. `account_value` and `raw_usd` are signed. |
| `withdrawable(user: address)` | `uint64`: withdrawable USDC |
| `user_vault_equity(user: address, vault: address)` | `UserVaultEquity(equity, locked_until_timestamp)`. The time is in milliseconds. |
| `core_user_exists(user: address)` | `bool` |
| `mark_px(perp_index: uint32)`, `oracle_px(perp_index: uint32)` | `uint64`: raw price. Divide by `10**(6 - sz_decimals)`. |
| `spot_px(spot_index: uint64)` | `uint64`: raw price. Divide by `10**(8 - base_sz_decimals)`, where `base_sz_decimals` is the `sz_decimals` of the base token. |
| `bbo(asset: uint64)` | `Bbo(bid, ask)`: raw prices |
| `l1_block_number()` | `uint64`: Core block number |
| `delegator_summary(user: address)` | `DelegatorSummary(delegated, undelegated, total_pending_withdrawal, n_pending_withdrawals)` |
| `delegations(user: address)` | A maximum of 64 `Delegation(validator, amount, locked_until_timestamp)` entries |
| `perp_asset_info(perp_index: uint32)` | `PerpAssetInfo(coin, margin_table_id, sz_decimals, max_leverage, only_isolated)` |
| `spot_info(spot_index: uint64)` | `SpotInfo(name, tokens)`. `tokens` is `[base, quote]`. |
| `token_info(token: uint64)` | `TokenInfo`: name, spot markets, deployer fee share, deployer, linked EVM address and three decimal values |
| `token_supply(token: uint64)` | `TokenSupply`: maximum, total and circulating supply, future emissions and non-circulating balances |
| `spot_index_for_token(token: uint64)` | `uint64`: the first spot market of the token with USDC as quote. Reverts `"No USDC spot market"` if there is none. |
| `spot_index_for_pair(token: uint64, quote: uint64)` | `uint64`: the first spot market of the token with `quote` as quote token. Reverts `"No spot market for pair"` if there is none. |
| `normalized_spot_px(spot_index: uint64)` | `uint256`: spot price with 8 decimals, in units of the quote token |
| `normalized_mark_px(perp_index: uint32)`, `normalized_oracle_px(perp_index: uint32)` | `uint256`: perp price in USD with 6 decimals |
| `borrow_lend_user_state(user: address, token: uint64)` | `BorrowLendUserTokenState(borrow, supply)`. Each is a `BasisAndValue(basis, value)`. Reads `0x0811`. |
| `borrow_lend_reserve_state(token: uint64)` | `BorrowLendReserveState(borrow_yearly_rate_bps, supply_yearly_rate_bps, balance, utilization_bps, oracle_px, ltv_bps, total_supplied, total_borrowed)`. Reads `0x0812`. |

`spot_index_for_token` always checks the quote token.
[Finding a market](../modules/precompiles.md#finding-a-market) explains why.

The two borrow/lend reads revert when the token or the user has no
borrow/lend state.

Names can be at most 64 bytes, and market lists and non-circulating balance
lists can hold at most 256 entries. [`precompiles.vy`](../modules/precompiles.md)
covers failures and gas.

### Which read to use

| Function | Gives | Does not give |
|---|---|---|
| `spot_balance(user, token)` | Spot total, amount that orders hold, entry notional | Perp equity or EVM balance |
| `account_margin_summary(perp_dex_index, user)` | Account value, margin used, notional and raw USD. Account value and raw USD are signed. | The amount that you can withdraw |
| `withdrawable(user)` | Withdrawable perp USDC | Whether a later withdrawal succeeds |
| `core_user_exists(user)` | Whether the address has an activated Core account | Escrowed funds, account mode or API wallets |
| `user_vault_equity(user, vault)` | Equity in a Core vault, and the lock time in milliseconds | Whether a withdrawal succeeds |
| `token_info(token)` | Token decimals, linked EVM address and spot markets | |

## `core_writer`: actions

Arguments are listed in the order the Vyper functions take them. Token amounts
use the token's Core wei decimals, and perp USD amounts use 6 decimals. Order
price and size are `10**8` times the human-readable value. If you start from an EVM
amount, convert it with `conversions` or use the `bridge` functions instead.

| Function | Action | Argument notes |
|---|---:|---|
| `place_limit_order(asset, is_buy, limit_px, sz, reduce_only, tif, cloid)` | 1 | `asset` uint32. `limit_px` and `sz` are uint64 and equal `10**8` times the human-readable value. `tif` uint8: a `TIF_*` constant. `cloid` uint128. |
| `vault_transfer(vault, is_deposit, usd_amount)` | 2 | Perp USD (6 decimals), uint64. A withdrawal checks the vault lock first. |
| `delegate_token(validator, amount_wei, undelegate)` | 3 | HYPE Core amount, uint64 |
| `staking_deposit(amount_wei)`, `staking_withdraw(amount_wei)` | 4, 5 | HYPE Core amount, uint64 |
| `spot_send(to, token, amount_wei)` | 6 | Token and amount uint64. Rejects a send to this contract. |
| `transfer_usd_class(ntl, to_perp)` | 7 | Perp USD (6 decimals), uint64 |
| `finalize_evm_contract(token, encoded_variant, create_nonce)` | 8 | uint64, uint8, uint64 |
| `add_api_wallet(wallet, name)` | 9 | Name of 32 bytes maximum. An empty name selects the unnamed API wallet. |
| `cancel_order_by_oid(asset, order_id)` | 10 | uint32, uint64 |
| `cancel_order_by_cloid(asset, cloid)` | 11 | uint32, uint128 |
| `approve_builder_fee(max_fee_rate, builder)` | 12 | Rate in decibps, uint64. Builder address. |
| `send_asset(destination, sub_account, source_dex, destination_dex, token, amount_wei)` | 13 | Two addresses, two uint32 DEX indices, two uint64 values |
| `borrow_lend(operation, token, amount_wei)` | 15 | uint8 (a `BLP_*` constant), uint64, uint64. An amount of zero means the maximum. |
| `set_abstraction(user, abstraction)` | 16 | Address, uint8. Use an `ABSTRACTION_*` constant. |

These functions only encode and send requests. Your contract must control
access and confirm that each action succeeds on Core.

## `bridge`: transfers between HyperEVM and HyperCore

| Function | Argument types | Returns |
|---|---|---|
| `bridge_usdc_to_core(amount_evm, destination_dex)` | uint256, uint32 | |
| `bridge_usdc_to_core_for(recipient, amount_evm, destination_dex)` | address, uint256, uint32 | |
| `bridge_usdc_to_evm(amount_evm, source_dex)` | uint256, uint32 | |
| `bridge_to_core(token, amount_evm)` | uint64, uint256 | uint64 Core amount |
| `bridge_hype_to_core(amount_evm)` | uint256 | uint64 Core amount |
| `bridge_erc20_to_core(token, amount_evm)` | uint64, uint256 | uint64 Core amount |
| `bridge_to_evm(token, amount, is_evm_amount)` | uint64, uint256, bool | uint64 Core amount |

The USDC functions take EVM USDC with 6 decimals. The other functions take EVM
units too, except `bridge_to_evm` when `is_evm_amount` is false, where the amount
is in Core wei. [`bridge.vy`](../modules/bridge.md) describes the routes and checks.

## `conversions`: units and addresses

| Function | Returns |
|---|---|
| `evm_to_wei(token: uint64, amount_evm: uint256)` | uint64 Core amount. Can round down. |
| `wei_to_evm(token: uint64, amount_wei: uint64)` | uint256 EVM amount. Can round down. |
| `sz_to_wei(token: uint64, sz: uint64)` | uint64 Core amount from an order size |
| `wei_to_sz(token: uint64, amount_wei: uint64)` | uint64 order size. Rounds down. |
| `wei_to_perp(amount_wei: uint64)` | uint64. Divides a USDC Core amount by 100. |
| `perp_to_wei(perp_amount: uint64)` | uint64. Multiplies a perp USD amount by 100. |
| `spot_to_asset_id(spot_index: uint64)` | uint32. Adds 10,000. |
| `asset_to_spot_id(asset: uint64)` | uint64. Subtracts 10,000. |
| `system_address(token: uint64)` | The system address of the token on the current network |
| `hype_token_index()`, `is_hype(token: uint64)` | The HYPE index on the current network, or a comparison with it |
| `usdc_address()`, `core_deposit_wallet()` | The fixed address for chain 998 or 999. Reverts on other chains. |
| `checked_token_info(token: uint64)` | `TokenInfo`. Reverts if the index is above `max_value(uint32)`. |
| `evm_to_wei_with_info(token: uint64, info: TokenInfo, amount_evm: uint256)` | `evm_to_wei` with metadata that you already read. Saves one read. |
| `token_index(token_address: address)` | uint64 Core token index of a linked EVM contract. Uses the TokenRegistry. |
| `is_usdc(token: uint64)` | `True` for index 0 |
| `to_milliseconds(timestamp: uint64)` | uint64. Multiplies by 1000. Core timestamps use milliseconds. |

The token conversions reject a token index above `max_value(uint32)`, and they
revert for a token without a linked EVM contract unless the token is HYPE.
All arithmetic and type conversions are checked. [Compatibility](compatibility.md)
lists the differences from Solidity.

`token_index` returns 0 for the chain's USDC token without a registry call. For
any other address it calls the TokenRegistry contract at
`constants.TOKEN_REGISTRY`, which reverts for an address that is not registered.
Anyone can write to the registry, so `token_index` also checks that the linked
contract in `token_info` is the same address and reverts `"Registry mismatch"`
if it isn't. For funds, use fixed token indices in your contract.

The Solidity library also has address versions of many functions, but this
library doesn't. Instead, pass the result of `token_index` to the index version,
for example `precompiles.spot_balance(user, conversions.token_index(token))`.

## `constants`

This module holds addresses, action headers, chain IDs, token indices and enum
values.

| Constant | Value | Use |
|---|---|---|
| `MAINNET_CHAIN_ID` | `999` | HyperEVM mainnet |
| `TESTNET_CHAIN_ID` | `998` | HyperEVM testnet |
| `USDC_TOKEN_INDEX` | `0` | Core token index of USDC on both networks |
| `HYPE_TOKEN_INDEX_MAINNET`, `HYPE_TOKEN_INDEX_TESTNET` | `150`, `1105` | Core token index of HYPE |
| `DEFAULT_PERP_DEX` | `0` | The default perp DEX |
| `SPOT_DEX` | `2**32 - 1` | The spot DEX in `send_asset` and the USDC bridge functions |
| `SPOT_ASSET_OFFSET` | `10_000` | Order asset ID of a spot market = spot index + this offset |
| `TIF_ALO`, `TIF_GTC`, `TIF_IOC` | `1`, `2`, `3` | `tif` of `place_limit_order`: add liquidity only, good until canceled, immediate-or-cancel |
| `BLP_SUPPLY`, `BLP_WITHDRAW` | `0`, `1` | `operation` of `borrow_lend` |
| `ABSTRACTION_DISABLED`, `ABSTRACTION_UNIFIED_ACCOUNT`, `ABSTRACTION_PORTFOLIO_MARGIN` | `1`, `2`, `3` | `abstraction` of `set_abstraction` |

The module also holds the CoreWriter address, the precompile addresses, the
action headers (`*_HEADER`), the system addresses, the TokenRegistry address,
and the USDC and CoreDepositWallet addresses for each network.
`POSITION_PRECOMPILE` (`0x0800`) is the legacy position read, and the library
reads `POSITION2_PRECOMPILE` (`0x0813`) instead.

The addresses come from
[HLConstants.sol](https://github.com/hyperliquid-dev/hyper-evm-lib/blob/4eb7ab044d0a368e0c01ec5b38d5ea48a3e3b427/src/common/HLConstants.sol)
at the pinned commit.

## Revert reasons

The library reverts with these reason strings.

| Reason | Raised by | Meaning |
|---|---|---|
| `Unsupported chain` | `conversions`, `bridge` | The chain ID is not 999 or 998. |
| `Token index too large` | `conversions` | The token index is above `max_value(uint32)`. |
| `Token not linked to EVM` | `conversions`, `bridge` | The token has no linked EVM contract and is not HYPE. |
| `Registry mismatch` | `conversions.token_index` | The TokenRegistry gave an index whose linked contract is a different address. |
| `No USDC spot market` | `precompiles.spot_index_for_token` | No spot market of the token has USDC as quote. |
| `No spot market for pair` | `precompiles.spot_index_for_pair` | No spot market of the token has the given quote token. |
| `Vault withdrawal locked` | `core_writer.vault_transfer` | The vault lock of this contract has not ended. |
| `Self transfer` | `core_writer.spot_send` | The recipient is this contract. Core always rejects this send. |
| `USDC link mismatch` | `bridge`, for USDC | Core token 0 does not link to the CoreDepositWallet of the network. |
| `USDC decimals mismatch` | `bridge`, for USDC | Core token 0 does not have 8 wei decimals and -2 EVM extra decimals. |
| `Amount too small` | `bridge` | The Core amount is zero. |
| `USDC approval failed` | `bridge` deposits | USDC `approve` for the amount returned false. |
| `USDC approval reset failed` | `bridge` deposits | USDC `approve` back to zero returned false. |
| `Zero recipient` | `bridge.bridge_usdc_to_core_for` | The recipient is the zero address. |
| `Use the USDC route` | `bridge.bridge_erc20_to_core` | The token is USDC. Use a USDC function. |
| `Use the HYPE route` | `bridge.bridge_erc20_to_core` | The token is HYPE. Use `bridge_hype_to_core`. |
| `Not a whole Core unit` | `bridge` | The EVM amount has a remainder smaller than one Core unit. |
| `Not a whole EVM unit` | `bridge.bridge_to_evm` | The Core amount has a remainder smaller than one EVM unit. |
| `Token transfer failed` | `bridge.bridge_erc20_to_core` | The ERC-20 `transfer` returned false. |

Some reverts have no reason string:

- Arithmetic overflow or a type conversion that does not fit.
- A failed precompile read, or a reply with the wrong length or out-of-range
  values.
- A failed external call. The called contract's revert data passes through, so
  for example the TokenRegistry reverts with `TokenNotFound(address)` for an
  address that is not registered.
