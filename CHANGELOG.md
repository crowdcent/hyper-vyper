# Changelog

## 0.1.0

First public release. The library is unaudited and provided as is.

- `precompiles`: typed reads of HyperCore state through the HyperEVM read
  precompiles, covering balances, positions, margin summaries, vault equity,
  staking, prices, best bid and offer, token, spot and perp metadata, token
  supply, borrow/lend state and the L1 block number. Replies decode into
  bounded types, and a failed read or a bad reply reverts.
- `core_writer`: encoders for the CoreWriter actions 1 to 13, 15 and 16.
- `conversions`: amount conversions between EVM units, Core wei, order sizes and
  perp USD, with checked arithmetic, plus network values and a TokenRegistry
  lookup that is cross-checked against `token_info`.
- `bridge`: USDC transfers through the Circle CoreDepositWallet and back with
  `send_asset`, and HYPE and linked ERC-20 transfers through system addresses.
- `constants`: addresses, action headers, chain IDs, token indices and enum
  values from hyper-evm-lib at commit `4eb7ab0`.
- Tests compare every action and read with the pinned Solidity hyper-evm-lib,
  and a HyperCore simulator models the asynchronous Core side.
- Tutorials for HyperEVM testnet: Core reads, account activation, USDC between
  spot and perp, USDC between EVM and Core, and spot and perp orders.
- Example contracts: `examples/read_core.vy`, `examples/usdc_bridge.vy` and
  `examples/spot_round_trip.vy`.
- Packaging: a wheel with the `hyper_vyper` modules, which Vyper finds on the
  Python path without `-p`. The package pins Vyper 0.4.3.
- `hyper_vyper.testing` (extra `testing`): the `CoreSim` HyperCore simulator for
  Titanoboa tests, with `Policy` settings for timing and for accounts that are
  not activated, and `forward_precompiles`, which answers the HyperCore read
  precompiles from a live node in Titanoboa fork and network mode.
- `hyper_vyper.testing.measured`: the activation fee and the return gas,
  measured with transactions on mainnet and testnet. The `Policy` defaults and
  the tutorial scripts use these values.
- `hyper-vyper-check-source`: a command that rejects the source patterns of the
  published Vyper 0.4.3 advisories. Run it on your own contracts too.
