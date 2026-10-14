"""The tutorials in tutorials/: contracts, scripts and pure helpers.

The contracts and the scripts run against the HyperCore simulator
(hyper_vyper.testing) on chain 998, so these tests use no network.
"""

import importlib
import json
from decimal import Decimal
from pathlib import Path

import boa
import pytest

from hyper_vyper.testing import HYPE_TOKEN
from hyper_vyper.testing import _precompiles as pc
from tests.support import (
    CORE_UNIT,
    OTHER,
    PROCESSED,
    USDC_UNIT,
    live_reply,
    send_asset_action,
)
from tutorials import _common as c
from tutorials import send_core
from tutorials.spot_order.run import order

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = sorted((ROOT / "tutorials").glob("*/*.vy"))
NAMES = ["read_state", "activate_account", "spot_perp", "evm_core", "spot_order"]
HYPE = HYPE_TOKEN[998]


# l2Book, spotMeta and precompile replies for testnet HYPE/USDC ("@1035"),
# recorded read-only from the testnet info API and RPC.
BOOK_FIXTURE = json.loads(
    (Path(__file__).parent / "reference" / "testnet_hype_usdc_book.json").read_text()
)


def recorded(name):
    return bytes.fromhex(BOOK_FIXTURE["precompiles"][name][2:])


PERP_FIXTURE = json.loads(
    (Path(__file__).parent / "reference" / "testnet_btc_perp.json").read_text()
)


def install_market(sim):
    """Answer spot_info(1035) and perp_asset_info(3) with recorded testnet replies,
    and give BTC a mark price."""
    sim.set_reply(pc.SPOT_INFO, recorded("spot_info_1035"))
    sim.set_reply(
        pc.PERP_ASSET_INFO, bytes.fromhex(PERP_FIXTURE["precompiles"]["perp_asset_info_3"][2:])
    )
    sim.set_price("mark_px", 3, 831_140)  # 83114.0 at 10**(6 - 5)


def test_every_tutorial_has_a_contract_and_a_script():
    assert sorted(p.parent.name for p in CONTRACTS) == sorted(NAMES)
    for name in NAMES:
        assert (ROOT / "tutorials" / name / "run.py").exists()
        assert (ROOT / "docs" / "tutorials" / f"{name.replace('_', '-')}.md").exists()


@pytest.mark.parametrize("path", CONTRACTS, ids=[p.name for p in CONTRACTS])
def test_contract_compiles_and_fits_a_small_block(path):
    boa.reset_env()
    data = boa.load_partial(str(path)).compiler_data
    assert len(data.bytecode_runtime) < 24_576
    _, computation = boa.env.deploy(bytecode=data.bytecode)
    # Small HyperEVM blocks have 3M gas. Leave a 30% margin.
    assert computation.get_gas_used() * 13 // 10 < 3_000_000


# --- the contracts against the simulator ---


@pytest.fixture
def sim(make_sim):
    return make_sim(998)


def deploy(name):
    return boa.load_partial(str(ROOT / "tutorials" / name / f"{name}.vy")).deploy()


def core_send(sim, sender, destination, token, amount_wei):
    """A sendAsset from an EOA on Core (spot to spot), as send_core.py does."""
    with boa.env.prank(sender):
        sim.writer.sendRawAction(send_asset_action(destination, token, amount_wei))


@pytest.fixture
def funder(sim):
    """A funded Core account, like the reader's testnet account."""
    address = boa.env.generate_address("funder")
    sim.set_spot(address, 0, 100 * CORE_UNIT)
    sim.set_hype(address, CORE_UNIT)
    sim.publish()
    return address


def test_read_state_reads_balances_and_prices(sim):
    contract = deploy("read_state")
    user = boa.env.generate_address("user")
    sim.set_spot(user, 0, 26 * CORE_UNIT, 1 * CORE_UNIT)
    sim.set_hype(user, 25_000_000)
    sim.set_perp(user, usd=5 * USDC_UNIT)
    sim.set_price("mark_px", 3, 828_990)
    sim.set_price("oracle_px", 3, 832_284)
    sim.set_reply(pc.PERP_ASSET_INFO, live_reply("perp_asset_info_btc", 999))
    sim.publish()

    view = contract.read_user(user)
    assert view.core_exists is True
    assert tuple(view.spot_usdc) == (26 * CORE_UNIT, 1 * CORE_UNIT, 0)
    assert view.spot_hype[0] == 25_000_000
    assert view.perp[0] == 5 * USDC_UNIT and view.withdrawable == 5 * USDC_UNIT
    assert contract.read_user(OTHER).core_exists is False

    perp = contract.read_perp(3)
    assert (perp.coin, perp.sz_decimals) == ("BTC", 5)
    assert c.human(perp.mark_px, 6 - perp.sz_decimals) == "82899"


def test_activation_releases_the_escrow(sim, funder):
    contract = deploy("activate_account")
    assert contract.status().core_exists is False
    boa.env.set_balance(boa.env.eoa, 10**18)

    contract.hype_to_core(value=10**15)  # 0.001 HYPE before activation
    sim.advance()
    assert sim.escrow(contract, HYPE) == 100_000
    status = contract.status()
    assert (status.core_exists, status.spot_hype) == (False, 0)  # escrow is invisible

    core_send(sim, funder, contract.address, 0, 2 * CORE_UNIT)
    sim.advance()
    status = contract.status()
    assert status.core_exists is True
    assert (status.spot_usdc, status.spot_hype) == (2 * CORE_UNIT, 100_000)
    assert sim.spot(funder, 0)[0] == 97 * CORE_UNIT  # 2 USDC sent + 1 USDC fee

    # The owner has no Core account: the send activates it and the contract pays 1 USDC.
    contract.sweep(0, 1 * CORE_UNIT)
    sim.advance()
    assert sim.spot(boa.env.eoa, 0)[0] == 1 * CORE_UNIT
    assert contract.status().spot_usdc == 0


def test_actions_of_an_unactivated_contract_revert_in_the_tutorials(sim):
    for name, call in (
        ("activate_account", lambda x: x.sweep(0, 1)),
        ("spot_perp", lambda x: x.move_usdc(1, True)),
        ("evm_core", lambda x: x.return_usdc(1, False)),
        ("spot_order", lambda x: x.place_ioc(True, 1, 1)),
    ):
        contract = deploy(name)
        with boa.reverts("Core account not activated"):
            call(contract)
        sim.activate(contract)
        sim.publish()
        with boa.env.prank(OTHER), boa.reverts("Only the owner"):
            call(contract)


def test_spot_perp_moves_with_units(sim, funder):
    contract = deploy("spot_perp")
    core_send(sim, funder, contract.address, 0, 5 * CORE_UNIT)
    sim.advance()
    contract.move_usdc(3 * USDC_UNIT, True)
    assert contract.status().spot_usdc == 5 * CORE_UNIT  # the read shows the block start
    sim.advance()
    status = contract.status()
    assert status.spot_usdc == 2 * CORE_UNIT  # 8 decimals: 3 USDC x 10**8
    assert status.perp_account_value == 3 * USDC_UNIT  # 6 decimals
    assert status.withdrawable == 3 * USDC_UNIT
    contract.move_usdc(3 * USDC_UNIT, False)
    sim.advance()
    assert contract.status().spot_usdc == 5 * CORE_UNIT
    contract.move_usdc(3 * USDC_UNIT, False)  # nothing on perp: Core rejects it silently
    sim.advance()
    assert sim.failures[-1].reason == "insufficient withdrawable"


def test_evm_core_return_from_spot_and_perp(sim, funder):
    contract = deploy("evm_core")
    core_send(sim, funder, contract.address, 0, 6 * CORE_UNIT)
    sim.advance()
    core_send(sim, funder, contract.address, HYPE, 1_000_000)  # 0.01 HYPE
    contract.move_usdc(2 * USDC_UNIT, True)
    sim.advance()

    contract.return_usdc(2 * USDC_UNIT, False)
    assert contract.has_pending() and not contract.observed()
    with boa.reverts("Not observed"):
        contract.confirm()
    with boa.reverts("Transfer pending"):
        contract.return_usdc(1 * USDC_UNIT, True)
    sim.advance()
    status = contract.status()
    assert status.evm_usdc == 2 * USDC_UNIT and status.observed
    assert status.spot_usdc == 2 * CORE_UNIT
    assert status.spot_hype == 1_000_000 - c.RETURN_GAS_HYPE
    contract.confirm()

    contract.return_usdc(2 * USDC_UNIT, True)
    sim.advance()
    assert contract.status().withdrawable == 0
    contract.confirm()
    assert sim.usdc.balanceOf(contract.address) == 4 * USDC_UNIT

    with boa.reverts("Not withdrawable"):
        contract.return_usdc(1 * USDC_UNIT, True)
    with boa.reverts("Spot balance too low"):
        contract.return_usdc(3 * USDC_UNIT, False)

    contract.withdraw_usdc(4 * USDC_UNIT)
    assert sim.usdc.balanceOf(boa.env.eoa) == 4 * USDC_UNIT


def test_evm_core_return_above_the_balance_fails_silently(sim, funder):
    contract = deploy("evm_core")
    core_send(sim, funder, contract.address, 0, 3 * CORE_UNIT)
    sim.advance()
    core_send(sim, funder, contract.address, HYPE, 1_000_000)
    sim.advance()
    with boa.reverts("Spot balance too low"):
        contract.return_usdc(4 * USDC_UNIT, False)
    contract.return_spot_unchecked(4 * USDC_UNIT)  # the EVM call succeeds
    sim.advance(3)
    assert sim.failures[-1].reason == "insufficient spot balance"
    status = contract.status()
    assert status.has_pending and not status.observed
    assert status.spot_usdc == 3 * CORE_UNIT and status.evm_usdc == 0
    assert status.spot_hype == 1_000_000  # a failed action pays no gas
    with boa.reverts("Too early"):
        contract.abandon()
    sim.advance(PROCESSED + 1)
    contract.abandon()
    assert not contract.has_pending()


def test_evm_core_return_that_core_took_cannot_be_abandoned(sim, funder):
    contract = deploy("evm_core")
    core_send(sim, funder, contract.address, 0, 6 * CORE_UNIT)
    sim.advance()
    core_send(sim, funder, contract.address, HYPE, 1_000_000)
    sim.advance()
    sim.policy.evm_credit_extra_blocks = PROCESSED + 100  # a slow EVM credit
    contract.return_usdc(2 * USDC_UNIT, False)
    sim.advance(PROCESSED + 2)
    status = contract.status()
    assert status.spot_usdc == 4 * CORE_UNIT and not status.observed
    with boa.reverts("Core took the USDC"):
        contract.abandon()
    sim.advance(100)
    assert contract.observed()
    contract.confirm()


def test_evm_core_return_from_spot_without_hype_pays_gas_in_usdc(sim, funder):
    # Without HYPE, Core takes the gas in USDC from spot, and the return arrives.
    contract = deploy("evm_core")
    core_send(sim, funder, contract.address, 0, 3 * CORE_UNIT)
    sim.advance()
    contract.return_usdc(1 * USDC_UNIT, False)
    sim.advance(3)
    status = contract.status()
    assert status.observed and status.evm_usdc == 1 * USDC_UNIT
    assert status.spot_usdc == 2 * CORE_UNIT - c.RETURN_GAS_USDC
    contract.confirm()


def test_evm_core_return_from_perp_without_hype_pays_gas_from_spot(sim, funder):
    # Without HYPE, Core takes the gas in USDC from spot, also for a perp return.
    contract = deploy("evm_core")
    core_send(sim, funder, contract.address, 0, 3 * CORE_UNIT)
    sim.advance()
    contract.move_usdc(2 * USDC_UNIT, True)
    sim.advance()
    contract.return_usdc(1 * USDC_UNIT, True)
    sim.advance(3)
    status = contract.status()
    assert status.observed and status.evm_usdc == 1 * USDC_UNIT
    assert status.spot_usdc == 1 * CORE_UNIT - c.RETURN_GAS_USDC
    assert status.withdrawable == 1 * USDC_UNIT
    contract.confirm()


def test_spot_order_sends_the_ioc_order(sim, funder):
    install_market(sim)
    contract = deploy("spot_order")
    name, tokens = contract.market()
    assert (name, list(tokens)) == ("@1035", [HYPE, 0])
    core_send(sim, funder, contract.address, 0, 15 * CORE_UNIT)
    sim.advance()
    contract.place_ioc(True, 4_815_800_000, 24_000_000)
    sim.advance(4)
    sent = [e for e in sim.events if e.name == "limit_order"][-1]
    assert sent.sender == contract.address.lower()
    assert sent.args == {
        "asset": 11035,
        "is_buy": True,
        "limit_px": 4_815_800_000,
        "sz": 24_000_000,
        "reduce_only": False,
        "tif": 3,
        "cloid": 0,
    }
    with boa.reverts("Zero price or size"):
        contract.place_ioc(False, 0, 1)
    boa.env.evm.patch.chain_id = 999
    with boa.reverts("Testnet market only"):
        contract.place_ioc(False, 1, 1)


# --- pure helpers ---


def test_unit_formatting():
    assert c.human(500_000_000, 8) == "5"
    assert c.human(-2_000, 8) == "-0.00002"
    assert c.amount(300_000_000, 8, "USDC") == "300000000 (3 USDC, 8 decimals)"
    assert c.amount(10**15, 18, "HYPE") == "1000000000000000 (0.001 HYPE, 18 decimals)"
    assert c.parse_amount("2", 6) == 2 * USDC_UNIT
    assert c.parse_amount("0.00002", 8) == 2_000
    for bad in ("0", "-1", "0.0000001", "x"):
        with pytest.raises(c.StepError):
            c.parse_amount(bad, 6)
    assert c.from_info("26.66706734", 8) == 2_666_706_734


def test_orders_from_the_recorded_book():
    book = BOOK_FIXTURE["l2Book"]  # best ask 47.681, best bid 47.68
    buy = order(book, True, Decimal(12), 2, 8, Decimal("0.01"))
    assert buy["limit"] == Decimal("48.158")  # 47.681 x 1.01 = 48.15781, rounded up
    assert buy["sz"] == Decimal("0.24")  # 12 / 48.158 = 0.249..., rounded down
    assert (buy["limit_e8"], buy["sz_e8"]) == (4_815_800_000, 24_000_000)
    sell = order(book, False, Decimal(0), 2, 8, Decimal("0.01"), Decimal("0.2499"))
    assert (sell["sz"], sell["limit"], sell["value"]) == (
        Decimal("0.24"),
        Decimal("47.203"),
        Decimal("11.32872"),
    )
    btc = order(PERP_FIXTURE["l2Book"], True, Decimal(11), 5, 6, Decimal("0.01"))
    assert btc["limit"] == btc["limit"].quantize(Decimal(1))  # 6 - 5 = 1 decimal at most


def test_send_core_checks():
    assert send_core.parse_amount("2") == Decimal(2)
    with pytest.raises(send_core.SendError):
        send_core.parse_amount("0.000000001")
    # tokenId values from the testnet spotMeta
    meta = {
        "tokens": [
            {"index": 0, "name": "USDC", "tokenId": "0xeb62eee3685fc4c43992febcd9e75443"},
            {"index": 1105, "name": "HYPE", "tokenId": "0x7317beb7cceed72ef0b346074cc8e7ab"},
        ]
    }
    assert send_core.token_wire_name(meta, "USDC") == "USDC:0xeb62eee3685fc4c43992febcd9e75443"
    assert send_core.token_wire_name(meta, "HYPE") == "HYPE:0x7317beb7cceed72ef0b346074cc8e7ab"
    funder = {"balances": [{"token": 0, "total": "10", "hold": "0"}]}
    assert send_core.check("USDC", Decimal(2), "missing", funder) == []
    assert send_core.check("USDC", Decimal(2), "user", None) == []
    assert send_core.check("USDC", Decimal("0.5"), "missing", None)
    assert send_core.check("HYPE", Decimal(1), "missing", None)
    assert send_core.check("USDC", Decimal(10), "missing", funder)  # 10 + 1 USDC fee > 10


# --- the scripts against the simulator ---


class SimInfo:
    """The info API reads of the scripts (the SDK's Info methods), from the simulator."""

    def __init__(self, sim):
        self.sim = sim

    def user_role(self, user):
        return {"role": "user" if self.sim.account_state(user) == "activated" else "missing"}

    def spot_user_state(self, user):
        balances = []
        for token, name in ((0, "USDC"), (HYPE, "HYPE")):
            total, hold = self.sim.spot(user, token)
            if total:
                balances.append(
                    {
                        "coin": name,
                        "token": token,
                        "total": c.human(total, 8),
                        "hold": c.human(hold, 8),
                    }
                )
        escrow = self.sim.escrow(user, HYPE)
        state = {"balances": balances}
        if escrow:
            state["evmEscrows"] = [{"coin": "HYPE", "token": HYPE, "total": c.human(escrow, 8)}]
        return state

    def user_state(self, user):
        perp = self.sim.perp(user)
        return {
            "marginSummary": {"accountValue": c.human(perp.account_value, 6)},
            "withdrawable": c.human(perp.withdrawable, 6),
        }

    def meta_and_asset_ctxs(self):
        universe = [{"name": f"P{i}", "szDecimals": 2} for i in range(3)]
        universe.append({"name": "BTC", "szDecimals": 5})
        ctxs = [{"markPx": "1", "oraclePx": "1"}] * 3 + [{"markPx": "82899", "oraclePx": "83228.4"}]
        return [{"universe": universe}, ctxs]

    def spot_meta(self):
        return BOOK_FIXTURE["spotMeta"]

    def l2_snapshot(self, coin):
        if coin == "BTC":
            return PERP_FIXTURE["l2Book"]
        assert coin == "@1035"
        return BOOK_FIXTURE["l2Book"]


@pytest.fixture
def script(sim, funder, tmp_path):
    """Run one tutorial step through its run.py logic. Returns (sessions, run_step)."""
    owner = boa.env.generate_address("owner")
    boa.env.set_balance(owner, 10**18)
    sim.activate(owner)  # the reader's own Core account exists
    sim.publish()
    lines = []

    def fund(destination, token, amount):
        index = 0 if token == "USDC" else HYPE
        core_send(sim, funder, destination, index, c.parse_amount(amount, 8))

    def run_step(name, step, execute=True, **options):
        module = importlib.import_module(f"tutorials.{name}.run")
        session = c.Session(
            contract_path=module.CONTRACT,
            execute=execute,
            signer=owner if execute else None,
            state_path=tmp_path / f"{name}.json",
            info=SimInfo(sim),
            funder=fund,
            log=lines.append,
            max_blocks=8,
            wait=sim.advance,
        )
        session.check_chain()
        argv = [step]
        for key, value in options.items():
            flag = "--" + key.replace("_", "-")
            argv += [flag] if value is True else [flag, str(value)]
        args = c.parse(module.__doc__, module.STEPS, module.OPTIONS, argv)
        module.STEPS[step][1](session, args)
        return session

    run_step.lines = lines
    run_step.owner = owner
    return run_step


def test_plan_only_sends_nothing(sim, script):
    session = script("spot_perp", "deploy", execute=False)
    assert not session.state_path.exists()
    assert "plan only: add --execute to send. Nothing was sent." in script.lines
    script("spot_perp", "deploy")
    script("spot_perp", "fund", usdc="5")
    journal, spot = sim.writer.count(), sim.spot(script("spot_perp", "status").contract.address)
    script("spot_perp", "to-perp", execute=False, amount="3")
    sim.advance()
    contract = script("spot_perp", "status").contract.address
    assert (sim.writer.count(), sim.spot(contract)) == (journal, spot)
    assert any(line.startswith("plan: move_usdc(3000000, True)") for line in script.lines)


def test_script_refuses_another_chain(sim, script):
    boa.env.evm.patch.chain_id = 999
    with pytest.raises(c.StepError, match="not 998"):
        script("read_state", "deploy", execute=False)


def test_read_state_script_matches_the_info_api(sim, script):
    user = boa.env.generate_address("user")
    sim.set_spot(user, 0, 26 * CORE_UNIT)
    sim.set_perp(user, usd=1 * USDC_UNIT)
    sim.set_price("mark_px", 3, 828_990)
    sim.set_price("oracle_px", 3, 832_284)
    sim.set_reply(pc.PERP_ASSET_INFO, live_reply("perp_asset_info_btc", 999))
    sim.publish()
    script("read_state", "deploy")
    script("read_state", "read", user=user)
    assert "All values match." in script.lines


def test_activate_account_script(sim, script):
    script("activate_account", "deploy")
    script("activate_account", "escrow", hype="0.001")
    contract = script("activate_account", "status", execute=False).contract.address
    assert sim.account_state(contract) == "escrow"
    script("activate_account", "activate", usdc="2")
    assert sim.account_state(contract) == "activated"
    assert sim.spot(contract, HYPE)[0] == 100_000  # the escrow is released to spot
    script("activate_account", "sweep")
    assert sim.spot(contract, 0)[0] == 0 and sim.spot(contract, HYPE)[0] == 0
    assert sim.spot(script.owner, 0)[0] == 2 * CORE_UNIT


def test_spot_perp_script(sim, script):
    script("spot_perp", "deploy")
    script("spot_perp", "fund", usdc="5")
    contract = script("spot_perp", "status", execute=False).contract.address
    script("spot_perp", "to-perp", amount="3")
    assert sim.spot(contract, 0)[0] == 2 * CORE_UNIT
    assert sim.perp(contract).account_value == 3 * USDC_UNIT
    script("spot_perp", "to-spot", amount="3")
    with pytest.raises(c.StepError, match="withdrawable"):
        script("spot_perp", "to-spot", amount="3")


def test_evm_core_script(sim, script):
    # The contract tests cover perp returns, silent failures and gas without HYPE.
    script("evm_core", "deploy")
    script("evm_core", "fund", usdc="6", hype="0.01")
    contract = script("evm_core", "status", execute=False).contract.address
    script("evm_core", "return-spot", amount="2")
    assert sim.usdc.balanceOf(contract) == 2 * USDC_UNIT

    # Deposit 1 USDC back to Core, for the owner.
    owner_before = sim.spot(script.owner, 0)[0]
    script("evm_core", "deposit", amount="1")
    assert sim.spot(script.owner, 0)[0] == owner_before + 1 * CORE_UNIT  # no fee

    # A deposit that Core does not credit, as on testnet without a mainnet account.
    sim.fail_next("deposit", "not credited")
    script("evm_core", "deposit", amount="1")
    with pytest.raises(c.StepError, match="Too early"):
        script("evm_core", "abandon")
    sim.advance(PROCESSED + 1)
    script("evm_core", "abandon")

    script("evm_core", "withdraw")
    script("evm_core", "sweep")
    assert sim.usdc.balanceOf(contract) == 0
    assert sim.spot(contract, 0)[0] == sim.spot(contract, HYPE)[0] == 0


def test_spot_order_script(sim, script):
    install_market(sim)
    script("spot_order", "deploy")
    with pytest.raises(c.StepError, match="not activated"):
        script("spot_order", "buy", usdc="12")
    script("spot_order", "fund")
    script("spot_order", "buy", usdc="12")
    assert any("encoded: limit_px 4815800000, sz 24000000" in line for line in script.lines)
    # The simulator has no matching engine, so the order never fills here.
    assert "No fill: the order did not match within the limit." in script.lines
    with pytest.raises(c.StepError, match="Core would reject"):
        script("spot_order", "buy", usdc="9")

    # Perp: margin, a long, a reduce-only close, and the margin back to spot.
    with pytest.raises(c.StepError, match="no margin"):
        script("spot_order", "perp-open", usd="11")
    script("spot_order", "to-perp", amount="3")
    script("spot_order", "perp-open", usd="11")
    assert any("encoded: limit_px 8394700000000, sz 13000" in line for line in script.lines)
    assert "No fill: the order did not match within the limit." in script.lines
    with pytest.raises(c.StepError, match="no long BTC position"):
        script("spot_order", "perp-close")
    contract = script("spot_order", "status", execute=False).contract.address
    sim.set_position(contract, 3, szi=13, entry_ntl=10_805_000)  # a filled long, for the test
    sim.publish()
    with pytest.raises(c.StepError, match="Close the BTC position first"):
        script("spot_order", "to-spot")
    script("spot_order", "perp-close")
    sent = [e for e in sim.events if e.name == "limit_order"][-1]
    assert sent.args["asset"] == 3 and sent.args["reduce_only"] and not sent.args["is_buy"]
    assert sent.args["sz"] == 13000
    sim.set_position(contract, 3)  # closed
    sim.publish()
    script("spot_order", "to-spot")
    assert sim.perp(contract).withdrawable == 0
