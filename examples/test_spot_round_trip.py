"""Test examples/spot_round_trip.vy against the HyperCore simulator (CoreSim)."""

from pathlib import Path

import boa
import pytest

from hyper_vyper.testing import CoreSim

CONTRACT = Path(__file__).with_name("spot_round_trip.vy")
USDC = 10**6  # EVM USDC and perp USD: 6 decimals
CORE_USDC = 10**8  # Core spot USDC: 8 decimals
HYPE = 10**8  # Core HYPE: 8 decimals


@pytest.fixture
def sim():
    boa.reset_env()
    sim = CoreSim.install(chain_id=999)  # mainnet addresses and token indices
    yield sim
    sim.close()


def test_spot_round_trip(sim):
    contract = boa.load_partial(str(CONTRACT)).deploy()
    sim.usdc.mint(contract.address, 100 * USDC)
    # An activated account gets the full deposit, with no 1 USDC fee.
    # HYPE on Core pays the return gas.
    sim.activate(contract)
    sim.set_hype(contract, 1 * HYPE)
    sim.publish()

    contract.deposit_to_spot(100 * USDC)
    assert contract.core_spot_usdc() == 0  # Core runs after the EVM block

    sim.advance()
    assert contract.core_spot_usdc() == 100 * CORE_USDC

    contract.return_from_spot(40 * USDC)
    sim.advance()
    assert contract.evm_usdc() == 40 * USDC
    assert contract.core_spot_usdc() == 60 * CORE_USDC

    contract.move_to_perp(10 * USDC)
    sim.advance()
    assert sim.perp(contract).usd == 10 * USDC
    assert not sim.failures
