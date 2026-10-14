# `precompiles.vy`

This module lets a contract read HyperCore state: balances, positions, prices
and token metadata. Each function asks one question and returns a typed answer.

If you know Python, think of it as a typed API client: each function sends a
request, gets bytes back and parses them into a dataclass. The difference is
that the "server" is part of the chain, and the answer describes Core state at
the start of the current EVM block.

## The module docstring

<!-- starts: "\"\"\"" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:4:30"
```

A read shows Core state at the start of the block, so an action that your
contract sends in this block shows only in a later block
([concepts](../concepts.md#actions-are-asynchronous) explains why).
Variable-length replies go into types with a maximum size, and a larger reply
causes a revert. A failed read uses all the gas that the read is allowed.

## Limits and gas

<!-- starts: "# Decode bounds for dynamic precompile responses" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:34:49"
```

Vyper has no lists or strings without a maximum size, so each variable-length
value needs a bound, for example `String[64]`. These four constants set the
bounds.

The two gas constants limit what a read may spend. A precompile costs
`2000 + 65 * (input bytes + output bytes)` gas, and these are the largest cases:

| Read | Largest input | Largest output | Cost | Limit |
|---|---:|---:|---:|---:|
| Small reads | 64 bytes | 1,024 bytes | 72,720 | 75,000 |
| Large reads | 32 bytes | 16,608 bytes | 1,083,600 | 1,100,000 |

Each limit covers the largest reply that the library accepts. The Solidity
library sends all remaining gas instead, but a limit is safer because a broken
read cannot use up the gas of the whole transaction.

## Structs: the shape of each answer

<!-- starts: "struct SpotBalance:" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:52:55"
```

A struct is like a Python dataclass. The decoder reads the values by position,
so the field order must match the order of the values in the reply.

<!-- starts: "struct AccountMarginSummary:" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:121:125"
```

`account_value` and `raw_usd` are `int64`, a signed type, because a perp account
can have a negative value. The other fields are unsigned (`uint64`).
`account_value` uses 6 decimals, so 1 USDC is `1_000_000`.

<!-- starts: "struct TokenInfo:" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:97:105"
```

`TokenInfo` holds the token metadata that the conversions use (see
[`conversions.vy`](conversions.md)): `wei_decimals`, `sz_decimals` and
`evm_extra_wei_decimals`. `spots` is a list with a maximum length, written
`DynArray[uint64, MAX_SPOT_MARKETS]`.

## The two call helpers

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:154:163"
```

Every read goes through one of these two helpers. `raw_call` sends bytes to an
address and returns bytes, and it takes these options:

| Option | Meaning |
|---|---|
| `max_outsize=SMALL_REPLY` | The largest reply that the call accepts: 1,024 bytes |
| `gas=SMALL_READ_GAS` | The most gas that the call may use |
| `is_static_call=True` | The call can read but cannot change state |
| (default) `revert_on_failure=True` | If the precompile fails, the whole transaction reverts |

The last row matters most for funds. A failed read never returns zero. It
reverts the transaction, so a contract that holds funds cannot read "balance 0"
by mistake when the read failed.

`@internal` means only code in the same contract can call the function. When a
contract imports the module, the compiler copies the functions into that
contract. `@view` means the function reads but does not write.

## One read, step by step

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:214:222"
```

`spot_balance(user, token)` works in three steps:

1. `abi_encode(user, token)` builds the input: two 32-byte words, 64 bytes in
   total. Both the address and the token index are padded on the left with
   zeros.
2. `self._call(...)` sends the input to precompile `0x0801` and gets the reply.
3. `abi_decode(response, SpotBalance)` checks the reply and returns a struct.

The reply has three 32-byte words, 96 bytes in total:

| Word | Field | Meaning |
|---:|---|---|
| 1 | `total` | All of the token, in Core wei (8 decimals for USDC) |
| 2 | `hold` | The part that open orders hold. It is included in `total`. |
| 3 | `entry_ntl` | Entry notional value |

`abi_decode` rejects a reply that is too short, too long, or has a value that
does not fit its type. For example, a `uint64` field with a value above
`2**64 - 1` causes a revert.

All the other simple reads follow the same three steps, and only the precompile
address, the input and the struct change.

## Prices and their units

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:168:176"
```

A raw price has a scale that depends on the market:

- A perp price is the price times `10**(6 - sz_decimals)`.
- A spot price is the price times `10**(8 - base_sz_decimals)`, where
  `base_sz_decimals` is the `sz_decimals` of the base token.

The `normalized_*` functions give a price with a fixed number of decimals:

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:397:403"
```

Here is an example from mainnet. BTC has `sz_decimals = 5`, so a raw mark price
of `834570` times `10**5` is `83_457_000_000`. With 6 decimals, that is
83,457 USD.

## Finding a market

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:349:370"
```

`_find_spot_index` reads the token's list of spot markets, then reads each
market until it finds one with the requested quote token. Vyper returns the two
values as a tuple: `(found, spot)`.

`spot_index_for_token` always requires a USDC quote. The Solidity library skips
this check and returns a token's only market, which can be wrong. On mainnet,
STHYPE has one market, and its quote token is not USDC. The Solidity library
returns that market, so a caller that reads its price gets a price in another
token, not in USDC. Use `spot_index_for_pair` for
a market quoted in another token.

## Account existence

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/precompiles.vy:455:466"
```

`core_user_exists` returns true only for an activated account.
[Security](../security.md#account-setup) explains what changes at activation and
why a contract that holds funds must check it.

## What the reads cannot tell you

- The account mode (see [account mode](core-writer.md#account-mode)).
- Funds in escrow.
- Past state. An off-chain `eth_call` to a precompile ignores the block tag and
  always returns the current state.
- A list of open orders, or of all tokens that an account holds.

## Check your understanding

1. Why does a failed read revert instead of returning zero, and why does that
   matter for a contract that holds funds?
2. `spot_balance` returns `total = 500_000_000` and `hold = 100_000_000` for
   USDC. How much USDC is free for a transfer?
3. Why are `account_value` and `raw_usd` signed, but `margin_used` unsigned?
4. A contract sends a CoreWriter action and reads `spot_balance` in the same
   transaction. Does the read show the result of the action? Why?
5. Why does the library set a gas limit on each read?

## Try it

```bash
uv run --locked pytest tests/test_decoding.py -q
```

Swap the `hold` and `entry_ntl` fields in `SpotBalance`, run the command again
and read the failure. Then restore the file with `git checkout -- src/`.

Next: [`core_writer.vy`](core-writer.md).
