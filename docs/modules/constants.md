# `constants.vy`

This module has no logic. It gives names to fixed values. Every other module
imports them, so a wrong value here breaks the whole library.

## The file header

<!-- starts: "# pragma version 0.4.3" -->
```python
--8<-- "src/hyper_vyper/constants.vy:1:15"
```

- `# pragma version 0.4.3` tells the compiler which Vyper version the file is
  for, and a different compiler version refuses the file.
- `# SPDX-License-Identifier: MIT` states the license in a standard format.
- The docstring describes the module with NatSpec tags such as `@title`,
  `@notice` and `@dev`.

## How a constant works

<!-- starts: "# CoreWriter system contract" -->
```python
--8<-- "src/hyper_vyper/constants.vy:17:18"
```

The form is `NAME: constant(type) = value`.

- The compiler copies the value into each place that uses it, so a constant
  uses no storage and costs no gas to read.
- The value cannot change after deployment. To change it, you must deploy new
  code.
- The source checker ([`hyper-vyper-check-source`](https://github.com/crowdcent/hyper-vyper/blob/main/src/hyper_vyper/check_source.py))
  allows only plain literal values here, plus
  `max_value(uint32)`. This avoids a known problem with computed constants in
  Vyper 0.4.3 (see [security](../security.md#compiler)).

`CORE_WRITER` is the contract that accepts actions for HyperCore, and
[`core_writer.vy`](core-writer.md) explains actions.

## Read precompiles

<!-- starts: "# Read precompile addresses" -->
```python
--8<-- "src/hyper_vyper/constants.vy:20:42"
```

Each address is a read endpoint built into the chain, and each one has a
matching function in [`precompiles.vy`](precompiles.md).

- Some addresses use capital letters (`080C`) and some do not (`080e`). This is
  the checksum format of Ethereum addresses. Vyper requires it because it
  catches typing errors.
- `0x0800` is the legacy position read. Like the Solidity library, this library
  uses `0x0813` instead.

## System addresses and the token registry

<!-- starts: "# System addresses" -->
```python
--8<-- "src/hyper_vyper/constants.vy:44:52"
```

A system address connects HyperEVM and HyperCore for one token.

- HYPE uses `0x2222...2222`.
- Every other token uses `0x20` followed by the token index. USDC is token 0, so
  its system address is `0x2000...0000`.
- A transfer to a system address on EVM moves the token to Core, and a Core
  `send_asset` to a system address moves it back to EVM.

`TOKEN_REGISTRY` is a contract outside this library that maps EVM token
addresses to Core token indices. Anyone can write to it, so
`conversions.token_index` checks each answer (see
[`conversions.vy`](conversions.md)).

## USDC, HYPE and the networks

<!-- starts: "# Core deposit wallet (Circle)" -->
```python
--8<-- "src/hyper_vyper/constants.vy:54:70"
```

- Each network has its own USDC address and its own Circle deposit wallet, and
  `conversions.vy` picks the correct one from the chain ID.
- Core links USDC to the deposit wallet, not to the USDC token.
- USDC is token 0 on both networks. HYPE is token 150 on mainnet and 1105 on
  testnet, so code that handles HYPE must check the network.
- HYPE has 18 decimals on EVM and 8 on Core. The difference is
  `HYPE_EVM_EXTRA_DECIMALS = 10`, which is why a HYPE amount must be a
  multiple of `10**10` before it can move to Core.
- Chain 999 is mainnet and chain 998 is testnet. Functions that depend on the
  network revert on any other chain.

## Action headers

<!-- starts: "# CoreWriter action headers" -->
```python
--8<-- "src/hyper_vyper/constants.vy:72:88"
```

Each action starts with a 4-byte header: version `01`, then the action ID as
3 bytes. For example, `0x01000006` means version 1, action 6 (spot send).

The values match the action table in the Hyperliquid documentation.
[`tests/test_actions.py`](https://github.com/crowdcent/hyper-vyper/blob/main/tests/test_actions.py)
checks each action against that table, not against this file. Action 14 is not
in the documented table, and the library does not support action 17 (outcome
operations).

## Enum values

<!-- starts: "# Limit order time-in-force" -->
```python
--8<-- "src/hyper_vyper/constants.vy:90:109"
```

- `TIF_*` is the time in force of an order. `TIF_IOC` means
  immediate-or-cancel, and the [order tutorial](../tutorials/spot-order.md)
  uses it.
- `BLP_*` selects supply or withdraw for borrow and lend.
- `ABSTRACTION_*` selects the account mode. A contract that holds funds should
  set `ABSTRACTION_DISABLED` after activation (see [security](../security.md)).
- `SPOT_DEX` is the largest `uint32` value, which Hyperliquid uses to mean
  "spot" wherever it expects a DEX index. `DEFAULT_PERP_DEX = 0` is the default
  perp DEX.
- An order on spot market `n` uses asset ID `10000 + n`.

## Check your understanding

1. A deployed contract uses a wrong constant. Why can't it correct the value,
   and what must its owner do?
2. Which constant tells you that HYPE amounts must be multiples of `10**10`?
3. A testnet order sells HYPE on spot market 1035. Which asset ID does the
   order use, and which line explains it?
4. Why does the library keep two deposit wallet addresses?

## Try it

```bash
uv run --locked pytest tests/test_actions.py -q
```

Change `SPOT_SEND_HEADER` to `0x01000007`, run the command again and read the
failures. Then restore the file with `git checkout -- src/`.

Next: [`precompiles.vy`](precompiles.md).
