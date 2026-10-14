"""Record raw precompile replies from HyperEVM so tests use real chain data.

uv run --locked scripts/record_live_replies.py

The script reads the network and rewrites src/hyper_vyper/testing/data/live_replies.json.

Review the diff before committing. Live metadata can change over time.
"""

import json
from pathlib import Path

from eth_abi import encode

from hyper_vyper.testing import _precompiles as pc
from hyper_vyper.testing.live import MAINNET_RPC, TESTNET_RPC, RetryingRPC

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "hyper_vyper" / "testing" / "data" / "live_replies.json"
RPC = {999: RetryingRPC(MAINNET_RPC), 998: RetryingRPC(TESTNET_RPC)}

# (name, chain, precompile suffix, argument types, arguments)
READS = [
    ("token_info_usdc", 999, pc.TOKEN_INFO, ["uint64"], [0]),
    ("token_info_usdc", 998, pc.TOKEN_INFO, ["uint64"], [0]),
    ("token_info_hype", 999, pc.TOKEN_INFO, ["uint64"], [150]),
    ("token_info_hype", 998, pc.TOKEN_INFO, ["uint64"], [1105]),
    # STHYPE has one spot market, and that market is not quoted in USDC.
    ("token_info_sthype", 999, pc.TOKEN_INFO, ["uint64"], [119]),
    ("spot_info_sthype", 999, pc.SPOT_INFO, ["uint64"], [297]),
    ("spot_info_hype_usdc", 999, pc.SPOT_INFO, ["uint64"], [107]),
    # HYPE's other mainnet markets: none of them is quoted in USDC.
    ("spot_info_hype_207", 999, pc.SPOT_INFO, ["uint64"], [207]),
    ("spot_info_hype_232", 999, pc.SPOT_INFO, ["uint64"], [232]),
    ("spot_info_hype_255", 999, pc.SPOT_INFO, ["uint64"], [255]),
    ("perp_asset_info_btc", 999, pc.PERP_ASSET_INFO, ["uint32"], [0]),
    # Linked ERC-20s for the generic bridge: Core has more decimals than EVM (UBTC),
    # fewer (UETH), and a testnet token (PURR).
    ("token_info_ubtc", 999, pc.TOKEN_INFO, ["uint64"], [197]),
    ("token_info_ueth", 999, pc.TOKEN_INFO, ["uint64"], [221]),
    ("token_info_purr", 998, pc.TOKEN_INFO, ["uint64"], [1]),
]


def main():
    replies = []
    for name, chain, suffix, types, args in READS:
        block = int(RPC[chain].fetch("eth_blockNumber", []), 16)
        data = "0x" + encode(types, args).hex()
        call = {"to": pc.address(suffix), "data": data}
        reply = RPC[chain].fetch("eth_call", [call, hex(block)])
        replies.append(
            {
                "name": name,
                "chain_id": chain,
                "block": block,
                "precompile": f"0x{suffix:04x}",
                "input": data,
                "reply": reply,
            }
        )
    OUTPUT.write_text(json.dumps(replies, indent=2) + "\n")
    print(f"Wrote {len(replies)} replies to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
