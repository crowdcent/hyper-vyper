# Modules

These pages are for readers who know Python but are new to smart contracts.
Each page walks through the real source code step by step and ends with
questions so you can check your understanding.

The code on these pages comes straight from
[`src/hyper_vyper/`](https://github.com/crowdcent/hyper-vyper/tree/main/src/hyper_vyper),
and a test checks that each quoted block still starts at the correct line.

Start with [concepts](../concepts.md), then read the pages in this order:

| Order | Module | What you learn |
|---|---|---|
| 1 | [`constants.vy`](constants.md) | Addresses, action headers, token indices and units |
| 2 | [`precompiles.vy`](precompiles.md) | How a contract reads HyperCore state |
| 3 | [`core_writer.vy`](core-writer.md) | How a contract sends actions to HyperCore |
| 4 | [`conversions.vy`](conversions.md) | How amounts change between EVM, Core and order units |
| 5 | [`bridge.vy`](bridge.md) | How funds move between HyperEVM and HyperCore |
