# /// script
# requires-python = ">=3.11"
# dependencies = ["hyperliquid-python-sdk==0.24.0"]
# ///
"""Send USDC or HYPE on HyperCore TESTNET from your funded Core account (sendAsset).

The tutorials use this script to activate and fund tutorial contracts. It uses
the official hyperliquid-python-sdk (Exchange.send_asset), spot to spot.

Safety:
- It talks only to the testnet API (https://api.hyperliquid-testnet.xyz).
- Without --execute it only reads (info API) and prints the plan.
- With --execute it reads the key from HYPER_VYPER_CORE_FUNDER_KEY. The key is
  never printed.

Rules that it checks:
- A send of 1 USDC or more to an address without a Core account activates it.
  The SENDER pays the 1 USDC fee, on top of the amount.
- A smaller send, or a HYPE send, to such an address is refused here.
- sendAsset works in unifiedAccount mode. spotSend does not.

  uv run --script tutorials/send_core.py --to 0xCONTRACT --token USDC --amount 2
  HYPER_VYPER_CORE_FUNDER_KEY=0x... uv run --script tutorials/send_core.py \\
      --to 0xCONTRACT --token USDC --amount 2 --execute
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, InvalidOperation

API_URL = "https://api.hyperliquid-testnet.xyz"
FUNDER_ENV = "HYPER_VYPER_CORE_FUNDER_KEY"
TOKENS = {"USDC": 0, "HYPE": 1105}  # testnet Core token indices
ACTIVATION_FEE_USDC = Decimal(1)


class SendError(Exception):
    pass


def token_wire_name(spot_meta: dict, token: str) -> str:
    """The sendAsset token string, "NAME:tokenId", from a spotMeta reply."""
    index = TOKENS[token]
    for t in spot_meta["tokens"]:
        if t["index"] == index:
            if t["name"] != token:
                raise SendError(f"token {index} is {t['name']}, not {token}")
            return f"{t['name']}:{t['tokenId']}"
    raise SendError(f"token {token} ({index}) not in spotMeta")


def parse_amount(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise SendError(f"{text!r} is not a number") from None
    if value <= 0 or value != value.quantize(Decimal("1e-8")):
        raise SendError(f"{text} must be positive with at most 8 decimals")
    return value


def spot_available(spot_state: dict, token: str) -> Decimal:
    for b in spot_state.get("balances", []):
        if b["token"] == TOKENS[token]:
            return Decimal(b["total"]) - Decimal(b["hold"])
    return Decimal(0)


def check(token: str, amount: Decimal, destination_role: str, funder_spot: dict | None) -> list:
    """Problems that block the send. funder_spot is None when the funder is unknown."""
    problems = []
    activates = destination_role == "missing"
    if activates and token != "USDC":
        problems.append(
            "the destination has no Core account: send 1 USDC or more first to activate it"
        )
    if activates and token == "USDC" and amount < ACTIVATION_FEE_USDC:
        problems.append("the first send to a new account must be at least 1 USDC")
    if funder_spot is not None:
        need = amount + (ACTIVATION_FEE_USDC if activates and token == "USDC" else 0)
        have = spot_available(funder_spot, token)
        if have < need:
            problems.append(f"your Core spot {token} is {have}, the send needs {need}")
    return problems


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--to", required=True, help="destination address")
    p.add_argument("--token", required=True, choices=list(TOKENS))
    p.add_argument("--amount", required=True, help="human amount, for example 2 or 0.01")
    p.add_argument("--execute", action="store_true", help="sign and send (testnet only)")
    args = p.parse_args(argv)

    try:
        amount = parse_amount(args.amount)
        key = os.environ.get(FUNDER_ENV)
        if args.execute and not key:
            raise SendError(f"--execute needs the funder key in {FUNDER_ENV}")
        funder = None
        if key:
            from eth_account import Account

            funder = Account.from_key(key.strip())
        from hyperliquid.info import Info

        info = Info(API_URL, skip_ws=True)
        role = info.user_role(args.to)["role"]
        print(f"destination {args.to}: Core role {role!r}")
        funder_spot = None
        if funder is not None:
            funder_spot = info.spot_user_state(funder.address)
            mode = info.query_user_abstraction_state(funder.address)
            print(f"funder {funder.address}: mode {mode!r}")
            print(f"  spot USDC {spot_available(funder_spot, 'USDC')} available")
            print(f"  spot HYPE {spot_available(funder_spot, 'HYPE')} available")
        if role == "missing" and args.token == "USDC":
            print("This send activates the destination. You pay 1 USDC more as the fee.")
        token = token_wire_name(info.spot_meta(), args.token)
        print(f"plan: send_asset({args.to}, 'spot', 'spot', '{token}', {float(amount)})")
        problems = check(args.token, amount, role, funder_spot)
        for problem in problems:
            print(f"  [FAIL] {problem}")
        if problems:
            raise SendError("prerequisites not met; nothing sent")
        if not args.execute:
            print("plan only: add --execute to send. Nothing was sent.")
            return 0

        from hyperliquid.exchange import Exchange

        exchange = Exchange(funder, API_URL)
        result = exchange.send_asset(args.to, "spot", "spot", token, float(amount))
        print(f"result: {result}")
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise SendError("Core refused the send")
    except SendError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
