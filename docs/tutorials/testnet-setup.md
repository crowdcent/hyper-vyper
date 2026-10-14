# Testnet setup

To run the tutorials, you need three things on Hyperliquid testnet:

1. A **testnet key**. Its address deploys and owns the tutorial contracts.
2. A little **HYPE on HyperEVM** for gas.
3. **Testnet USDC in the spot balance of your Core account** (and 0.01 HYPE for
   tutorial 4). Your Core account sends Core funds to the tutorial contracts.

## Amounts

| Item | Where | Amount for all tutorials |
|---|---|---|
| HYPE for gas | HyperEVM (EVM balance of your address) | About 0.015 HYPE. One deployment costs less than 0.001 HYPE at 0.1 gwei. Tutorial 2 also sends 0.001 HYPE to Core. |
| USDC | Spot balance of your Core account | 35 USDC. You get back all except about 5 USDC: 4 activation fees, the trading fees and the Core gas of the returns. |
| HYPE | Spot balance of your Core account | 0.01 HYPE, for tutorial 4 only |

The deposit step of tutorial 4 also needs your address to have a Hyperliquid
**mainnet** account, because on testnet Circle's deposit wallet credits only
such addresses. The testnet faucet asks for one too.

## Make a testnet key

Create a new key for testnet use only:

```bash
uv run --locked python -c "from eth_account import Account; a = Account.create(); print(a.address, '0x' + a.key.hex())"
```

Write down the address and keep the key secret. Never use a key that holds
mainnet funds.

## Prepare the repository

1. Install the locked environment:

    ```bash
    uv sync --locked
    ```

2. Run a read that needs no key and no funds. The `--no-deploy` option deploys
   the contract on a local copy of the chain only, so nothing is sent.

    ```bash
    uv run --locked tutorials/read_state/run.py read --no-deploy \
        --user 0xYOUR_ADDRESS
    ```

    The last line is `All values match.` Use your own testnet address or any
    address that has a Core account.

## Get HYPE on HyperEVM

Your address needs about 0.015 HYPE in its EVM balance.

- Some HYPE faucets for HyperEVM testnet only give HYPE to addresses with a
  Hyperliquid mainnet account.
- If you have HYPE on Core spot, you can move it to HyperEVM in the Hyperliquid
  testnet app.

Check the EVM balance (the result is in wei, 18 decimals):

```bash
curl -s -X POST https://rpc.hyperliquid-testnet.xyz/evm -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_getBalance","params":["0xYOUR_ADDRESS","latest"]}'
```

## Get USDC on HyperCore

- The official faucet at
  [app.hyperliquid-testnet.xyz/drip](https://app.hyperliquid-testnet.xyz/drip)
  gives 1000 testnet USDC on Core. It gives USDC only to an address that has a
  Hyperliquid **mainnet** account. A new testnet key does not meet this
  condition.
- If you have an address with a mainnet account, claim the USDC with that
  address in the testnet app. Then send USDC from it to your testnet key with
  the [snippet below](#send-usdc-or-hype-on-core). The testnet signature is not
  valid on mainnet.
- A colleague with testnet USDC can also send you USDC on Core.
- The [Circle faucet](https://faucet.circle.com) gives HyperEVM testnet USDC on
  the **EVM** side. The tutorials don't use it: tutorial 4 makes its own EVM
  USDC with a return.

For tutorial 4 you also need 0.01 HYPE on Core spot. Buy it on the testnet spot
market HYPE/USDC in the app. The minimum order value is 10 USDC, so buy about
0.25 HYPE.

## Check your Core account

Check the Core balances (human units):

```bash
curl -s -X POST https://api.hyperliquid-testnet.xyz/info -H 'Content-Type: application/json' \
  -d '{"type":"spotClearinghouseState","user":"0xYOUR_ADDRESS"}'
```

Check the account mode:

```bash
curl -s -X POST https://api.hyperliquid-testnet.xyz/info -H 'Content-Type: application/json' \
  -d '{"type":"userAbstraction","user":"0xYOUR_ADDRESS"}'
```

A new user wallet starts in unified account mode (`unifiedAccount`). In this
mode, Core refuses a user-signed `spotSend` with "Action disabled when unified
account is active", so the tutorials use `sendAsset` for all Core transfers.
[Account mode](../modules/core-writer.md#account-mode) lists the modes.

## Send USDC or HYPE on Core

The tutorials use [`tutorials/send_core.py`](https://github.com/crowdcent/hyper-vyper/blob/main/tutorials/send_core.py) for Core transfers. It calls
`Exchange.send_asset` of the official
[hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk)
(version 0.24.0), from spot to spot. `uv` installs the SDK in a separate
environment for this script only.

Without `--execute`, the script only reads and prints the plan:

```bash
uv run --script tutorials/send_core.py --to 0xDESTINATION --token USDC --amount 2
```

```text
destination 0xDESTINATION: Core role 'missing'
This send activates the destination. You pay 1 USDC more as the fee.
plan: send_asset(0xDESTINATION, 'spot', 'spot', 'USDC:0xeb62eee3685fc4c43992febcd9e75443', 2.0)
plan only: add --execute to send. Nothing was sent.
```

With `--execute`, it signs with `HYPER_VYPER_CORE_FUNDER_KEY` and sends:

```bash
uv run --script tutorials/send_core.py --to 0xDESTINATION --token USDC --amount 2 --execute
```

The last line is `result: {'status': 'ok', 'response': {'type': 'default'}}`.

The script checks these rules before it sends:

- A send of 1 USDC or more to an address without a Core account activates that
  address. **You** pay the 1 USDC fee, in addition to the amount.
- The script refuses a smaller USDC send or a HYPE send to such an address.
- The script refuses a send that is larger than your available spot balance.

Here is the same transfer in your own code:

```python
import os

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

wallet = Account.from_key(os.environ["HYPER_VYPER_CORE_FUNDER_KEY"])
exchange = Exchange(wallet, constants.TESTNET_API_URL)
# The token is "NAME:tokenId" from the spotMeta info API request (testnet values).
usdc = "USDC:0xeb62eee3685fc4c43992febcd9e75443"
hype = "HYPE:0x7317beb7cceed72ef0b346074cc8e7ab"
result = exchange.send_asset("0xDESTINATION", "spot", "spot", usdc, 2.0)
print(result)  # {'status': 'ok', 'response': {'type': 'default'}}
```

## Set the environment variables

Type each key into a hidden prompt so it stays out of your shell history:

```bash
read -rs HYPER_VYPER_TESTNET_KEY && export HYPER_VYPER_TESTNET_KEY
read -rs HYPER_VYPER_CORE_FUNDER_KEY && export HYPER_VYPER_CORE_FUNDER_KEY
```

| Variable | Used by | Purpose |
|---|---|---|
| `HYPER_VYPER_TESTNET_KEY` | `tutorials/*/run.py --execute` | Deploys the contracts and sends the owner-only EVM calls |
| `HYPER_VYPER_CORE_FUNDER_KEY` | `tutorials/send_core.py --execute` | Sends USDC and HYPE on Core to the contracts |

If `HYPER_VYPER_CORE_FUNDER_KEY` is not set, the tutorial scripts print the
`send_core.py` command. You can then run it in a different terminal.

Remove the keys from the shell when you are done:

```bash
unset HYPER_VYPER_TESTNET_KEY HYPER_VYPER_CORE_FUNDER_KEY
```
