"""Shared code of the tutorial scripts (tutorials/*/run.py).

Titanoboa drives the contracts. With --execute it sends real transactions to
HyperEVM testnet, and it runs each call locally first, so a call that would revert
is never sent. Without --execute the steps run only on a local copy of the chain.
In both modes, hyper_vyper.testing.forward_precompiles answers the HyperCore read
precompiles from the node, because the local copy has none.

The scripts refuse any chain but 998. The EVM key comes only from
HYPER_VYPER_TESTNET_KEY and is never printed. Core transfers go through
tutorials/send_core.py, which reads HYPER_VYPER_CORE_FUNDER_KEY.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shlex
import sys
import time
import warnings
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import boa
from boa.contracts.base_evm_contract import BoaError
from boa.interpret import set_search_paths
from boa.network import NetworkEnv

from hyper_vyper.testing import HYPE_TOKEN as HYPE_TOKENS
from hyper_vyper.testing import forward_precompiles, measured
from hyper_vyper.testing.live import TESTNET_RPC, RetryingRPC

ROOT = Path(__file__).resolve().parents[1]
KEY_ENV = "HYPER_VYPER_TESTNET_KEY"
FUNDER_ENV = "HYPER_VYPER_CORE_FUNDER_KEY"
TESTNET_CHAIN_ID = 998
USDC_TOKEN = 0
HYPE_TOKEN = HYPE_TOKENS[TESTNET_CHAIN_ID]
RETURN_GAS_HYPE = measured.RETURN_GAS_HYPE_WEI
RETURN_GAS_USDC = measured.RETURN_GAS_USDC_WEI

# Network mode warns when a local view result differs from the node's. The testing
# quick start (docs/testing/quick-start.md) explains why this is expected.
warnings.filterwarnings("ignore", message="local fork did not match node")
warnings.filterwarnings("ignore", message="debug_traceTransaction not available")
warnings.filterwarnings("ignore", message="Couldn't get a trace for")


class StepError(Exception):
    """A step cannot run. The step that raised it sent nothing more."""


def human(value: int, decimals: int) -> str:
    """human(500_000_000, 8) -> "5"."""
    return format(Decimal(value).scaleb(-decimals).normalize(), "f")


def amount(value: int, decimals: int, symbol: str) -> str:
    """amount(500_000_000, 8, "USDC") -> "500000000 (5 USDC, 8 decimals)"."""
    return f"{value} ({human(value, decimals)} {symbol}, {decimals} decimals)"


def parse_amount(text: str, decimals: int) -> int:
    """A positive human amount as an integer with `decimals` decimals."""
    try:
        value = Decimal(text).scaleb(decimals)
    except ArithmeticError:
        raise StepError(f"{text!r} is not a number") from None
    if value <= 0 or value != value.to_integral_value():
        raise StepError(f"{text} is not a positive amount with at most {decimals} decimals")
    return int(value)


def from_info(text: str, decimals: int) -> int:
    """An info API decimal string as an integer: from_info("5.0", 8) -> 500000000."""
    return int(Decimal(text).scaleb(decimals).to_integral_value(rounding=ROUND_DOWN))


def info_balance(state: dict, token: int, key: str = "balances") -> int:
    """The total of one token in a spotClearinghouseState, in Core wei. Use
    key="evmEscrows" for the escrow, which no precompile shows."""
    for b in state.get(key) or []:
        if b["token"] == token:
            return from_info(b["total"], 8)
    return 0


def connect(rpc_url: str, execute: bool) -> str | None:
    """Set the Titanoboa environment. Returns the address that signs, or None."""
    rpc = RetryingRPC(rpc_url)
    forward_precompiles(rpc)
    if not execute:
        env = boa.Env()
        env.fork_rpc(rpc, block_identifier="latest")
        boa.set_env(env)
        return None
    if not os.environ.get(KEY_ENV):
        raise StepError(f"--execute needs the testnet key in {KEY_ENV}")
    from eth_account import Account

    account = Account.from_key(os.environ[KEY_ENV].strip())
    env = NetworkEnv(rpc)
    env.suppress_debug_tt()
    boa.set_env(env)
    env.add_account(account, force_eoa=True)
    return account.address


def run_send_core(destination: str, token: str, value: str) -> None:
    from tutorials import send_core

    args = ["--to", destination, "--token", token, "--amount", value, "--execute"]
    if send_core.main(args) != 0:
        raise StepError("tutorials/send_core.py failed")


def quietly(call):
    """Run a Titanoboa call that may send a transaction. Returns (result, tx hash).
    Titanoboa prints each hash. Keep it, and print nothing else."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = call()
    hashes = re.findall(r"tx broadcasted: (0x[0-9a-f]+)", out.getvalue())
    return result, hashes[-1] if hashes else None


class Session:
    """One tutorial contract: deploy it, read it, send owner-only calls, wait for Core.

    Without `execute`, each transaction runs and is rolled back. `wait` waits for
    the next EVM block (the tests advance the HyperCore simulator instead)."""

    def __init__(
        self,
        *,
        contract_path,
        state_path,
        execute=False,
        signer=None,
        info=None,
        funder=None,
        log=print,
        max_blocks=20,
        wait=lambda: time.sleep(1),
    ):
        self.execute, self.signer, self.info, self.funder = execute, signer, info, funder
        self.state_path, self.log, self.max_blocks, self.wait = state_path, log, max_blocks, wait
        set_search_paths([str(ROOT / "src")])
        self.deployer = boa.load_partial(str(contract_path))
        self.contract_name = Path(contract_path).name
        self._contract = None

    def check_chain(self) -> None:
        if boa.env.evm.patch.chain_id != TESTNET_CHAIN_ID:
            raise StepError(f"The chain ID is {boa.env.evm.patch.chain_id}, not 998. Refusing.")
        self.log("chain 998 (HyperEVM testnet)")

    @property
    def contract(self):
        if self._contract is None:
            if not self.state_path.exists():
                raise StepError(f"No contract in {self.state_path}. Run the deploy step first.")
            self._contract = self.deployer.at(json.loads(self.state_path.read_text())["contract"])
        return self._contract

    def read(self, fn: str = "status", *args) -> dict:
        """A view that returns one struct, as a dict."""
        return getattr(self.contract, fn)(*args)._asdict()

    def deploy(self) -> None:
        if self.state_path.exists():
            raise StepError(f"{self.state_path} names a contract. Delete it to deploy again.")
        self.log(f"plan: deploy {self.contract_name}")
        if not self.execute:
            with boa.env.anchor():
                self.deployer.deploy()
            self.log("plan only: add --execute to send. Nothing was sent.")
            return
        with boa.env.prank(self.signer):
            self._contract, tx = quietly(self.deployer.deploy)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"contract": self._contract.address}) + "\n")
        self.log(f"sent deploy: {tx} in block {boa.env.evm.patch.block_number}")
        self.log(f"contract {self._contract.address}")

    def send(self, fn: str, *args, value: int = 0) -> bool:
        """Send an owner-only call. Returns False in plan-only mode. Titanoboa runs
        the call locally first, so a call that would revert is never sent."""
        owner = self.contract.OWNER()
        if self.signer and self.signer.lower() != owner.lower():
            raise StepError(f"The key is for {self.signer}, the owner is {owner}")
        shown = ", ".join(str(a) for a in args)
        self.log(f"plan: {fn}({shown}) value {value}")
        try:
            with boa.env.prank(owner):
                if not self.execute:
                    with boa.env.anchor():
                        getattr(self.contract, fn)(*args, value=value)
                    self.log("plan only: add --execute to send. Nothing was sent.")
                    return False
                _, tx = quietly(lambda: getattr(self.contract, fn)(*args, value=value))
        except BoaError as exc:
            reason = exc.stack_trace.last_frame.pretty_vm_reason
            raise StepError(f"{fn}({shown}) would revert: {reason}") from None
        self.log(f"sent {fn}: {tx} in block {boa.env.evm.patch.block_number}")
        return True

    def wait_for(self, done, describe) -> tuple[dict, bool]:
        """Read the status once per new EVM block until done(status), or give up after
        max_blocks blocks. Returns (last status, True if done)."""
        s = self.read()
        start = last = s["evm_block"]
        self.log(f"  block {last}: {describe(s)}")
        while not done(s) and last < start + self.max_blocks:
            self.wait()
            s = self.read()
            if s["evm_block"] > last:
                last = s["evm_block"]
                self.log(f"  block {last} (+{last - start}): {describe(s)}")
        return s, done(s)

    def fund(self, token: str, value: str) -> bool:
        """Send `value` of `token` on Core from your Core account. Returns True if sent."""
        destination = self.contract.address
        command = f"uv run --script tutorials/send_core.py --to {destination} --token {token}"
        self.log(f"Core transfer: {value} {token} from your Core account to {destination}")
        self.log(f"  {FUNDER_ENV}=0x... {command} --amount {shlex.quote(value)} --execute")
        if not self.execute or self.funder is None:
            self.log("Not sent. Run the command above yourself, or set the key and --execute.")
            return False
        self.funder(destination, token, value)
        return True


def fund(s: Session, usdc: str, hype: str | None = None) -> None:
    """USDC first, because it activates the account. HYPE sent to an account that is
    not activated goes into an escrow."""
    before = s.read()
    want = before["spot_usdc"] + parse_amount(usdc, 8)
    if not s.fund("USDC", usdc):
        return
    _, ok = s.wait_for(
        lambda x: x["core_exists"] and x["spot_usdc"] >= want,
        lambda x: f"exists {x['core_exists']}, spot USDC {amount(x['spot_usdc'], 8, 'USDC')}",
    )
    if not ok:
        raise StepError("The USDC did not arrive. Check the send_core.py output.")
    if hype:
        want = s.read()["spot_hype"] + parse_amount(hype, 8)
        s.fund("HYPE", hype)
        s.wait_for(
            lambda x: x["spot_hype"] >= want,
            lambda x: f"spot HYPE {amount(x['spot_hype'], 8, 'HYPE')}",
        )


def sweep(s: Session, fields=("spot_usdc", "spot_hype")) -> None:
    """Send all Core spot USDC and HYPE (or only the given fields) of the contract
    to the owner on Core."""
    status = s.read()
    tokens = {"spot_usdc": USDC_TOKEN, "spot_hype": HYPE_TOKEN}
    for field in fields:
        value = status[field]
        if value and s.send("sweep", tokens[field], value):
            s.wait_for(lambda x, f=field: x[f] == 0, lambda x, f=field: f"{f} {human(x[f], 8)}")


def move_withdrawable(s: Session, ntl: int, to_perp: bool) -> None:
    """Send move_usdc(ntl, to_perp) and wait until perp withdrawable changes by ntl."""
    before = s.read()["withdrawable"]
    if s.send("move_usdc", ntl, to_perp):
        s.wait_for(
            lambda x: x["withdrawable"] == before + (ntl if to_perp else -ntl),
            lambda x: f"withdrawable {human(x['withdrawable'], 6)}",
        )


def deploy_step(s: Session, args) -> None:
    s.deploy()


def sweep_step(s: Session, args) -> None:
    sweep(s)


def parse(doc: str, steps: dict, options: dict, argv=None) -> argparse.Namespace:
    """The command line of a tutorial script. steps: {name: (help, function)}.
    options: {--flag: (default, help)}."""
    lines = [doc, "steps:"] + [f"  {name:<16} {text}" for name, (text, _) in steps.items()]
    p = argparse.ArgumentParser(
        description="\n".join(lines), formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("step", choices=list(steps))
    p.add_argument("--execute", action="store_true", help="sign and send (testnet only)")
    p.add_argument("--rpc", default=TESTNET_RPC)
    p.add_argument("--api", default="https://api.hyperliquid-testnet.xyz")
    p.add_argument("--state", type=Path, help="state file (default tutorials/.state/)")
    for flag, (default, text) in options.items():
        if default is False:
            p.add_argument(flag, action="store_true", help=text)
        else:
            p.add_argument(flag, default=default, help=text)
    return p.parse_args(argv)


def main(doc: str, contract_path: Path, steps: dict, options: dict, argv=None) -> int:
    """Parse the command line, connect, check the chain and run one step."""
    args = parse(doc, steps, options, argv)
    try:
        from hyperliquid.info import Info

        signer = connect(args.rpc, args.execute)
        name = Path(contract_path).stem
        session = Session(
            contract_path=contract_path,
            state_path=args.state or ROOT / "tutorials" / ".state" / f"{name}.json",
            execute=args.execute,
            signer=signer,
            info=Info(args.api, skip_ws=True),
            funder=run_send_core if os.environ.get(FUNDER_ENV) else None,
        )
        session.check_chain()
        steps[args.step][1](session, args)
    except StepError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
