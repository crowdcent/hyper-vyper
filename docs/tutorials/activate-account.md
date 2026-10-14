# 2. Activate a contract account

A new contract has no activated Core account. In this tutorial you deploy a new
contract, send it HYPE before activation, then activate it with a Core send of
USDC and watch what changes.

You'll learn:

- Why a new contract's `core_user_exists` is false, and what that blocks.
- Where HYPE goes when you send it to an account that isn't activated: into an
  escrow that the precompiles can't see but the info API can.
- How a Core send of 1 USDC or more activates the account, who pays the 1 USDC
  fee, and how the escrow then moves to spot.

## Prerequisites

| Item | Amount |
|---|---|
| HYPE on HyperEVM | 0.001 HYPE for the escrow step, plus less than 0.001 HYPE for gas |
| USDC in the spot balance of your Core account | 3 USDC: 2 USDC to the contract and 1 USDC fee |
| `HYPER_VYPER_TESTNET_KEY` | for the deploy, escrow and sweep steps |
| `HYPER_VYPER_CORE_FUNDER_KEY` | optional, for the activate step |

See [testnet setup](testnet-setup.md).

## What activation changes

A contract that sends CoreWriter actions needs an activated Core account. If
the account is not activated:

- Each CoreWriter action fails silently. The EVM transaction succeeds, but Core
  does nothing.
- HYPE and linked tokens sent to the account go into an escrow. They are not
  lost, but the contract cannot see or use them.

So a contract must check `precompiles.core_user_exists(self)` before it
sends an action.

## The contract

```vyper
--8<-- "tutorials/activate_account/activate_account.vy"
```

- `status` reads the account through the precompiles.
- `hype_to_core` uses `bridge.bridge_hype_to_core` to send HYPE from EVM to the
  contract's Core account.
- `sweep` checks activation first, then sends the Core funds back to the owner.

## Steps

1. Deploy the contract. Run the step without `--execute` first to see the plan:

    ```bash
    uv run --locked tutorials/activate_account/run.py deploy
    uv run --locked tutorials/activate_account/run.py deploy --execute
    ```

2. Look at the new account:

    ```bash
    uv run --locked tutorials/activate_account/run.py status
    ```

    ```text
    contract 0x... at EVM block N
      precompile core_user_exists: False
      precompile spot USDC: 0 (0 USDC, 8 decimals)
      precompile spot HYPE: 0 (0 HYPE, 8 decimals)
      info API userRole: missing
      info API spot USDC 0, spot HYPE 0
      info API escrow (evmEscrows) HYPE: 0
    ```

3. Optional: send 0.001 HYPE to Core before activation. The step waits until
   the info API shows the escrow:

    ```bash
    uv run --locked tutorials/activate_account/run.py escrow --execute
    ```

    ```text
    send 1000000000000000 (0.001 HYPE, 18 decimals) from EVM to the Core account of the contract
    plan: hype_to_core() value 1000000000000000
    sent hype_to_core: 0x... in block N
      block N+5: exists False, precompile spot HYPE 0
    info API escrow HYPE: 0.001
    The HYPE is in escrow. The precompiles do not show it.
    ```

    The precompile shows 0 HYPE, while the info API shows 0.001 HYPE in escrow.

4. Activate the account with a Core send of 2 USDC from your Core account:

    ```bash
    uv run --locked tutorials/activate_account/run.py activate --execute
    ```

    If `HYPER_VYPER_CORE_FUNDER_KEY` is set, the step runs
    [`tutorials/send_core.py`](https://github.com/crowdcent/hyper-vyper/blob/main/tutorials/send_core.py)
    and then waits. If it is not set, the step prints the command. Run that
    command, then wait for the activation:

    ```bash
    uv run --script tutorials/send_core.py --to 0xCONTRACT --token USDC --amount 2 --execute
    uv run --locked tutorials/activate_account/run.py wait
    ```

    ```text
    Your Core account pays the 1 USDC activation fee on top of the amount.
    Core transfer: 2 USDC from your Core account to 0x...
      block N: core_user_exists True
    account is activated
    contract 0x... at EVM block N+1
      precompile core_user_exists: True
      precompile spot USDC: 200000000 (2 USDC, 8 decimals)
      precompile spot HYPE: 100000 (0.001 HYPE, 8 decimals)
      info API userRole: user
      info API spot USDC 2, spot HYPE 0.001
      info API escrow (evmEscrows) HYPE: 0
    ```

    The contract has the full 2 USDC, and the escrowed HYPE is now on spot.
    Your Core account paid 3 USDC: 2 USDC to the contract and a 1 USDC fee.
    Check your own balance with the `spotClearinghouseState` request from
    [testnet setup](testnet-setup.md#check-your-core-account).

## What can go wrong

- **The activate step refuses less than 1 USDC.** A smaller send does not
  activate the account. `send_core.py` also refuses to send HYPE to an account
  that is not activated.
- **Your Core account cannot pay.** The send needs the amount plus 1 USDC, and
  `send_core.py` checks this before it sends.
- **`spotSend` fails with "Action disabled when unified account is active".**
  New user wallets are in unified account mode, so `send_core.py` uses
  `sendAsset`, which works in that mode.
- **The escrow step refuses to send.** After activation, HYPE goes to spot
  instead of escrow, so do the escrow step before the activate step.
- **A contract action does nothing.** Check `core_user_exists`, because
  actions from an account that is not activated fail silently.

## Clean up

Send the contract's Core USDC and HYPE back to your Core account:

```bash
uv run --locked tutorials/activate_account/run.py sweep --execute
```

```text
plan: sweep(0, 200000000) value 0
sent sweep: 0x... in block N
  block N+6: spot_usdc 0
plan: sweep(1105, 100000) value 0
sent sweep: 0x... in block N+11
  block N+16: spot_hype 0
```
