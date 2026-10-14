# 1. Read Core state

In this tutorial, a contract reads balances, positions and prices on HyperCore
through the read precompiles, and moves nothing. You compare each value with the
Hyperliquid info API.

You'll learn:

- How to read a spot balance, the perp account summary, `withdrawable`, mark
  and oracle prices and perp metadata from a contract.
- How each value's integer form maps to the human number that the info API
  shows.
- How `core_user_exists` tells you whether an address has a Core account.

## Prerequisites

| Item | Amount |
|---|---|
| HYPE on HyperEVM for the deployment | less than 0.001 HYPE |
| Core funds | none |
| `HYPER_VYPER_TESTNET_KEY` | for the deploy step only |

See [testnet setup](testnet-setup.md).

## The contract

[`tutorials/read_state/read_state.vy`](https://github.com/crowdcent/hyper-vyper/blob/main/tutorials/read_state/read_state.vy) has no storage and no write functions:

```vyper
--8<-- "tutorials/read_state/read_state.vy"
```

- `read_user` makes all reads for one address in one call, so all values come
  from the same EVM block.
- `spot_usdc` and `spot_hype` are `SpotBalance(total, hold, entry_ntl)` in Core
  units with 8 decimals.
- `perp` is `AccountMarginSummary(account_value, margin_used, ntl_pos, raw_usd)`
  in perp USD with 6 decimals.
- `mark_px` and `oracle_px` are raw integers that you divide by
  `10**(6 - sz_decimals)`. For BTC, `sz_decimals` is 5, so you divide by 10.

## Steps

1. Show the deployment plan. This step runs the deployment on a local copy of
   the chain and sends nothing:

    ```bash
    uv run --locked tutorials/read_state/run.py deploy
    ```

    ```text
    chain 998 (HyperEVM testnet)
    plan: deploy read_state.vy
    plan only: add --execute to send. Nothing was sent.
    ```

2. Deploy the contract:

    ```bash
    uv run --locked tutorials/read_state/run.py deploy --execute
    ```

    ```text
    chain 998 (HyperEVM testnet)
    plan: deploy read_state.vy
    sent deploy: 0x... in block N
    contract 0x...
    ```

    The deploy step saves the contract address in
    `tutorials/.state/read_state.json`.

3. Read your own address and perp market 3 (BTC on testnet). Give the address
   with `--user`:

    ```bash
    uv run --locked tutorials/read_state/run.py read --user 0xYOUR_ADDRESS
    ```

    This step only reads. Each line shows the precompile value with its units,
    then the info API value:

    ```text
    chain 998 (HyperEVM testnet)
    EVM block N, Core block M, user 0xYOUR_ADDRESS
      [ok  ] core_user_exists    precompile True  |  info API user
      [ok  ] spot USDC           precompile 100000000000 (1000 USDC, 8 decimals)  |  info API 1000.0
      [ok  ] spot HYPE           precompile 25000000 (0.25 HYPE, 8 decimals)  |  info API 0.25
      [ok  ] perp account value  precompile 0 (0 USD, 6 decimals)  |  info API 0.0
      [ok  ] perp withdrawable   precompile 0 (0 USD, 6 decimals)  |  info API 0.0
      [ok  ] perp 3 name         precompile BTC  |  info API BTC
      [ok  ] perp 3 sz_decimals  precompile 5  |  info API 5
      [ok  ] mark price          precompile 831540 / 10**1 = 83154  |  info API 83150.0
      [ok  ] oracle price        precompile 836580 / 10**1 = 83658  |  info API 83658.0
    All values match.
    ```

    The mark price moved between the two reads, which is within the tolerance
    for prices (see [What can go wrong](#what-can-go-wrong)).

4. Read a new random address, which has no Core account, and perp 0:

    ```bash
    uv run --locked tutorials/read_state/run.py read --perp 0 \
        --user 0x8f3a2b9c1d4e5f60718293a4b5c6d7e8f9012345
    ```

    ```text
      [ok  ] core_user_exists    precompile False  |  info API missing
      [ok  ] spot USDC           precompile 0 (0 USDC, 8 decimals)  |  info API 0
      ...
      [ok  ] perp 0 name         precompile SOL  |  info API SOL
      [ok  ] perp 0 sz_decimals  precompile 2  |  info API 2
      [ok  ] mark price          precompile 1074500 / 10**4 = 107.45  |  info API 107.45
    ```

    `core_user_exists` is `False` and all balances are 0. Perp 0 is SOL, with
    `sz_decimals` 2, so the script divides the prices by `10**4`.

!!! tip "Read without a deployment"
    Add `--no-deploy` to the read step. The script then deploys the contract
    on the local copy of the chain only, reads through it, and sends nothing.

## What can go wrong

- **A price shows `DIFF`.** The script reads the precompiles and the info API
  one after the other, and the price can change between the two reads. The
  script accepts a difference of 0.5%, so run the step again.
- **A balance shows `DIFF` in unified account mode.** A new user wallet is in
  unified account mode, where balance reads can show perp funds through spot,
  so the two sources can differ. See [account mode](../modules/core-writer.md#account-mode).
- **Funds in escrow.** The precompiles do not show an escrow. If the info API
  shows `evmEscrows`, the script prints a note. See
  [tutorial 2](activate-account.md).
- **A past block.** An `eth_call` to a precompile always returns the current
  Core state, even for an old block tag. Record each reading when you make it.
- **No contract in the state file.** Run the deploy step first, or use
  `--no-deploy`.

## Clean up

The contract holds no funds, so you can leave it. To deploy again, delete
`tutorials/.state/read_state.json`.
