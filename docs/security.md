# Security

This library is unaudited and provided as is. Its code runs inside the contract
that imports it, with that contract's address and funds, so review it as
thoroughly as your own code.

## What the library checks

- Read replies decode into types with fixed bounds. A short or out-of-range
  reply reverts, so a failed read never turns into a zero balance.
- A fixed-size read reverts if the reply is longer than expected. If HyperCore
  changes a reply format, these reads stop working, so a contract that holds
  funds needs an upgrade or escape path. A variable-length read accepts trailing
  bytes after the data.
- Reads forward a limited amount of gas: 75,000 for fixed-size replies and
  1,100,000 for variable-length replies. A failed read uses up its whole gas
  limit, so a few failed large reads can use most of a small block's gas.
  `spot_index_for_token` and `spot_index_for_pair` can read up to 256 markets.
- Amount conversions revert on overflow instead of wrapping.
- USDC functions run only on chains 998 and 999. They check USDC's Core
  metadata, reject a zero amount, and reset the deposit-wallet allowance to
  zero.

## What your contract must handle

The library stays a thin wrapper and makes no policy decisions, so your contract
must handle these.

### Access and authority

- **Access control.** Don't let arbitrary callers use the bridge or CoreWriter
  functions.
- **Recipients.** `send_asset`, `spot_send`, `vault_transfer`,
  `delegate_token`, `approve_builder_fee`, `add_api_wallet` and
  `bridge_usdc_to_core_for` move funds or authority to the given address, so
  never take that address from untrusted input.
- **API wallets.** An API wallet can trade the whole Core account, and it stays
  active when you pause the EVM contract. To revoke an API wallet, replace it
  with a new one. The replacement takes effect in the next block. An API wallet
  added through CoreWriter expires after 90 days. Never reuse a replaced API
  wallet address, because Hyperliquid can prune its nonce state and old signed
  actions could then replay.
- **Reentrancy.** A linked ERC-20 contract can call back into your contract
  during a bridge transfer, and the token's deployer chooses that contract.
- **Token lookups.** `conversions.token_index` trusts the TokenRegistry
  contract, so use fixed token indices for funds.

### Transfers finish in a later block

A CoreWriter action that fails on Core doesn't revert the EVM transaction, and
a deposit or a return isn't complete when the transaction ends.

- **Pending transfers.** Record each transfer as pending until a later read
  shows the result, and plan how to recover when a Core action fails. Other
  operations can change the same balances, so include them in your accounts too.
  [`examples/usdc_bridge.vy`](https://github.com/crowdcent/hyper-vyper/blob/main/examples/usdc_bridge.vy)
  shows a pending record.
- **Pausing.** If you pause an EVM contract, its open Core orders stay open.
- **Native balance.** `bridge_hype_to_core` spends your contract's own HYPE.

### Account setup

- **Activation.** CoreWriter actions from an account that is not activated
  fail silently, and HYPE and linked tokens sent to it wait in an escrow that
  the precompiles don't show. Check `precompiles.core_user_exists(self)` before
  you send a CoreWriter action or bridge HYPE or a linked token. A Core transfer
  of 1 USDC or more activates an account, the sender pays the 1 USDC fee, and
  Core then releases the escrow to spot. A USDC deposit to an account that is
  not activated also activates it, and Core takes the 1 USDC fee from the
  deposit, so don't count the first 1 USDC of that deposit.
- **Account mode.** Call
  `core_writer.set_abstraction(self, constants.ABSTRACTION_DISABLED)` once after
  activation, and check that the info API request `userAbstraction` returns
  `disabled`. In unified account mode, a deposit to perp DEX 0 arrives in spot.
  [Account mode](modules/core-writer.md#account-mode) explains each mode.
- **HYPE for returns.** When the account holds HYPE, Core charges the gas for a
  return to EVM in HYPE from Core spot (about 0.00002 HYPE at a base fee of
  0.1 gwei). Without HYPE, Core takes the gas in USDC from spot: 0.001 to 0.002
  USDC per return on mainnet, and about 0.0009 USDC on testnet. For a perp
  return when spot has no USDC, it takes the fee from perp. The amount changes
  with the HYPE price and the base fee. Keep a small HYPE balance so the fee
  comes from HYPE and your USDC accounting stays exact. A return above the balance or the withdrawable amount
  fails silently and pays no gas.
- **DEX index.** Neither the USDC functions nor the CoreDepositWallet restrict
  the DEX index. A deposit to a DEX that
  doesn't exist goes to spot. A HIP-3 DEX can also use collateral other than
  USDC. Hard-code `constants.DEFAULT_PERP_DEX` or `constants.SPOT_DEX` unless
  you have verified the other DEX. A return from the wrong source DEX fails
  silently.

### Amounts

- **Perp margin.** A transfer out of perps, such as a return to EVM or a move
  to spot, must leave margin of at least
  `max(initial margin, 10% of total position value)`. Unrealized profit counts
  toward that margin, so the amount you can transfer changes with prices. Read
  `precompiles.withdrawable(self)` immediately before the transfer. Source:
  [Hyperliquid margining](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margining#unrealized-pnl-and-transfer-margin-requirements).
- **Zero amounts in `borrow_lend`.** An amount of 0 means the maximum, so a
  computed amount that rounds down to 0 moves the whole balance. Validate the
  amount before the call.

## Compiler

The library uses Vyper 0.4.3, which was the latest stable release at 0.1.0.
This version has published advisories, and the source checker
(`hyper-vyper-check-source`) rejects the source patterns they describe. CI runs
the checker on this repository.

| Advisory | Restriction |
|---|---|
| [Multi-byte identifiers/BOM](https://github.com/vyperlang/vyper/security/advisories/GHSA-r3c7-7xwm-6vfw), [line separators](https://github.com/vyperlang/vyper/security/advisories/GHSA-wvx7-39qj-2g9v) | Printable ASCII, tabs and newlines only, also in comments |
| [Nested-array conditionals](https://github.com/vyperlang/vyper/security/advisories/GHSA-cw3h-xwxq-8cx2), [conditional optimizer issue](https://github.com/vyperlang/vyper/security/advisories/GHSA-6j9c-gvcw-74fj) | No `a if condition else b` expressions |
| [Imported constants/default arguments](https://github.com/vyperlang/vyper/security/advisories/GHSA-2489-32vh-8rrc) | Constants must be literals or `max_value(uint32)`. No default arguments. |
| [Blueprint offset validation](https://github.com/vyperlang/vyper/security/advisories/GHSA-fxg7-4wqg-c8gh) | No `create_from_blueprint` |

The package installs the checker as a command, so you can run it on your own
contracts:

```bash
uv run hyper-vyper-check-source contracts/
```

It checks the `.vy` files in the paths you give it. Before you deploy, check the
advisory list again for new entries.

## Report a vulnerability

Don't open a public issue for a security problem. Report it privately, as
[SECURITY.md](https://github.com/crowdcent/hyper-vyper/blob/main/SECURITY.md)
describes.
