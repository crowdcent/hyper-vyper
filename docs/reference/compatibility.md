# Solidity compatibility

For every supported input, the Vyper library must send the same bytes and return
the same values as the Solidity library. Names follow Vyper style, and where the
Solidity library truncates a value, the Vyper library reverts instead.

## Pinned reference

| Input | Pin |
|---|---|
| `hyperliquid-dev/hyper-evm-lib` | `4eb7ab044d0a368e0c01ec5b38d5ea48a3e3b427` |
| OpenZeppelin, as used by hyper-evm-lib | `c64a1edb67b6e3f4a15cca8909c9482ad33a02b0` |
| Solidity test compiler | solc 0.8.30, Cancun, optimizer 200 runs |
| Vyper test compiler | Vyper 0.4.3, Cancun, gas optimization |

The [comparison tests](../testing/repository-tests.md#comparison-with-solidity)
run the compiled Solidity functions, and their MIT licenses are in
[`tests/reference/`](https://github.com/crowdcent/hyper-vyper/tree/main/tests/reference).

## Intentional differences

| Area | Vyper behavior |
|---|---|
| Variable-length data | Names and lists have bounds. A larger reply reverts. |
| Read resources | Gas and output size have fixed limits. |
| Network | An unsupported chain reverts. Solidity uses mainnet values. |
| Token index in conversions | A value above uint32 reverts. Solidity truncates it. |
| Size scale factor | Checked. Solidity can truncate it. |
| USDC deposit destination | The caller gives the DEX. The general Solidity function uses spot. |
| USDC return source | The caller gives the DEX. The general Solidity function uses spot. |
| USDC configuration | Checks that USDC links to the deposit wallet and has the expected decimals before a write. |
| Allowance | Sets the deposit-wallet allowance back to zero after a deposit. |
| Recipient and amount | USDC functions reject a zero recipient and a zero amount. |
| `spot_index_for_token` | Always requires a market quoted in USDC. Solidity returns the only market of a token without this check. |
| Token index in bridge functions | A value above uint32 reverts. Solidity reads the metadata of the truncated index but sends to the system address of the full index. |
| Bridge remainders | Rejects an amount that does not convert exactly between EVM units and Core wei. Solidity sends it, and the remainder is burned or lost. |
| `bridge_to_evm` with a Core amount | Requires a linked token or HYPE, and rejects zero. Solidity sends these amounts. |
| `token_index` | Checks the registry answer against `token_info`, and rejects the CoreDepositWallet, which the registry maps to USDC. Anyone can write to the registry. Solidity returns the answer unchecked. |
| ERC-20 bridge to Core | Reads `token_info` once. Solidity reads it twice. |
| `bridge_erc20_to_core` | Rejects USDC and HYPE. Solidity has no separate ERC-20 function. |
| Address variants | Not included. Use `conversions.token_index` with the index version. |
| `token_index` network | An unsupported chain reverts. Solidity uses mainnet values. |
| Errors | Vyper assertions. The error bytes can be different from Solidity. |

Both libraries check amount and asset-ID overflows, read token metadata before
they apply the HYPE fallback, and check the vault lock with a strict comparison
in milliseconds.

## Coverage

The tests compare every action and every read with the Solidity library, along
with the conversions, the vault lock check, and the bridge routes for USDC, HYPE
and linked ERC-20 tokens.

Hyperliquid documents some features that neither library supports:

- CoreWriter action 17 (outcome operations) and precompile `0x0814`.
- The legacy position precompile `0x0800`. Both libraries read `0x0813` instead.

Changes to hyper-evm-lib after the pinned commit are not included. At release
0.1.0, the pinned commit was the latest commit on its main branch.
