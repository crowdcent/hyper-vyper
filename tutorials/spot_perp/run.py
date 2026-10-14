"""Tutorial 3: move USDC between spot and perp (transfer_usd_class).

uv run --locked tutorials/spot_perp/run.py deploy --execute
uv run --locked tutorials/spot_perp/run.py to-perp --amount 3     # plan only
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tutorials import _common as c  # noqa: E402

CONTRACT = Path(__file__).with_name("spot_perp.vy")


def show(x: dict, log) -> None:
    log(f"  spot USDC      {c.amount(x['spot_usdc'], 8, 'USDC')}")
    log(f"  perp value     {c.amount(x['perp_account_value'], 6, 'USD')}")
    log(f"  withdrawable   {c.amount(x['withdrawable'], 6, 'USD')}")


def move(s: c.Session, args) -> None:
    to_perp = args.step == "to-perp"
    ntl = c.parse_amount(args.amount, 6)
    before = s.read()
    s.log(f"before (EVM block {before['evm_block']}):")
    show(before, s.log)
    if not before["core_exists"]:
        raise c.StepError("The Core account is not activated. Run the fund step first.")
    if to_perp and before["spot_usdc"] - before["spot_usdc_hold"] < ntl * 100:
        raise c.StepError(f"Spot has {c.amount(before['spot_usdc'], 8, 'USDC')}.")
    if not to_perp and before["withdrawable"] < ntl:
        raise c.StepError(f"Perp withdrawable is {c.amount(before['withdrawable'], 6, 'USD')}.")
    s.log(f"move {c.amount(ntl, 6, 'USD')} {'spot -> perp' if to_perp else 'perp -> spot'}")
    s.log(f"  spot changes by {ntl * 100} Core wei (8 decimals): ntl x 100")
    if not s.send("move_usdc", ntl, to_perp):
        return
    sign = -1 if to_perp else 1
    after, ok = s.wait_for(
        lambda x: x["spot_usdc"] == before["spot_usdc"] + sign * ntl * 100,
        lambda x: (
            f"spot USDC {c.human(x['spot_usdc'], 8)}, perp {c.human(x['perp_account_value'], 6)}"
        ),
    )
    if not ok:
        raise c.StepError("No change. Core rejected the move silently.")
    s.log(f"after (EVM block {after['evm_block']}):")
    show(after, s.log)
    s.log(f"change: spot USDC {c.amount(after['spot_usdc'] - before['spot_usdc'], 8, 'USDC')}")
    perp = after["perp_account_value"] - before["perp_account_value"]
    s.log(f"        perp value {c.amount(perp, 6, 'USD')}")


def status(s: c.Session, args) -> None:
    x = s.read()
    s.log(f"EVM block {x['evm_block']}, core_user_exists {x['core_exists']}")
    show(x, s.log)


STEPS = {
    "deploy": ("Deploy the contract.", c.deploy_step),
    "fund": (
        "Send --usdc USDC on Core to the contract. It activates it.",
        lambda s, a: c.fund(s, a.usdc),
    ),
    "status": ("Show the spot and perp balances, with units.", status),
    "to-perp": ("Move --amount USDC from Core spot to Core perp.", move),
    "to-spot": ("Move --amount USDC from Core perp back to Core spot.", move),
    "sweep": ("Cleanup: send the Core USDC and HYPE of the contract to the owner.", c.sweep_step),
}
OPTIONS = {"--usdc": ("5", "USDC for the fund step"), "--amount": ("3", "USDC to move")}

if __name__ == "__main__":
    sys.exit(c.main(__doc__, CONTRACT, STEPS, OPTIONS))
