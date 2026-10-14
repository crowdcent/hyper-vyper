# `core_writer.vy`

This module lets a contract send actions to HyperCore: orders, transfers,
staking and account settings. [`precompiles.vy`](precompiles.md) asks questions,
and this module gives instructions.

If you know Python, think of each function as building a request body and
putting it on a queue. The function returns at once. A worker processes the
queue later, and it does not tell you when a request fails.

## The module docstring

<!-- starts: "\"\"\"" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:4:31"
```

HyperCore runs each action after the EVM block, so the EVM transaction
succeeds even when HyperCore later rejects the action, and your contract must
read the result in a later block
([concepts](../concepts.md#actions-are-asynchronous) explains this model). A
transfer shows in the next block. The Hyperliquid documentation says orders and
vault transfers can take a few seconds more.

## The one function that sends

<!-- starts: "# The largest payload" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:36:45"
```

- `interface ICoreWriter` tells the compiler the function signature of the
  CoreWriter contract, much like a type stub in Python.
- `extcall` calls another contract that can change state. The reads in
  `precompiles.vy` are static calls, which cannot change state.
- `Bytes[MAX_ACTION_BYTES]` is a byte string with a maximum length of 228,
  because the largest action, a limit order, is exactly 228 bytes.

Every other function in the module calls `_send`, so all actions go to the
same address, `constants.CORE_WRITER`.

## A limit order, byte by byte

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:50:68"
```

`concat(header, abi_encode(...))` builds the payload:

| Bytes | Content |
|---:|---|
| 4 | Header `0x01000001`: version 1, action 1 (limit order) |
| 32 | `asset` (`uint32`, padded) |
| 32 | `is_buy` |
| 32 | `limit_px` (`uint64`) |
| 32 | `sz` (`uint64`) |
| 32 | `reduce_only` |
| 32 | `tif` (`uint8`) |
| 32 | `cloid` (`uint128`) |

Pay attention to the units:

- `limit_px` and `sz` are `10**8` times the human-readable value. A price of
  47.203 USDC is `4_720_300_000`, and a size of 0.25 is `25_000_000`.
- For a spot market, `asset` is `10000 +` the spot index.
- Hyperliquid has a minimum order value of 10 USDC.

The [spot order tutorial](../tutorials/spot-order.md) places IOC orders
(`TIF_IOC`) with this function.

[Concepts](../concepts.md#hyperevm-and-hypercore) shows a complete `spot_send`
payload with each byte marked.

## A check before the action

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:91:107"
```

`vault_transfer` moves USDC into or out of a HyperCore vault. Before a
withdrawal, it reads the vault lock (see [`precompiles.vy`](precompiles.md)) and
reverts if the lock is still active. The check is useful because a locked
withdrawal would otherwise fail silently on Core.

- `block.timestamp` is in seconds and Core uses milliseconds, so the code
  multiplies by 1000.
- `>` (not `>=`) matches the Solidity library exactly.

## Transfers

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:112:126"
```

`spot_send` sends a token to another address on Core. It reverts when the
recipient is the contract itself, because Core always rejects that action.

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:129:145"
```

`send_asset` is the general transfer. It moves funds between addresses and
between DEXes (spot, perp DEX 0, other perp DEXes), and the library uses it for
every route. `spot_send` moves spot tokens only. In unified account mode, Core
refuses a user-signed `spotSend` but accepts a CoreWriter `spot_send`.

A `send_asset` to a token's system address returns the token to EVM, and the
bridge module uses this route (see [`bridge.vy`](bridge.md)).

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:148:157"
```

`transfer_usd_class` moves USDC between the spot balance and the perp balance
of the same address, and `ntl` uses perp units (6 decimals). For example, moving
3 USDC from spot to perp decreases spot by `300_000_000` (8 decimals) and
increases the perp account value by `3_000_000` (6 decimals).

## Functions that give away funds or authority

Several functions move funds or authority to an address that you supply, and
each one has a warning in its docstring. Never take these addresses from
untrusted input, for example from a function argument that any user can set.

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:209:225"
```

`add_api_wallet` is the most powerful one. An API wallet (Hyperliquid also
calls it an agent) can trade with the contract's whole Core account, and pausing
the EVM contract does not stop it.

<!-- starts: "# --- Borrow/Lend ---" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:239:251"
```

`borrow_lend` has a trap: an amount of 0 means "the maximum". If your contract
computes an amount that rounds down to 0, the action moves the whole balance.
The library keeps the protocol meaning and warns you, so your contract must
check the amount.

## Account mode

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/core_writer.vy:256:273"
```

The account mode decides how Core holds an account's USDC: as separate spot and
perp balances, or pooled. The info API request `userAbstraction` returns one of
these values:

| Value | Meaning |
|---|---|
| `default` | No mode is set, so the account uses Hyperliquid's default for its account type. A new contract keeps spot and perp separate, and a new user wallet starts in `unifiedAccount`. |
| `disabled` | Spot and perp stay separate. `set_abstraction(self, ABSTRACTION_DISABLED)` sets it. |
| `unifiedAccount` | Spot and perp are pooled. A switch to this mode moves the perp USDC to spot, and a switch back doesn't move it back. Balance reads can show perp funds through spot. |
| `portfolioMargin` | Portfolio margin. Core ignores the switch unless the account has 10,000 USD of account value or 5,000,000 USD of trading volume. |

A contract that holds funds should call
`set_abstraction(self, ABSTRACTION_DISABLED)` once after activation. `disabled`
pins separate spot and perp balances, so accounting that counts them separately
doesn't change if Hyperliquid changes the default. No precompile can read the
current mode, so check the result with the info API.

## Check your understanding

1. A contract calls `transfer_usd_class` and the EVM transaction succeeds. Has
   the USDC moved? How can the contract find out?
2. What is the byte length of a `cancel_order_by_oid` payload?
3. Encode a buy order for 1.5 units at a price of 2.25 USDC. What are `sz` and
   `limit_px`?
4. Why does the library prefer `send_asset` to `spot_send`?
5. Your contract calls `borrow_lend(BLP_WITHDRAW, token, amount)` with
   `amount = wei_to_sz(...)`. What can go wrong?

## Try it

```bash
uv run --locked pytest tests/test_actions.py -q
```

Swap `limit_px` and `sz` in the `abi_encode` call of `place_limit_order`, run
the command again and read the failure. Then restore the file with
`git checkout -- src/`.

Next: [`conversions.vy`](conversions.md).
