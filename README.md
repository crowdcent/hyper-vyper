# hyper-vyper

![A cartoon snake in a hoodie codes on a laptop](https://raw.githubusercontent.com/crowdcent/hyper-vyper/main/docs/assets/images/hero.png)

[![Library checks](https://github.com/crowdcent/hyper-vyper/actions/workflows/test.yml/badge.svg)](https://github.com/crowdcent/hyper-vyper/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/crowdcent/hyper-vyper/blob/main/LICENSE)

**Build Vyper contracts on HyperEVM that read and write to HyperCore.**

hyper-vyper gives your HyperEVM contracts one typed interface to HyperCore, so you
can work on your protocol instead of byte layouts and decimal conversions:

- **Read Core state:** balances, perp positions, prices, and token and market
  metadata.
- **Send CoreWriter actions:** orders, cancels, transfers, staking, vault moves and
  account settings.
- **Bridge assets** (USDC, HYPE and linked ERC-20 tokens) between HyperEVM and
  HyperCore, with the decimal conversions done for you.
- **Test without a testnet:** `hyper_vyper.testing` adds a HyperCore simulator to
  your Titanoboa tests.

The library has no state and nothing to deploy. It is a Vyper port of the Solidity
[hyper-evm-lib](https://github.com/hyperliquid-dev/hyper-evm-lib/tree/4eb7ab044d0a368e0c01ec5b38d5ea48a3e3b427),
and its tests check that both libraries behave the same.

hyper-vyper is open source under the MIT license and maintained by
[CrowdCent](https://crowdcent.com).

> **Unaudited.** This library is provided as is. Read
> [security](https://crowdcent.github.io/hyper-vyper/security/) before you use it with funds.

| Module | Purpose |
|---|---|
| `precompiles` | Read Core balances, positions, prices and metadata |
| `core_writer` | Encode and send CoreWriter actions: orders, transfers, staking and more |
| `conversions` | Convert amounts between EVM, Core and order-size units |
| `bridge` | Move USDC, HYPE and linked ERC-20 tokens between HyperEVM and HyperCore |
| `constants` | Addresses, action headers and enum values |

```vyper
from hyper_vyper import constants
from hyper_vyper import precompiles

@external
@view
def core_usdc_balance(user: address) -> uint64:
    return precompiles.spot_balance(user, constants.USDC_TOKEN_INDEX).total
```

## Installation

hyper-vyper is a Python package of Vyper modules. Vyper finds them on the
Python path, so you don't need a `-p` option.

```bash
uv add hyper-vyper        # or: pip install hyper-vyper
```

The package pins **Vyper 0.4.3** exactly. Every module has
`# pragma version 0.4.3`, and the library is tested only on 0.4.3. Use the
Cancun EVM version.

The `testing` extra adds `hyper_vyper.testing`, a HyperCore simulator for
Titanoboa tests (`uv add --dev "hyper-vyper[testing]"`):

```python
from hyper_vyper.testing import CoreSim, Policy
```

See [install and quick start](https://crowdcent.github.io/hyper-vyper/getting-started/),
which also covers Moccasin, and the
[testing quick start](https://crowdcent.github.io/hyper-vyper/testing/quick-start/).

## Documentation

The documentation site is at
[crowdcent.github.io/hyper-vyper](https://crowdcent.github.io/hyper-vyper/).

- [Concepts](https://crowdcent.github.io/hyper-vyper/concepts/): HyperEVM and HyperCore, asynchronous actions, units
- [Tutorials](https://crowdcent.github.io/hyper-vyper/tutorials/): five testnet tutorials, each with a
  contract and a script
- [Testing](https://crowdcent.github.io/hyper-vyper/testing/quick-start/): test your contracts with the HyperCore simulator
- [Modules](https://crowdcent.github.io/hyper-vyper/modules/): each module explained with its source code
- [API](https://crowdcent.github.io/hyper-vyper/reference/api/)
- [Solidity compatibility](https://crowdcent.github.io/hyper-vyper/reference/compatibility/)
- [Security](https://crowdcent.github.io/hyper-vyper/security/)

To preview the docs site locally, see
[contributing](https://crowdcent.github.io/hyper-vyper/contributing/).

## Development

```bash
uv sync --locked
uv run --locked hyper-vyper-check-source src examples tutorials
uv run --locked pytest
```

See [repository tests](https://crowdcent.github.io/hyper-vyper/testing/repository-tests/) and
[contributing](https://github.com/crowdcent/hyper-vyper/blob/main/CONTRIBUTING.md).
`examples/` holds example contracts, and `tutorials/` holds the tutorial
contracts and scripts. Report security problems as described in
[SECURITY.md](https://github.com/crowdcent/hyper-vyper/blob/main/SECURITY.md).

## Acknowledgements

- [hyper-evm-lib](https://github.com/hyperliquid-dev/hyper-evm-lib) by
  hyperliquid-dev, the Solidity library that hyper-vyper ports.
- The [Hyperliquid documentation](https://hyperliquid.gitbook.io/hyperliquid-docs)
  on HyperEVM, HyperCore and CoreWriter.
- The [Circle documentation](https://developers.circle.com/cctp/concepts/cctp-on-hypercore)
  on USDC and the CoreDepositWallet on HyperCore.

## License

MIT. The Solidity reference sources in `tests/reference/` keep their own MIT
licenses.
