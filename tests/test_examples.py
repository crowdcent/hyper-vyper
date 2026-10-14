"""Compile every example, and run the examples against the HyperCore simulator."""

from pathlib import Path

import boa
import pytest

from tests.support import CORE_UNIT, OTHER, PROCESSED, USDC_UNIT

EXAMPLES_DIR = Path(__file__).parents[1] / "examples"
EXAMPLES = sorted(EXAMPLES_DIR.glob("*.vy"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[path.name for path in EXAMPLES])
def test_example_compiles(path):
    assert boa.load_partial(str(path)).compiler_data.bytecode


@pytest.fixture
def sim(make_sim):
    return make_sim(999)


@pytest.fixture
def example(sim):
    contract = boa.load_partial(str(EXAMPLES_DIR / "usdc_bridge.vy")).deploy()
    sim.usdc.mint(contract.address, 500 * USDC_UNIT)
    return contract


def activate(sim, contract):
    """An activated Core account with a little HYPE for return gas."""
    sim.activate(contract)
    sim.set_hype(contract, 10**8)
    sim.publish()


def test_deposit_is_pending_until_core_shows_it(sim, example):
    activate(sim, example)
    example.deposit(100 * USDC_UNIT)
    assert example.has_pending()
    assert not example.observed()
    with boa.reverts("Same block"):
        example.confirm()

    sim.advance()
    assert sim.spot(example)[0] == 100 * CORE_UNIT
    assert example.observed()
    example.confirm()
    assert not example.has_pending()


def test_withdraw_is_pending_until_evm_receives_it(sim, example):
    activate(sim, example)
    example.deposit(100 * USDC_UNIT)
    sim.advance()
    example.confirm()

    example.withdraw(40 * USDC_UNIT)
    assert not example.observed()
    sim.advance()
    assert sim.usdc.balanceOf(example.address) == 440 * USDC_UNIT
    assert example.observed()
    example.confirm()


def test_guards(sim, example):
    with boa.reverts("Core account not activated"):
        example.deposit(1 * USDC_UNIT)
    activate(sim, example)
    with boa.env.prank(OTHER), boa.reverts("Only the owner"):
        example.deposit(1 * USDC_UNIT)
    with boa.reverts("Zero amount"):
        example.deposit(0)
    with boa.reverts("Spot balance too low"):
        example.withdraw(1 * USDC_UNIT)
    example.deposit(1 * USDC_UNIT)
    with boa.reverts("Transfer pending"):
        example.deposit(1 * USDC_UNIT)
    with boa.reverts("Too early"):
        example.abandon()


def test_failed_return_can_be_abandoned_after_core_processed_it(sim, example):
    activate(sim, example)
    example.deposit(100 * USDC_UNIT)
    sim.advance()
    example.confirm()
    sim.fail_next("send_asset", "rejected by Core")  # any silent rejection
    example.withdraw(40 * USDC_UNIT)
    sim.advance(3)
    assert [event.name for event in sim.failures] == ["send_asset"]
    assert not example.observed()
    with boa.reverts("Not observed"):
        example.confirm()
    with boa.reverts("Too early"):
        example.abandon()
    sim.advance(PROCESSED + 1)
    example.abandon()
    assert not example.has_pending()


def test_a_return_that_core_took_cannot_be_abandoned(sim, example):
    """A slow EVM credit must not let the owner abandon the return, retry it, and
    then count the first arrival as the retry."""
    activate(sim, example)
    example.deposit(100 * USDC_UNIT)
    sim.advance()
    example.confirm()
    sim.policy.evm_credit_extra_blocks = PROCESSED + 50
    example.withdraw(40 * USDC_UNIT)
    sim.advance(PROCESSED + 2)
    assert sim.spot(example)[0] == 60 * CORE_UNIT  # Core took the USDC
    assert not example.observed()
    with boa.reverts("Core took the USDC"):
        example.abandon()
    sim.advance(50)
    assert example.observed()
    example.confirm()


def test_perp_profit_cannot_confirm_a_failed_deposit(sim, example):
    activate(sim, example)
    sim.set_perp(example, usd=1_000 * USDC_UNIT)
    sim.publish()
    sim.fail_next("deposit", "not credited")
    example.deposit(100 * USDC_UNIT)
    sim.advance()
    assert [event.name for event in sim.failures] == ["deposit"]
    sim.add_pnl(example, unrealized=200 * USDC_UNIT)  # unrelated profit on perp
    sim.advance()
    assert sim.perp(example).pnl == 200 * USDC_UNIT
    assert sim.spot(example)[0] == 0
    assert not example.observed()
    with boa.reverts("Not observed"):
        example.confirm()
