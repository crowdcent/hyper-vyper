# `conversions.vy`

This module converts amounts between the decimal systems of HyperEVM and
HyperCore, and it finds network-specific addresses. A wrong unit can lose funds,
so this page has many examples.

If you know Python, think of the module as a set of unit-conversion functions,
like `cents_to_dollars`. The difference is that Vyper has no floats: every
amount is an integer, and every division rounds down.

## The module docstring

<!-- starts: "\"\"\"" -->
```python
--8<-- "src/hyper_vyper/conversions.vy:4:25"
```

The library works with four units:

| Unit | Meaning | USDC example: 1 USDC |
|---|---|---:|
| EVM amount | The ERC-20 amount on HyperEVM | `1_000_000` (6 decimals) |
| Core wei | The token amount on HyperCore | `100_000_000` (8 decimals) |
| Core sz | The order size unit | depends on `sz_decimals` |
| Perp USD | USDC in the perp balance | `1_000_000` (6 decimals) |

## The network

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/conversions.vy:31:44"
```

`chain.id` is the chain ID of the current network, and `_require_network`
reverts on every chain except 998 (testnet) and 999 (mainnet). The Solidity
library falls back to mainnet values on unknown chains. This library refuses,
because a wrong address on an unknown chain could send funds to the wrong place.

`hype_token_index`, `usdc_address` and `core_deposit_wallet` return the value
for the current network.

## System addresses

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/conversions.vy:74:84"
```

An address is a 160-bit number. The code converts the base address
`0x2000...0000` to a number, adds the token index, and converts the result back
to an address. For token 197 (UBTC) the result is `0x2000...00c5`, because 197
is `0xc5` in hexadecimal. HYPE is the exception and uses `0x2222...2222`.

## From EVM to Core

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/conversions.vy:89:127"
```

`checked_token_info` reads the token metadata and rejects an index above
`max_value(uint32)`. The Solidity library truncates such an index to 32 bits,
so it can read the metadata of a different token.

`evm_to_wei_with_info` uses `evm_extra_wei_decimals`, which is the number of
decimals that the EVM token has in addition to the Core token.

| Token | EVM decimals | Core decimals | Extra | Rule | Example |
|---|---:|---:|---:|---|---|
| USDC | 6 | 8 | -2 | multiply by 100 | `1_000_000` EVM is `100_000_000` Core |
| UETH | 18 | 9 | 9 | divide by `10**9` | `3 * 10**9 + 1` EVM is `3` Core, remainder 1 |
| HYPE | 18 | 8 | not linked | divide by `10**10` | `10**18` EVM (1 HYPE) is `10**8` Core |

Three Vyper details matter here:

- `//` is integer division and rounds down, so the UETH example loses the
  remainder. The bridge functions ([`bridge.vy`](bridge.md)) reject such amounts.
- `convert(x, uint64)` reverts if `x` does not fit in 64 bits, so a
  wrap-around is not possible.
- `-info.evm_extra_wei_decimals` changes the sign of an `int8`. For the value
  `-128` this overflows, so the code reverts instead of giving a wrong result.

HYPE has no linked EVM contract (`evm_contract` is the zero address), so the
code uses a fixed rule for HYPE. Any other unlinked token causes the revert
`"Token not linked to EVM"`.

## From Core to EVM

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/conversions.vy:130:145"
```

This is the reverse direction, and it truncates when EVM has fewer decimals
than Core. For USDC, `199` Core wei is `1` EVM unit, and the conversion drops
the remaining `99` Core wei.

## Order sizes

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/conversions.vy:150:169"
```

An order size uses `sz_decimals`, and a Core amount uses `wei_decimals`. HYPE
has `wei_decimals = 8` and `sz_decimals = 2`, so the factor is `10**6`:

- `sz_to_wei(HYPE, 25)` is `25_000_000` Core wei (0.25 HYPE).
- `wei_to_sz(HYPE, 999_999)` is `0`, because the division rounds down.

The subtraction `wei_decimals - sz_decimals` uses `uint8`, so it would revert
for a token whose `sz_decimals` is larger than its `wei_decimals`.

## USDC between spot and perp, and asset IDs

<!-- starts: "# --- USDC spot wei" -->
```python
--8<-- "src/hyper_vyper/conversions.vy:172:203"
```

- Spot USDC has 8 decimals and perp USD has 6, so the factor is 100.
  `wei_to_perp(199)` is `1`, and the division loses 99.
- `spot_to_asset_id(1035)` is `11035`, the asset ID of a spot order on market
  1035. `asset_to_spot_id` is the reverse, and it only makes sense for spot
  asset IDs.

## From a token address to a token index

<!-- starts: "@internal" -->
```python
--8<-- "src/hyper_vyper/conversions.vy:212:228"
```

`token_index` finds the Core index of an EVM token address:

1. The network's USDC token is index 0, so no registry call is necessary.
2. For any other address, the function asks the TokenRegistry contract with
   `staticcall`, a call that cannot change state.
3. The function rejects index 0, because index 0 is USDC and step 1 already
   handles the USDC token. The registry also maps the Circle deposit wallet to
   0, but the wallet is not a token.
4. The function checks that the token metadata links back to the same address,
   because anyone can write to the registry and its answer can be stale.

In a contract that holds funds, use fixed token indices instead of `token_index`.

## Check your understanding

1. Convert 2.5 USDC from EVM units to Core wei, and from Core wei to perp USD.
2. Why does `evm_to_wei` revert for a token without a linked EVM contract,
   except for HYPE?
3. What is the result of `wei_to_sz(HYPE, 1_999_999)`, and what happens to the
   rest?
4. Why does the library check `token_index` answers against `token_info`?
5. Which function would you use to avoid two `token_info` reads in one
   transaction?

## Try it

```bash
uv run --locked pytest tests/test_reference.py -q -k "conversion or wei or usdc"
```

Change `perp_to_wei` to multiply by 10 instead of 100, run the command again and
read the failures. Then restore the file with `git checkout -- src/`.

Next: [`bridge.vy`](bridge.md).
