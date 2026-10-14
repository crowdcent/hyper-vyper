"""Tutorial 4: move USDC between EVM and Core, with a pending record for each transfer.

uv run --locked tutorials/evm_core/run.py deploy --execute
uv run --locked tutorials/evm_core/run.py return-spot --amount 2     # plan only
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tutorials import _common as c  # noqa: E402

CONTRACT = Path(__file__).with_name("evm_core.vy")
ABANDON_AFTER = "After 200 L1 blocks (about 15 seconds), run the abandon step."


def show(x: dict, log) -> None:
    log(f"  core_user_exists {x['core_exists']}")
    log(f"  Core spot USDC   {c.amount(x['spot_usdc'], 8, 'USDC')}")
    log(f"  Core spot HYPE   {c.amount(x['spot_hype'], 8, 'HYPE')}")
    log(f"  withdrawable     {c.amount(x['withdrawable'], 6, 'USD')}")
    log(f"  EVM USDC         {c.amount(x['evm_usdc'], 6, 'USDC')}")
    log(f"  owner Core USDC  {c.amount(x['owner_spot_usdc'], 8, 'USDC')}")
    log(f"  pending          {x['has_pending']} (observed {x['observed']})")


def start(s: c.Session) -> dict:
    before = s.read()
    s.log(f"before (EVM block {before['evm_block']}):")
    show(before, s.log)
    if before["has_pending"]:
        raise c.StepError(f"A transfer is pending. Confirm it if it arrived. {ABANDON_AFTER}")
    return before


def to_perp(s: c.Session, args) -> None:
    c.move_withdrawable(s, c.parse_amount(args.amount, 6), True)


def give_back(s: c.Session, args) -> None:
    """Return USDC from Core spot or perp to EVM, wait for it, then confirm."""
    from_perp, too_much = args.step == "return-perp", args.step == "return-too-much"
    before = start(s)
    value = before["spot_usdc"] // 100 + 10**6 if too_much else c.parse_amount(args.amount, 6)
    if too_much:
        s.log("Failure demo: this return is 1 USDC more than the Core spot balance.")
    if before["spot_hype"] < c.RETURN_GAS_HYPE:
        s.log(
            f"Note: the contract has no Core HYPE, so Core takes the gas in USDC: about "
            f"{c.amount(c.RETURN_GAS_USDC, 8, 'USDC')}."
        )
    s.log(f"return {c.amount(value, 6, 'USDC')} from Core {'perp' if from_perp else 'spot'} to EVM")
    sent = (
        s.send("return_spot_unchecked", value)
        if too_much
        else s.send("return_usdc", value, from_perp)
    )
    if not sent:
        return
    after, ok = s.wait_for(
        lambda x: x["observed"],
        lambda x: (
            f"EVM USDC {c.human(x['evm_usdc'], 6)}, spot USDC {c.human(x['spot_usdc'], 8)}, "
            f"withdrawable {c.human(x['withdrawable'], 6)}, spot HYPE {c.human(x['spot_hype'], 8)}"
        ),
    )
    for label, field, decimals, symbol in (
        ("EVM USDC", "evm_usdc", 6, "USDC"),
        ("Core spot USDC", "spot_usdc", 8, "USDC"),
        ("withdrawable", "withdrawable", 6, "USD"),
        ("Core spot HYPE", "spot_hype", 8, "HYPE"),
    ):
        s.log(f"change: {label} {c.amount(after[field] - before[field], decimals, symbol)}")
    if not ok:
        s.log(
            f"NOT observed: Core rejected the return. The EVM transaction succeeded, and the "
            f"return stays pending. {ABANDON_AFTER}"
        )
        return
    s.log("observed: the USDC is on EVM. Confirm the pending return.")
    s.send("confirm")


def deposit(s: c.Session, args) -> None:
    """Deposit EVM USDC into the owner's Core spot, wait for it, then confirm."""
    before = start(s)
    value = c.parse_amount(args.amount, 6)
    owner = s.contract.OWNER()
    if s.info.user_role(owner)["role"] == "missing":
        raise c.StepError(f"The owner {owner} has no Core account. See testnet setup.")
    s.log(f"deposit {c.amount(value, 6, 'USDC')} into the Core spot balance of {owner}")
    if not s.send("deposit", value):
        return
    after, ok = s.wait_for(
        lambda x: x["observed"],
        lambda x: f"owner Core spot USDC {c.human(x['owner_spot_usdc'], 8)}",
    )
    s.log(f"change: EVM USDC {c.amount(after['evm_usdc'] - before['evm_usdc'], 6, 'USDC')}")
    owner_change = after["owner_spot_usdc"] - before["owner_spot_usdc"]
    s.log(f"        owner Core spot USDC {c.amount(owner_change, 8, 'USDC')}")
    if not ok:
        s.log(
            "NOT observed: Core did not credit the deposit. On testnet, the deposit wallet "
            f"credits only an address with a mainnet account. {ABANDON_AFTER}"
        )
        return
    s.log("observed: the USDC is on Core. Confirm the pending deposit.")
    s.send("confirm")


def remove_hype(s: c.Session, args) -> None:
    c.sweep(s, fields=("spot_hype",))


def withdraw(s: c.Session, args) -> None:
    value = s.read()["evm_usdc"]
    s.log(f"send {c.amount(value, 6, 'USDC')} to the owner on EVM")
    if value:
        s.send("withdraw_usdc", value)


def status(s: c.Session, args) -> None:
    x = s.read()
    s.log(f"EVM block {x['evm_block']}")
    show(x, s.log)


STEPS = {
    "deploy": ("Deploy the contract.", c.deploy_step),
    "fund": (
        "Send --usdc USDC, then --hype HYPE on Core to it.",
        lambda s, a: c.fund(s, a.usdc, a.hype),
    ),
    "status": ("Show the Core and EVM balances and the pending transfer.", status),
    "to-perp": ("Move --amount USDC from Core spot to Core perp.", to_perp),
    "return-spot": ("Return --amount USDC from Core spot to EVM, then confirm.", give_back),
    "return-perp": ("Return --amount USDC from Core perp to EVM, then confirm.", give_back),
    "return-too-much": ("Optional: return 1 USDC more than Core spot holds.", give_back),
    "remove-hype": ("Optional: send all Core HYPE of the contract to the owner.", remove_hype),
    "deposit": ("Deposit --amount EVM USDC into your Core spot, then confirm.", deposit),
    "confirm": ("Clear a pending transfer that has arrived.", lambda s, a: s.send("confirm")),
    "abandon": ("Clear a pending transfer that Core did not do.", lambda s, a: s.send("abandon")),
    "withdraw": ("Cleanup: send the EVM USDC of the contract to the owner.", withdraw),
    "sweep": ("Cleanup: send the Core USDC and HYPE of the contract to the owner.", c.sweep_step),
}
OPTIONS = {
    "--usdc": ("6", "USDC for the fund step"),
    "--hype": ("0.01", "HYPE for the fund step"),
    "--amount": ("2", "USDC to move, return or deposit"),
}

if __name__ == "__main__":
    sys.exit(c.main(__doc__, CONTRACT, STEPS, OPTIONS))
