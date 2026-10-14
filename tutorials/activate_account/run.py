"""Tutorial 2: activate the HyperCore account of a new contract.

uv run --locked tutorials/activate_account/run.py deploy --execute
uv run --locked tutorials/activate_account/run.py status
uv run --locked tutorials/activate_account/run.py activate --execute
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tutorials import _common as c  # noqa: E402

CONTRACT = Path(__file__).with_name("activate_account.vy")


def escrow(s: c.Session) -> int:
    return c.info_balance(s.info.spot_user_state(s.contract.address), c.HYPE_TOKEN, "evmEscrows")


def status(s: c.Session, args=None) -> dict:
    """Print what the precompiles show and what the info API shows."""
    x = s.read()
    spot = s.info.spot_user_state(s.contract.address)
    s.log(f"contract {s.contract.address} at EVM block {x['evm_block']}")
    s.log(f"  precompile core_user_exists: {x['core_exists']}")
    s.log(f"  precompile spot USDC: {c.amount(x['spot_usdc'], 8, 'USDC')}")
    s.log(f"  precompile spot HYPE: {c.amount(x['spot_hype'], 8, 'HYPE')}")
    s.log(f"  info API userRole: {s.info.user_role(s.contract.address)['role']}")
    s.log(
        f"  info API spot USDC {c.human(c.info_balance(spot, c.USDC_TOKEN), 8)}, "
        f"spot HYPE {c.human(c.info_balance(spot, c.HYPE_TOKEN), 8)}"
    )
    s.log(f"  info API escrow (evmEscrows) HYPE: {c.human(escrow(s), 8)}")
    return x


def send_to_escrow(s: c.Session, args) -> None:
    if s.read()["core_exists"]:
        raise c.StepError("The account is already activated. The HYPE would go to spot.")
    value = c.parse_amount(args.hype, 18)
    s.log(f"send {c.amount(value, 18, 'HYPE')} from EVM to the Core account of the contract")
    if not s.send("hype_to_core", value=value):
        return
    _, ok = s.wait_for(
        lambda x: escrow(s) > 0,
        lambda x: f"exists {x['core_exists']}, precompile spot HYPE {c.human(x['spot_hype'], 8)}",
    )
    s.log(f"info API escrow HYPE: {c.human(escrow(s), 8)}")
    if ok:
        s.log("The HYPE is in escrow. The precompiles do not show it.")


def activate(s: c.Session, args) -> None:
    if status(s)["core_exists"]:
        s.log("The account is already activated. Nothing to do.")
        return
    s.log("Your Core account pays the 1 USDC activation fee on top of the amount.")
    if s.fund("USDC", args.usdc):
        wait(s, args)


def wait(s: c.Session, args) -> None:
    _, ok = s.wait_for(lambda x: x["core_exists"], lambda x: f"core_user_exists {x['core_exists']}")
    s.log("account is activated" if ok else "account is NOT activated yet")
    if ok:
        status(s)


STEPS = {
    "deploy": ("Deploy the contract. Its Core account is not activated.", c.deploy_step),
    "status": ("Show the account: precompiles and info API, with the escrow.", status),
    "escrow": ("Optional: send --hype HYPE from EVM to Core before activation.", send_to_escrow),
    "activate": ("Send --usdc USDC on Core to the contract, then wait.", activate),
    "wait": ("Wait until core_user_exists is true (after you ran send_core.py).", wait),
    "sweep": ("Cleanup: send the Core USDC and HYPE of the contract to the owner.", c.sweep_step),
}
OPTIONS = {
    "--hype": ("0.001", "HYPE for the escrow step"),
    "--usdc": ("2", "USDC for the activate step"),
}

if __name__ == "__main__":
    sys.exit(c.main(__doc__, CONTRACT, STEPS, OPTIONS))
