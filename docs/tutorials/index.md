# Tutorials

In each tutorial, you deploy a small contract on HyperEVM **testnet** (chain
998), then use a Python script to call it and read the result on HyperCore.

## What you need

- Python 3.11 or later and [`uv`](https://docs.astral.sh/uv/).
- This repository. Run all commands from the repository root.
- A testnet key with a little HYPE on HyperEVM for gas.
- USDC in the spot balance of your testnet Core account, and for one tutorial
  a little HYPE.

[Testnet setup](testnet-setup.md) explains how to get these items and which
faucets have conditions.

If HyperEVM, HyperCore, spot and perp are new to you, read
[where your USDC can be](../concepts.md#where-your-usdc-can-be) first.

## How the scripts work

Each tutorial has one script, `tutorials/<name>/run.py`. The script has steps,
for example `deploy`, `fund` and `status`, and you give the step as the first
argument. The scripts use [Titanoboa](https://github.com/vyperlang/titanoboa)
to call the contracts.

- Without `--execute`, a step runs on a local copy of the chain and prints what
  it would do. It signs nothing and sends nothing.
- With `--execute`, the script reads the EVM key from the
  `HYPER_VYPER_TESTNET_KEY` environment variable and sends real transactions.
  It never prints the key. Titanoboa runs each call locally first, so a call
  that would revert stops with its revert reason, and nothing is sent.
- The local copy of the chain has no HyperCore precompiles, so the scripts use
  [`forward_precompiles`](../testing/quick-start.md#test-against-live-hypercore-state),
  which answers each read from the testnet node.
- Each script stops if the RPC does not report chain ID 998.
- Core transfers come from your own Core account. The script
  [`tutorials/send_core.py`](https://github.com/crowdcent/hyper-vyper/blob/main/tutorials/send_core.py)
  sends them with the official Python SDK and reads its key from
  `HYPER_VYPER_CORE_FUNDER_KEY`. If that variable is not set, the tutorial
  script prints the command so you can run it yourself.
- The deploy step writes the contract address to `tutorials/.state/<name>.json`,
  a directory that Git ignores.
- After a transaction, the script waits for the receipt. Then it reads the
  contract once per EVM block until the result shows, for up to 20 blocks.

The sample output comes from testnet runs. Addresses, hashes and balances are
examples. `N` is the first EVM block in an output, `N+10` is ten blocks later,
and `M` is a Core block.

## The tutorials

Do the tutorials in this order. Each tutorial deploys its own contract. If you
have no Core HYPE, buy some before tutorial 4, as
[testnet setup](testnet-setup.md#get-usdc-on-hypercore) describes.

| Tutorial | What you'll learn | Core funds that you send |
|---|---|---|
| [1. Read Core state](read-state.md) | Read balances, positions and prices on Core from a contract, and check them against the info API. | None |
| [2. Activate a contract account](activate-account.md) | Why a new contract can't use Core yet, where HYPE sent before activation goes, and how a 1 USDC Core send activates the account. | 2 USDC + 1 USDC fee |
| [3. Move USDC between spot and perp](spot-perp.md) | Move USDC between the spot and perp balances of a Core account, with the right units. | 5 USDC + 1 USDC fee |
| [4. Move USDC between EVM and Core](evm-core.md) | Return USDC from Core to EVM and deposit it back, with pending records, gas costs and a silent-failure demo. | 6 USDC + 1 USDC fee, 0.01 HYPE |
| [5. Place spot and perp orders](spot-order.md) | Buy and sell HYPE on spot, and open and close a BTC perp position, with valid prices and sizes. | 18 USDC + 1 USDC fee |

The cleanup step of each tutorial sends the remaining funds back to you. You
lose only the activation fees (1 USDC for each contract), the trading fees and
the Core gas of the returns in tutorial 4.

## Safety rules

- Use a key that you use only on testnet. Never use a key that holds mainnet
  funds.
- Do not write the key into a file in the repository. Git ignores `.env*`
  files, but your shell history can still keep a key. Use `read -rs` (see
  [testnet setup](testnet-setup.md#set-the-environment-variables)).
- The tutorial contracts are examples and nobody has audited them. Do not
  deploy them on mainnet.
