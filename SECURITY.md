# Security policy

hyper-vyper is unaudited and provided as is. Read the [security page](https://crowdcent.github.io/hyper-vyper/security/)
before you use it with funds.

## Report a vulnerability

Don't open a public issue for a security problem. Report it privately by email to
info@crowdcent.com, with "Security" in the subject line. Include the affected
file, the steps to reproduce, and the impact.

CrowdCent handles reports as its [security policy](https://crowdcent.com/security/)
describes, with the same response times and disclosure rules. The rewards in that
policy cover CrowdCent's own services and don't cover this library.

## Scope

In scope:

- The library modules in `src/hyper_vyper/`.
- `hyper-vyper-check-source` (`src/hyper_vyper/check_source.py`), the check for
  compiler advisory patterns.
- The HyperCore simulator in `src/hyper_vyper/testing/`, when it models HyperCore
  in a way that hides a bug that costs funds on the real chain.
- Incorrect statements in the documentation that can cause a loss of funds.

Out of scope:

- The example contracts in `examples/` and the tutorial tooling in `tutorials/`.
- The repository tests in `tests/`.
- Bugs in Vyper, HyperEVM, HyperCore, Circle contracts or the Solidity
  hyper-evm-lib. Report those to their maintainers.
- Policy checks that the documentation assigns to the importing contract.
