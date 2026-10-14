# 3. Move USDC between spot and perp

On HyperCore, an account holds USDC in two balances: **spot** (8 decimals, for
token trading) and **perp** (6 decimals, margin for perp positions). In this
tutorial a contract moves USDC between them with
`core_writer.transfer_usd_class`, and nothing leaves HyperCore. [Tutorial
4](evm-core.md) moves USDC between HyperEVM and HyperCore.

You'll learn:

- How to move USDC from spot to perp and back from a contract.
- Why `transfer_usd_class` takes 6-decimal perp USD, and why spot then changes
  by `ntl * 100`.
- How to check the result through the spot balance, the perp account value
  and `withdrawable`.

## Prerequisites

| Item | Amount |
|---|---|
| HYPE on HyperEVM | less than 0.002 HYPE for gas |
| USDC in the spot balance of your Core account | 6 USDC: 5 USDC to the contract and 1 USDC activation fee |
| `HYPER_VYPER_TESTNET_KEY` | for all steps with `--execute` |
| `HYPER_VYPER_CORE_FUNDER_KEY` | optional, for the fund step |

Do [tutorial 2](activate-account.md) first, because it explains activation.

## Units

The same USDC has two integer forms on Core:

| Balance | Decimals | 3 USDC |
|---|---:|---:|
| Core spot USDC | 8 | `300_000_000` |
| Perp USD (`transfer_usd_class`, account value, `withdrawable`) | 6 | `3_000_000` |

If you give `300_000_000` to `transfer_usd_class`, you ask for 300 USD, not 3.

## The contract

```vyper
--8<-- "tutorials/spot_perp/spot_perp.vy"
```

- `move_usdc` checks the owner, the activation and a non-zero amount before it
  sends the action.
- `status` reads spot USDC, perp account value and `withdrawable` in one call.

## Steps

1. Deploy the contract:

    ```bash
    uv run --locked tutorials/spot_perp/run.py deploy --execute
    ```

2. Fund the contract with 5 USDC on Core. This send also activates the account:

    ```bash
    uv run --locked tutorials/spot_perp/run.py fund --execute
    ```

    Without `HYPER_VYPER_CORE_FUNDER_KEY`, the step prints the
    `send_core.py` command. Run it, then check the account with the `status`
    step until `core_user_exists` is `True`.

    ```text
    Core transfer: 5 USDC from your Core account to 0x...
      HYPER_VYPER_CORE_FUNDER_KEY=0x... uv run --script tutorials/send_core.py --to 0x... --token USDC --amount 5 --execute
      block N: exists True, spot USDC 500000000 (5 USDC, 8 decimals)
    ```

3. Show the plan to move 3 USDC to perp. This step runs the call on a local
   copy of the chain and sends nothing:

    ```bash
    uv run --locked tutorials/spot_perp/run.py to-perp --amount 3
    ```

    ```text
    before (EVM block N):
      spot USDC      500000000 (5 USDC, 8 decimals)
      perp value     0 (0 USD, 6 decimals)
      withdrawable   0 (0 USD, 6 decimals)
    move 3000000 (3 USD, 6 decimals) spot -> perp
      spot changes by 300000000 Core wei (8 decimals): ntl x 100
    plan: move_usdc(3000000, True) value 0
    plan only: add --execute to send. Nothing was sent.
    ```

4. Move 3 USDC to perp:

    ```bash
    uv run --locked tutorials/spot_perp/run.py to-perp --amount 3 --execute
    ```

    ```text
    plan: move_usdc(3000000, True) value 0
    sent move_usdc: 0x... in block N
      block N+57: spot USDC 2, perp 3
    after (EVM block N+57):
      spot USDC      200000000 (2 USDC, 8 decimals)
      perp value     3000000 (3 USD, 6 decimals)
      withdrawable   3000000 (3 USD, 6 decimals)
    change: spot USDC -300000000 (-3 USDC, 8 decimals)
            perp value 3000000 (3 USD, 6 decimals)
    ```

    Core applied the move in the next block. The script reads later, after it
    has the transaction receipt, and the public testnet RPC can take many blocks
    to return it.

5. Move the 3 USDC back to spot:

    ```bash
    uv run --locked tutorials/spot_perp/run.py to-spot --amount 3 --execute
    ```

    The change is `spot USDC 300000000` and `perp value -3000000`.

## What can go wrong

- **No change after 20 blocks.** Core rejected the action silently, even though
  the EVM transaction succeeded. The account may not be activated, spot may
  have too little USDC, or perp may have too little `withdrawable`. The script
  checks the balances before it sends, but the state can change in between.
- **A move out of perp fails while a position is open.** A transfer out of perp
  must leave enough margin. The tutorial contract opens no positions.
- **Wrong units.** `move_usdc` takes 6-decimal perp USD, so the script converts
  `--amount 3` to `3000000`.

## Clean up

Move all USDC to spot (step 5), then send it back to your Core account:

```bash
uv run --locked tutorials/spot_perp/run.py sweep --execute
```

```text
plan: sweep(0, 500000000) value 0
sent sweep: 0x... in block N
  block N+7: spot_usdc 0
```
