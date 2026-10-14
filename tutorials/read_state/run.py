"""Tutorial 1: read HyperCore state from a contract, and compare it with the info API.

uv run --locked tutorials/read_state/run.py deploy --execute
uv run --locked tutorials/read_state/run.py read --user 0xYOUR_ADDRESS
uv run --locked tutorials/read_state/run.py read --user 0xYOUR_ADDRESS --no-deploy
"""

import sys
from decimal import Decimal
from pathlib import Path

import boa

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tutorials import _common as c  # noqa: E402

CONTRACT = Path(__file__).with_name("read_state.vy")


def compare(s: c.Session, user: str, perp: int) -> None:
    """Print each precompile value next to the info API value."""
    u = s.read("read_user", user)
    p = s.read("read_perp", perp)
    s.log(f"EVM block {u['evm_block']}, Core block {u['l1_block']}, user {user}")
    role = s.info.user_role(user)["role"]
    spot = s.info.spot_user_state(user)
    margin = s.info.user_state(user)
    meta, ctxs = s.info.meta_and_asset_ctxs()
    asset, ctx = meta["universe"][perp], ctxs[perp]
    price_scale = 6 - p["sz_decimals"]  # a perp price has 6 - sz_decimals decimals
    rows = [
        ("core_user_exists", u["core_exists"], role, u["core_exists"] == (role != "missing")),
        (
            "perp account value",
            c.amount(u["perp"][0], 6, "USD"),
            margin["marginSummary"]["accountValue"],
            u["perp"][0] == c.from_info(margin["marginSummary"]["accountValue"], 6),
        ),
        (
            "perp withdrawable",
            c.amount(u["withdrawable"], 6, "USD"),
            margin["withdrawable"],
            u["withdrawable"] == c.from_info(margin["withdrawable"], 6),
        ),
        (f"perp {perp} name", p["coin"], asset["name"], p["coin"] == asset["name"]),
        (
            f"perp {perp} sz_decimals",
            p["sz_decimals"],
            asset["szDecimals"],
            p["sz_decimals"] == asset["szDecimals"],
        ),
    ]
    for symbol, token, balance in (
        ("HYPE", c.HYPE_TOKEN, u["spot_hype"]),
        ("USDC", c.USDC_TOKEN, u["spot_usdc"]),
    ):
        api = c.info_balance(spot, token)
        rows.insert(
            1,
            (f"spot {symbol}", c.amount(balance[0], 8, symbol), c.human(api, 8), balance[0] == api),
        )
    for label, raw, api in (
        ("mark price", p["mark_px"], ctx["markPx"]),
        ("oracle price", p["oracle_px"], ctx["oraclePx"]),
    ):
        price = Decimal(raw).scaleb(-price_scale)
        ok = abs(price - Decimal(api)) <= Decimal(api) * Decimal("0.005")
        rows.append((label, f"{raw} / 10**{price_scale} = {c.human(raw, price_scale)}", api, ok))
    width = max(len(r[0]) for r in rows)
    for label, onchain, api, ok in rows:
        s.log(
            f"  [{'ok  ' if ok else 'DIFF'}] {label:<{width}}  precompile {onchain}  |  "
            f"info API {api}"
        )
    if c.info_balance(spot, c.HYPE_TOKEN, "evmEscrows"):
        s.log(f"  note: the info API shows an escrow (evmEscrows): {spot['evmEscrows']}")
    differ = [r[0] for r in rows if not r[3]]
    if differ:
        s.log(
            f"{len(differ)} values differ: {', '.join(differ)}. Prices move between the "
            "two reads, so run the step again."
        )
    else:
        s.log("All values match.")


def read(s: c.Session, args) -> None:
    user = args.user or s.signer
    if not user:
        raise c.StepError("Give --user 0x... (the address to read)")
    if not args.no_deploy:
        compare(s, user, int(args.perp))
        return
    if s.execute:
        raise c.StepError("--no-deploy only reads. Run it without --execute.")
    with boa.env.anchor():
        s._contract = s.deployer.deploy()
        s.log("no deployment: the contract runs on a local copy of the chain")
        compare(s, user, int(args.perp))


STEPS = {
    "deploy": ("Deploy the read contract.", c.deploy_step),
    "read": ("Read --user and perp --perp through the contract. Compare with the info API.", read),
}
OPTIONS = {
    "--user": (None, "the address to read"),
    "--perp": ("3", "perp index (3 = BTC on testnet)"),
    "--no-deploy": (False, "deploy on a local copy of the chain only"),
}

if __name__ == "__main__":
    sys.exit(c.main(__doc__, CONTRACT, STEPS, OPTIONS))
