"""Tutorial 5: place IOC spot and perp orders through CoreWriter.

uv run --locked tutorials/spot_order/run.py deploy --execute
uv run --locked tutorials/spot_order/run.py buy --usdc 12          # plan only
uv run --locked tutorials/spot_order/run.py perp-open --usd 11     # plan only

The script reads the order book from the info API, sets the limit price 1%
(--slippage) beyond the best price, and rounds the price to a valid tick and the
size to the lot size.
"""

import sys
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tutorials import _common as c  # noqa: E402

CONTRACT = Path(__file__).with_name("spot_order.vy")
HYPE_USDC = "@1035"  # testnet spot market 1035: tokens [1105 (HYPE), 0 (USDC)]
BTC_PERP = 3  # testnet: a perp's asset ID is its perp index
MIN_VALUE = Decimal(10)  # Hyperliquid: "Order must have minimum value of $10."


def order(
    book: dict,
    is_buy: bool,
    value: Decimal,
    sz_decimals: int,
    max_decimals: int,
    slippage: Decimal,
    size: Decimal | None = None,
) -> dict:
    """An IOC order: the limit is the best price moved by `slippage` into the book, with
    at most 5 significant figures and max_decimals - sz_decimals decimals. A buy spends
    about `value`. A sell sells `size`. CoreWriter takes both as 10**8 times the value."""
    best = Decimal(book["levels"][1 if is_buy else 0][0]["px"])
    px = best * (1 + slippage if is_buy else 1 - slippage)
    exponent = min(0, max(px.adjusted() - 4, sz_decimals - max_decimals))
    limit = px.quantize(Decimal(1).scaleb(exponent), ROUND_UP if is_buy else ROUND_DOWN)
    sz = (value / limit if is_buy else size).quantize(Decimal(1).scaleb(-sz_decimals), ROUND_DOWN)
    return {
        "best": best,
        "limit": limit,
        "sz": sz,
        "limit_e8": int(limit * 10**8),
        "sz_e8": int(sz * 10**8),
        "value": limit * sz,
    }


def check(s: c.Session, o: dict, side: str, asset: str, unit: str) -> None:
    s.log(f"order: IOC {side} {o['sz']} {asset} at limit {o['limit']} (best {o['best']})")
    s.log(f"  encoded: limit_px {o['limit_e8']}, sz {o['sz_e8']} (x 10**8)")
    s.log(f"  value at the limit: {o['value']} {unit}")
    if o["sz"] <= 0 or o["value"] < MIN_VALUE:
        raise c.StepError(f"The order value is below {MIN_VALUE} {unit}. Core would reject it.")


def spot(s: c.Session, args) -> None:
    """A buy for about --usdc USDC, or a sell of all available HYPE."""
    is_buy = args.step == "buy"
    before = s.read()
    if not before["core_exists"]:
        raise c.StepError("The Core account is not activated. Run the fund step first.")
    name, tokens = s.contract.market()
    sz_decimals = next(
        t["szDecimals"] for t in s.info.spot_meta()["tokens"] if t["index"] == c.HYPE_TOKEN
    )
    s.log(f"market {name}: tokens {list(tokens)}, HYPE sz_decimals {sz_decimals}")
    hype = Decimal(before["spot_hype"] - before["spot_hype_hold"]) / 10**8
    o = order(
        s.info.l2_snapshot(HYPE_USDC),
        is_buy,
        Decimal(args.usdc),
        sz_decimals,
        8,
        Decimal(args.slippage),
        hype,
    )
    check(s, o, "buy" if is_buy else "sell", "HYPE", "USDC")
    if not s.send("place_ioc", is_buy, o["limit_e8"], o["sz_e8"]):
        return
    after, ok = s.wait_for(
        lambda x: x["spot_hype"] != before["spot_hype"],
        lambda x: f"spot HYPE {c.human(x['spot_hype'], 8)}, USDC {c.human(x['spot_usdc'], 8)}",
    )
    if not ok:
        s.log("No fill: the order did not match within the limit.")
        return
    hype, usdc = after["spot_hype"] - before["spot_hype"], after["spot_usdc"] - before["spot_usdc"]
    s.log(f"filled: spot HYPE {c.amount(hype, 8, 'HYPE')}")
    s.log(f"        spot USDC {c.amount(usdc, 8, 'USDC')}")


def move(s: c.Session, args) -> None:
    to_perp = args.step == "to-perp"
    x = s.read()
    if not to_perp and x["btc_szi"] != 0:
        raise c.StepError("Close the BTC position first (perp-close).")
    ntl = c.parse_amount(args.amount, 6) if to_perp else x["withdrawable"]
    s.log(f"move {c.amount(ntl, 6, 'USD')} {'spot -> perp' if to_perp else 'perp -> spot'}")
    if ntl:
        c.move_withdrawable(s, ntl, to_perp)


def perp(s: c.Session, args) -> None:
    """Open a BTC long for about --usd USD, or close the whole position (reduce-only)."""
    is_open = args.step == "perp-open"
    before = s.read()
    coin, _, sz_decimals, max_leverage, _ = s.contract.perp_market()
    s.log(f"perp {coin} (asset {BTC_PERP}): sz_decimals {sz_decimals}, max leverage {max_leverage}")
    if is_open and before["withdrawable"] == 0:
        raise c.StepError("Perp has no margin. Run the to-perp step first.")
    if not is_open and before["btc_szi"] <= 0:
        raise c.StepError("There is no long BTC position to close.")
    held = Decimal(before["btc_szi"]).scaleb(-sz_decimals)
    o = order(
        s.info.l2_snapshot("BTC"),
        is_open,
        Decimal(args.usd),
        sz_decimals,
        6,
        Decimal(args.slippage),
        held,
    )
    check(s, o, "buy" if is_open else "sell (reduce-only)", "BTC", "USD")
    if not s.send("place_perp_ioc", is_open, o["limit_e8"], o["sz_e8"], not is_open):
        return
    after, ok = s.wait_for(
        lambda x: x["btc_szi"] != before["btc_szi"], lambda x: f"BTC szi {x['btc_szi']}"
    )
    if not ok:
        s.log("No fill: the order did not match within the limit.")
        return
    size = Decimal(after["btc_szi"]).scaleb(-sz_decimals)
    s.log(
        f"position: szi {after['btc_szi']} ({c.human(after['btc_szi'], sz_decimals)} BTC), "
        f"entry notional {c.amount(after['btc_entry_ntl'], 6, 'USD')}"
    )
    for p in s.info.user_state(s.contract.address)["assetPositions"]:
        s.log(f"  info API: {p['position']['coin']} szi {p['position']['szi']}")
    if size == 0:
        s.log("The position is closed.")


def status(s: c.Session, args) -> None:
    x = s.read()
    s.log(f"EVM block {x['evm_block']}, core_user_exists {x['core_exists']}")
    s.log(f"  spot USDC {c.amount(x['spot_usdc'], 8, 'USDC')}")
    s.log(f"  spot HYPE {c.amount(x['spot_hype'], 8, 'HYPE')}")
    s.log(f"  withdrawable {c.amount(x['withdrawable'], 6, 'USD')}, BTC szi {x['btc_szi']}")


STEPS = {
    "deploy": ("Deploy the contract.", c.deploy_step),
    "fund": (
        "Send --fund-usdc USDC on Core to the contract. It activates it.",
        lambda s, a: c.fund(s, a.fund_usdc),
    ),
    "status": ("Show the Core balances and the BTC position.", status),
    "buy": ("IOC buy of HYPE for about --usdc USDC.", spot),
    "sell": ("IOC sell of all available HYPE.", spot),
    "to-perp": ("Move --amount USDC from Core spot to Core perp, as margin.", move),
    "perp-open": ("IOC buy (long) of BTC perp for about --usd USD.", perp),
    "perp-close": ("Reduce-only IOC sell that closes the whole BTC position.", perp),
    "to-spot": ("Move all withdrawable perp USD back to Core spot.", move),
    "sweep": ("Cleanup: send the Core USDC and HYPE of the contract to the owner.", c.sweep_step),
}
OPTIONS = {
    "--fund-usdc": ("18", "USDC for the fund step"),
    "--usdc": ("12", "USDC to spend in the buy step"),
    "--amount": ("3", "USDC to move to perp"),
    "--usd": ("11", "USD value of the BTC long"),
    "--slippage": ("0.01", "limit beyond the best price (0.01 = 1%%)"),
}

if __name__ == "__main__":
    sys.exit(c.main(__doc__, CONTRACT, STEPS, OPTIONS))
