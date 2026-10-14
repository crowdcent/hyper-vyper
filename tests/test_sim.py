"""The HyperCore simulator, driven through the real library by a small contract."""

import boa
import pytest

from hyper_vyper.testing import HYPE_SYSTEM, SPOT_DEX, Policy, system_address
from tests.support import CORE_UNIT, OTHER, SIM_TOKEN, USDC_UNIT, live_reply, token_info

CLIENT = """
# pragma version 0.4.3
# pragma evm-version cancun
from ethereum.ercs import IERC20
from hyper_vyper import bridge
from hyper_vyper import constants
from hyper_vyper import conversions
from hyper_vyper import core_writer
from hyper_vyper import precompiles

# What a vault would track: money that left one ledger but is not yet seen in the other.
pending_to_core: public(uint256)
pending_to_evm: public(uint256)

@external
def to_core(amount: uint256, dex: uint32):
    bridge.bridge_usdc_to_core(amount, dex)
    self.pending_to_core += amount

@external
def to_evm(amount: uint256, dex: uint32):
    bridge.bridge_usdc_to_evm(amount, dex)
    self.pending_to_evm += amount

@external
def clear_pending():
    self.pending_to_core = 0
    self.pending_to_evm = 0

@external
def to_core_and_read(amount: uint256) -> (int64, int64):
    before: int64 = precompiles.account_margin_summary(0, self).account_value
    bridge.bridge_usdc_to_core(amount, 0)
    return before, precompiles.account_margin_summary(0, self).account_value

@external
def class_transfer_and_read(ntl: uint64, to_perp: bool) -> (uint64, int64, uint64, int64):
    spot: uint64 = precompiles.spot_balance(self, 0).total
    perp: int64 = precompiles.account_margin_summary(0, self).account_value
    core_writer.transfer_usd_class(ntl, to_perp)
    return (
        spot,
        perp,
        precompiles.spot_balance(self, 0).total,
        precompiles.account_margin_summary(0, self).account_value,
    )

@external
def send_then_revert(to: address, amount_wei: uint64):
    core_writer.spot_send(to, 0, amount_wei)
    raise "undo"

@external
@payable
def hype_to_core():
    bridge.bridge_hype_to_core(msg.value)

@external
@payable
def hype_then_revert():
    bridge.bridge_hype_to_core(msg.value)
    raise "undo"

@external
def spot_send(to: address, token: uint64, amount_wei: uint64):
    core_writer.spot_send(to, token, amount_wei)

@external
def send_asset(to: address, source_dex: uint32, destination_dex: uint32, amount_wei: uint64):
    core_writer.send_asset(to, empty(address), source_dex, destination_dex, 0, amount_wei)

@external
def transfer_usd_class(ntl: uint64, to_perp: bool):
    core_writer.transfer_usd_class(ntl, to_perp)

@external
def vault_transfer(vault: address, is_deposit: bool, usd: uint64):
    core_writer.vault_transfer(vault, is_deposit, usd)

@external
def add_api_wallet(wallet: address, name: String[32]):
    core_writer.add_api_wallet(wallet, name)

@external
def set_abstraction(mode: uint8):
    core_writer.set_abstraction(self, mode)

@external
def place_order():
    core_writer.place_limit_order(0, True, 1, 1, False, constants.TIF_GTC, 0)

@external
@view
def perp() -> precompiles.AccountMarginSummary:
    return precompiles.account_margin_summary(0, self)

@external
@view
def spot_usdc() -> uint64:
    return precompiles.spot_balance(self, 0).total

@external
@view
def withdrawable() -> uint64:
    return precompiles.withdrawable(self)

@external
@view
def spot_hype() -> uint64:
    return precompiles.spot_balance(self, conversions.hype_token_index()).total

@external
@view
def exists(user: address) -> bool:
    return precompiles.core_user_exists(user)

@external
@view
def vault_equity(vault: address) -> precompiles.UserVaultEquity:
    return precompiles.user_vault_equity(self, vault)

@external
def token_to_evm(token: uint64, amount_wei: uint256):
    bridge.bridge_to_evm(token, amount_wei, False)

@external
@view
def evm_usdc() -> uint256:
    return staticcall IERC20(conversions.usdc_address()).balanceOf(self)

@external
@view
def observed_assets() -> int256:
    # EVM USDC + Core spot USDC (8 -> 6 decimals) + perp account value.
    return (
        convert(staticcall IERC20(conversions.usdc_address()).balanceOf(self), int256)
        + convert(precompiles.spot_balance(self, 0).total // 100, int256)
        + convert(precompiles.account_margin_summary(0, self).account_value, int256)
    )
"""

SIM_VAULT = "0x" + "56" * 20


@pytest.fixture(scope="session")
def client_deployer():
    return boa.loads_partial(CLIENT, name="Client")


FEE_USDC_CORE = Policy().evm_transfer_fee_usdc_fallback_wei


@pytest.fixture
def sim(make_sim):
    return make_sim()


def fund(sim, deployer, evm=10_000, perp=0, spot=0, hype=10**8):
    """A client with EVM USDC, an active Core account and a little HYPE for gas."""
    client = deployer.deploy()
    sim.usdc.mint(client.address, evm * USDC_UNIT)
    sim.activate(client)
    sim.set_hype(client, hype)
    if perp:
        sim.set_perp(client, usd=perp * USDC_UNIT)
    if spot:
        sim.set_spot(client, 0, spot * CORE_UNIT)
    sim.publish()
    return client


@pytest.fixture
def client(sim, client_deployer):
    return fund(sim, client_deployer)


# (1) A deposit is invisible in its own block and visible after it.


@pytest.mark.parametrize("chain_id", [999, 998])
def test_deposit_is_seen_only_in_a_later_block(make_sim, client_deployer, chain_id):
    sim = make_sim(chain_id)
    client = fund(sim, client_deployer)
    before, after = client.to_core_and_read(1_000 * USDC_UNIT)
    assert before == after == 0
    # Another transaction in the same block still sees the old Core state.
    assert client.perp().account_value == 0
    assert client.evm_usdc() == 9_000 * USDC_UNIT
    assert sim.usdc.balanceOf(sim.wallet.address) == 1_000 * USDC_UNIT
    assert [e.status for e in sim.advance()] == ["applied"]
    assert client.perp().account_value == client.perp().raw_usd == 1_000 * USDC_UNIT
    assert client.withdrawable() == 1_000 * USDC_UNIT


def test_spot_deposit_and_unsupported_dex_credit_spot(sim, client):
    client.to_core(100 * USDC_UNIT, SPOT_DEX)
    client.to_core(5 * USDC_UNIT, 1000)  # a DEX that does not exist credits spot
    sim.advance()
    assert client.spot_usdc() == 105 * CORE_UNIT
    assert client.perp().account_value == 0


@pytest.mark.parametrize(
    "amount,spot_after",
    [(2 * USDC_UNIT, 1 * CORE_UNIT), (1 * USDC_UNIT, 0)],
)
def test_deposit_to_an_unactivated_account_activates_it(sim, client_deployer, amount, spot_after):
    # Core takes the 1 USDC activation fee from the deposit, with no escrow.
    client = client_deployer.deploy()
    sim.usdc.mint(client.address, amount)
    client.to_core(amount, SPOT_DEX)
    sim.advance()
    assert sim.events[0].status == "applied"
    assert sim.account_state(client) == "activated"
    assert client.exists(client.address)
    assert client.spot_usdc() == spot_after
    assert sim.escrow(client) == 0
    assert client.evm_usdc() == 0


def test_deposit_to_an_unactivated_account_on_testnet_can_be_dropped(make_sim, client_deployer):
    # The testnet wallet with an address that has no mainnet account.
    sim = make_sim(deposit_to_inactive="drop")
    client = client_deployer.deploy()
    sim.usdc.mint(client.address, 10 * USDC_UNIT)
    client.to_core(10 * USDC_UNIT, 0)
    sim.advance()
    assert sim.events[0].status == "failed"
    assert sim.account_state(client) == "missing"
    assert client.evm_usdc() == 0  # the EVM side is gone


# (2) A return credits EVM only later.


@pytest.mark.parametrize("dex", [0, SPOT_DEX])
def test_return_credits_evm_only_after_the_block(sim, client_deployer, dex):
    client = fund(sim, client_deployer, evm=0, perp=100, spot=100)
    client.to_evm(40 * USDC_UNIT, dex)
    assert client.evm_usdc() == 0
    assert client.perp().account_value == 100 * USDC_UNIT
    assert client.spot_usdc() == 100 * CORE_UNIT
    sim.advance()
    assert client.evm_usdc() == 40 * USDC_UNIT
    if dex == 0:
        assert client.perp().account_value == 60 * USDC_UNIT
    else:
        assert client.spot_usdc() == 60 * CORE_UNIT
    credit = [e for e in sim.events if e.kind == "evm_credit"]
    assert [(c.sender, c.args["amount"]) for c in credit] == [
        (system_address(0, 999), 40 * USDC_UNIT)
    ]
    assert sim.spot(client, sim.hype)[0] == 10**8 - sim.policy.evm_transfer_fee_hype_wei


def test_hype_return_credits_native_balance(sim, client):
    client.spot_send(HYPE_SYSTEM, sim.hype, 50_000)
    assert boa.env.get_balance(client.address) == 0
    sim.advance()
    assert boa.env.get_balance(client.address) == 50_000 * 10**10
    # A HYPE return pays no separate gas fee.
    assert sim.spot(client, sim.hype)[0] == 10**8 - 50_000


def test_spot_usdc_return_without_hype_pays_gas_in_usdc(sim, client_deployer):
    # With 0 HYPE on Core spot, a 1 USDC return from spot arrives. Core takes the
    # gas in USDC from spot.
    client = fund(sim, client_deployer, evm=0, spot=3, hype=0)
    client.to_evm(1 * USDC_UNIT, SPOT_DEX)
    sim.advance()
    assert client.evm_usdc() == 1 * USDC_UNIT
    fee = sim.policy.evm_transfer_fee_usdc_fallback_wei
    assert fee == 92_700
    assert client.spot_usdc() == 2 * CORE_UNIT - fee
    assert sim.events[-2].reason == "gas charged in USDC: no HYPE on Core spot"


def test_spot_usdc_return_without_hype_fails_if_usdc_cannot_pay_the_gas(sim, client_deployer):
    client = fund(sim, client_deployer, evm=0, spot=3, hype=0)
    client.to_evm(3 * USDC_UNIT, SPOT_DEX)  # the whole balance leaves nothing for gas
    sim.advance()
    assert sim.failures[-1].reason == "no HYPE or USDC for EVM gas"
    assert (client.spot_usdc(), client.evm_usdc()) == (3 * CORE_UNIT, 0)


@pytest.mark.parametrize(
    "perp,spot,amount,evm,spot_after,perp_after",
    [
        # Gas comes from spot USDC when spot has USDC.
        (2, 1, 1 * USDC_UNIT, 1 * USDC_UNIT, CORE_UNIT - FEE_USDC_CORE, 1 * USDC_UNIT),
        # Without spot USDC, gas comes from perp.
        (1, 0, USDC_UNIT // 2, USDC_UNIT // 2, 0, USDC_UNIT // 2 - FEE_USDC_CORE // 100),
        # The whole perp balance leaves nothing for gas, so the return fails.
        (1, 0, 1 * USDC_UNIT, 0, 0, 1 * USDC_UNIT),
    ],
)
def test_perp_usdc_return_without_hype(
    sim, client_deployer, perp, spot, amount, evm, spot_after, perp_after
):
    client = fund(sim, client_deployer, evm=0, perp=perp, spot=spot, hype=0)
    client.to_evm(amount, 0)
    sim.advance()
    assert client.evm_usdc() == evm
    assert client.spot_usdc() == spot_after
    assert sim.perp(client).withdrawable == perp_after


# (3) Silent failures: the EVM call succeeds, Core does not change.


@pytest.mark.parametrize(
    "setup,call,reason",
    [
        (lambda sim, p: None, lambda p: p.spot_send(OTHER, 0, 1), "insufficient spot balance"),
        (
            lambda sim, p: sim.set_spot(p, 0, CORE_UNIT),
            lambda p: p.spot_send(OTHER, 0, 1),
            "recipient not activated (needs >= 1 USDC)",
        ),
        (
            lambda sim, p: sim.set_perp(p, usd=5 * USDC_UNIT),
            lambda p: p.to_evm(10 * USDC_UNIT, 0),
            "insufficient withdrawable",
        ),
        (
            lambda sim, p: (sim.set_perp(p, usd=10 * USDC_UNIT), sim.set_hype(p, 0)),
            lambda p: p.to_evm(10 * USDC_UNIT, 0),
            "no HYPE or USDC for EVM gas",
        ),
        (
            lambda sim, p: sim.set_perp(p, usd=50 * USDC_UNIT, margin_used=45 * USDC_UNIT),
            lambda p: p.transfer_usd_class(10 * USDC_UNIT, False),
            "insufficient withdrawable",
        ),
        (
            lambda sim, p: sim.set_perp(p, usd=50 * USDC_UNIT),
            lambda p: p.vault_transfer(SIM_VAULT, True, 1),
            "unknown vault",
        ),
        (
            lambda sim, p: sim.set_perp(p, usd=50 * USDC_UNIT),
            lambda p: p.send_asset(OTHER, 0, SPOT_DEX, 150),
            "amount is not a whole perp unit",
        ),
    ],
)
def test_failed_action_leaves_evm_success_and_core_unchanged(sim, client, setup, call, reason):
    setup(sim, client)
    sim.publish()
    perp, spot, evm = client.perp(), client.spot_usdc(), client.evm_usdc()
    hype = sim.spot(client, sim.hype)
    call(client)  # no revert
    assert sim.writer.count() == 1
    sim.advance(blocks=5)
    assert [(e.status, e.reason) for e in sim.events] == [("failed", reason)]
    assert (client.perp(), client.spot_usdc(), client.evm_usdc()) == (perp, spot, evm)
    assert sim.spot(client, sim.hype) == hype


def test_forced_failure_and_missing_sender(sim, client_deployer):
    client = fund(sim, client_deployer, perp=100)
    sim.fail_next("usd_class_transfer", "venue halted")
    client.transfer_usd_class(10 * USDC_UNIT, False)
    client.transfer_usd_class(10 * USDC_UNIT, False)
    sim.advance()
    assert [(e.status, e.reason) for e in sim.events] == [
        ("failed", "venue halted"),
        ("applied", ""),
    ]
    assert client.perp().account_value == 90 * USDC_UNIT
    assert client.spot_usdc() == 10 * CORE_UNIT

    stranger = client_deployer.deploy()  # no Core account
    stranger.transfer_usd_class(1, True)
    sim.advance()
    assert sim.events[-1].reason == "sender not activated"


def test_reverted_transaction_queues_nothing(sim, client):
    sim.activate(OTHER)
    sim.set_spot(client, 0, CORE_UNIT)
    sim.publish()
    with boa.reverts("undo"):
        client.send_then_revert(OTHER, 1)
    sim.advance()
    assert sim.writer.count() == 0 and sim.events == []


# (4) Reads within one block are consistent.


def test_reads_in_one_block_use_the_block_start_state(sim, client_deployer):
    client = fund(sim, client_deployer, perp=100)
    first = client.perp()
    # Core moves between EVM transactions; EVM does not see it until the next block.
    sim.add_pnl(client, unrealized=-7 * USDC_UNIT)
    spot0, perp0, spot1, perp1 = client.class_transfer_and_read(10 * USDC_UNIT, False)
    assert (spot0, perp0) == (spot1, perp1) == (0, 100 * USDC_UNIT)
    assert client.perp() == first
    sim.advance()
    assert client.perp().account_value == 83 * USDC_UNIT
    assert client.perp().raw_usd == 90 * USDC_UNIT
    assert client.spot_usdc() == 10 * CORE_UNIT


def test_moving_blocks_without_the_simulator_is_an_error(sim, client):
    boa.env.time_travel(blocks=1)
    with pytest.raises(RuntimeError, match="advance"):
        client.perp()


# (5) Reconciling pending transfers when P&L moves the same balance.


def test_reconciliation_with_concurrent_pnl(sim, client_deployer):
    client = fund(sim, client_deployer, evm=10_000, perp=5_000)
    start = client.observed_assets()

    client.to_core(1_000 * USDC_UNIT, 0)
    # In flight: the EVM side fell, Core has not risen. Pending fills the gap.
    assert client.observed_assets() == start - 1_000 * USDC_UNIT
    assert client.observed_assets() + client.pending_to_core() == start

    # The market moves while the deposit lands.
    sim.add_pnl(client, unrealized=-30 * USDC_UNIT, realized=-2 * USDC_UNIT)
    sim.advance()
    perp = client.perp()
    assert perp.account_value == 5_968 * USDC_UNIT  # +1000 - 30 - 2
    assert perp.raw_usd == 5_998 * USDC_UNIT  # realized P&L hides inside raw USD too
    # Neither delta equals the deposit, so "delta >= pending" never confirms it ...
    assert perp.account_value - 5_000 * USDC_UNIT < client.pending_to_core()
    # ... and keeping it pending now double counts: the money is in both terms.
    assert client.observed_assets() + client.pending_to_core() == start + 968 * USDC_UNIT
    client.clear_pending()  # completion needs evidence other than this balance

    # A failed deposit plus a lucky +1000 P&L looks the same as a clean arrival.
    sim.fail_next("deposit", "forwarding failed")
    client.to_core(1_000 * USDC_UNIT, 0)
    sim.add_pnl(client, unrealized=1_000 * USDC_UNIT)
    before = client.perp().account_value
    sim.advance()
    assert client.perp().account_value - before == 1_000 * USDC_UNIT
    assert sim.failures[-1].reason == "forwarding failed"


def test_return_gap_between_core_debit_and_evm_credit(make_sim, client_deployer):
    sim = make_sim(evm_credit_extra_blocks=2)
    client = fund(sim, client_deployer, evm=0, perp=1_000)
    start = client.observed_assets()
    client.to_evm(400 * USDC_UNIT, 0)
    seen = []
    for _ in range(3):
        sim.advance()
        observed = client.observed_assets()
        seen.append((client.perp().account_value, client.evm_usdc(), observed))
        # Tracked pending fills the gap exactly until the credit lands ...
        in_flight = sim.events[-1].status == "queued"
        assert (observed + client.pending_to_evm() == start) == in_flight
    assert seen == [
        (600 * USDC_UNIT, 0, start - 400 * USDC_UNIT),  # Core debited, EVM not yet paid
        (600 * USDC_UNIT, 0, start - 400 * USDC_UNIT),
        (600 * USDC_UNIT, 400 * USDC_UNIT, start),
    ]
    # ... after which keeping it pending double counts the return.
    assert client.observed_assets() + client.pending_to_evm() == start + 400 * USDC_UNIT


# Other simulated actions.


def test_vault_transfer_is_delayed_and_locked(sim, client_deployer):
    client = fund(sim, client_deployer, perp=100)
    sim.add_vault(SIM_VAULT)
    client.vault_transfer(SIM_VAULT, True, 60 * USDC_UNIT)
    sim.advance()
    assert sim.events[0].status == "queued"  # documented extra delay
    sim.advance(blocks=sim.policy.delayed_action_blocks)
    assert sim.events[0].status == "applied"
    assert sim.view.accounts[client.address.lower()].vaults[SIM_VAULT][0] == 60 * USDC_UNIT
    assert client.perp().account_value == 40 * USDC_UNIT
    # The library refuses a withdrawal while the block-start view shows a lock.
    with boa.reverts("Vault withdrawal locked"):
        client.vault_transfer(SIM_VAULT, False, 60 * USDC_UNIT)
    sim.advance(seconds=sim.policy.vault_lock_ms // 1000 + 1)
    client.vault_transfer(SIM_VAULT, False, 60 * USDC_UNIT)
    sim.advance(blocks=1 + sim.policy.delayed_action_blocks)
    assert client.perp().account_value == 100 * USDC_UNIT


def test_account_setup_actions_and_unsimulated_actions(sim, client):
    client.add_api_wallet(OTHER, "oms")
    client.set_abstraction(1)
    client.set_abstraction(9)
    client.place_order()
    sim.advance(blocks=1 + sim.policy.delayed_action_blocks)
    assert [(e.name, e.status) for e in sim.events] == [
        ("add_api_wallet", "applied"),
        ("set_abstraction", "applied"),
        ("set_abstraction", "failed"),
        ("limit_order", "recorded"),
    ]
    account = sim.account(client)
    assert account.agents == {"oms": OTHER} and account.abstraction == 1


def test_spot_send_between_accounts(sim, client):
    sim.activate(OTHER)
    sim.set_spot(client, 0, 3 * CORE_UNIT)
    sim.publish()
    client.spot_send(OTHER, 0, CORE_UNIT)
    client.send_asset(OTHER, SPOT_DEX, 0, CORE_UNIT)  # to OTHER's perp account
    sim.advance()
    assert sim.spot(OTHER) == (CORE_UNIT, 0)
    assert sim.perp(OTHER).usd == USDC_UNIT
    assert client.spot_usdc() == CORE_UNIT


# (6) Account activation and escrow.

HYPE_EVM = 10**10  # EVM wei per Core HYPE wei


@pytest.fixture
def sim998(make_sim):
    sim = make_sim(998)
    boa.env.set_balance(boa.env.eoa, 10**18)
    return sim


def test_hype_to_an_unactivated_account_is_escrowed_and_invisible(sim998, client_deployer):
    sim = sim998
    client = client_deployer.deploy()
    client.hype_to_core(value=10_000 * HYPE_EVM)  # 0.0001 HYPE
    assert boa.env.get_balance(HYPE_SYSTEM) == 10_000 * HYPE_EVM
    sim.advance()
    assert [(e.kind, e.status, e.reason) for e in sim.events] == [
        ("bridge_in", "applied", "recipient not activated: held in escrow")
    ]
    assert sim.account_state(client) == "escrow"
    assert sim.escrow(client, sim.hype) == 10_000
    # The precompiles show nothing.
    assert not client.exists(client.address)
    assert client.spot_hype() == 0

    # An action from the unactivated account: EVM success, Core does nothing.
    client.spot_send(HYPE_SYSTEM, sim.hype, 5_000)
    sim.advance(blocks=3)
    assert (sim.events[-1].status, sim.events[-1].reason) == ("failed", "sender not activated")
    assert sim.escrow(client, sim.hype) == 10_000
    assert boa.env.get_balance(client.address) == 0


def test_hype_send_in_a_reverted_transaction_queues_nothing(sim998, client_deployer):
    client = client_deployer.deploy()
    with boa.reverts("undo"):
        client.hype_then_revert(value=10_000 * HYPE_EVM)
    sim998.advance()
    assert sim998.events == [] and sim998.account_state(client) == "missing"


@pytest.mark.parametrize("dex", [SPOT_DEX, 0])
def test_core_transfer_activates_charges_the_fee_and_releases_escrow(sim998, client_deployer, dex):
    sim = sim998
    operator = fund(sim, client_deployer, evm=0, spot=10)
    client = client_deployer.deploy()
    client.hype_to_core(value=10_000 * HYPE_EVM)
    sim.advance()
    assert sim.escrow(client, sim.hype) == 10_000 and sim.account_state(client) == "escrow"

    operator.send_asset(client, SPOT_DEX, dex, 3 * CORE_UNIT)
    sim.advance()
    assert sim.events[-1].reason == "recipient activated: fee charged"
    assert sim.account_state(client) == "activated" and client.exists(client.address)
    # Escrow goes to spot. The sender pays the 1 USDC fee.
    assert sim.escrow(client) == sim.escrow(client, sim.hype) == 0
    assert client.spot_hype() == 10_000
    if dex == SPOT_DEX:
        assert client.spot_usdc() == 3 * CORE_UNIT
    else:
        assert (client.spot_usdc(), client.perp().account_value) == (0, 3 * USDC_UNIT)
    assert operator.spot_usdc() == 6 * CORE_UNIT

    # Now the account's actions work.
    client.transfer_usd_class(3 * USDC_UNIT, dex == SPOT_DEX)
    sim.advance()
    assert sim.events[-1].status == "applied"
    assert client.spot_usdc() == (0 if dex == SPOT_DEX else 3) * CORE_UNIT


@pytest.mark.parametrize("hype,amount", [(False, CORE_UNIT - 1), (True, 10**8)])
def test_a_small_or_non_usdc_send_does_not_activate(sim998, client_deployer, hype, amount):
    sim = sim998
    operator = fund(sim, client_deployer, evm=0, spot=10, hype=10**9)
    client = client_deployer.deploy()
    operator.spot_send(client, sim.hype if hype else 0, amount)
    sim.advance()
    assert sim.failures[-1].reason == "recipient not activated (needs >= 1 USDC)"
    assert sim.account_state(client) == "missing"


def test_bridge_in_models_an_erc20_send_to_a_system_address(sim, client):
    stranger = "0x" + "9a" * 20
    sim.bridge_in(client, 5, 700)
    sim.bridge_in(stranger, 5, 300)
    assert sim.spot(client, 5) == (0, 0)  # lands after the block, like any transfer
    sim.advance()
    assert sim.spot(client, 5) == (700, 0)
    assert sim.account_state(stranger) == "escrow" and sim.escrow(stranger, 5) == 300
    sim.activate(stranger)
    assert sim.spot(stranger, 5) == (300, 0)


def test_vault_first_deposit_pays_the_activation_fee(sim998, client_deployer):
    sim = sim998
    vault = client_deployer.deploy()  # a new contract: no Core account
    sim.usdc.mint(vault.address, 1_000 * USDC_UNIT)
    start = vault.observed_assets()

    vault.to_core(400 * USDC_UNIT, 0)
    sim.advance()
    # The deposit activates the account, and Core takes the 1 USDC fee from it,
    # so the vault must not count the first 1 USDC.
    assert vault.exists(vault.address)
    assert sim.escrow(vault) == 0
    assert vault.perp().account_value == 399 * USDC_UNIT
    assert vault.observed_assets() == start - USDC_UNIT


def test_set_vault_equity_shows_in_the_vault_read(sim, client):
    sim.set_vault_equity(client, SIM_VAULT, 500 * USDC_UNIT, locked_until_ms=1_000)
    sim.publish()
    assert tuple(client.vault_equity(SIM_VAULT)) == (500 * USDC_UNIT, 1_000)


def test_a_linked_token_return_mints_on_evm(sim, client):
    # UBTC: 8 EVM decimals, 10 Core decimals, so 100 Core wei is one EVM unit.
    reply = live_reply("token_info_ubtc", 999)
    info = token_info(reply)
    token = boa.loads_partial(SIM_TOKEN).deploy(override_address=info.evm_contract)
    sim.link_evm_token(197, token, info.evm_extra_wei_decimals, token_info=reply)
    sim.set_spot(client, 197, 10_000)
    sim.publish()
    client.token_to_evm(197, 10_000)
    sim.advance()
    assert token.balanceOf(client.address) == 100
    assert sim.spot(client, 197)[0] == 0


def test_policy_rejects_an_unknown_setting_value():
    with pytest.raises(ValueError, match="deposit_to_inactive"):
        Policy(deposit_to_inactive="escrow")
