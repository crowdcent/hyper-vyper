"""Money and routing checks. Local submission never stands in for remote arrival."""

import boa
import pytest
from eth_abi import encode

from hyper_vyper.testing import _precompiles as pc
from tests.support import (
    BAD_BOOL_TOKEN,
    CORE_UNIT,
    NO_RETURN_TOKEN,
    RECORDING_WALLET,
    SIM_TOKEN,
    SPOT_DEX,
    START_BALANCE,
    TOKEN_APPROVE_FALSE,
    TOKEN_RESET_FALSE,
    TOKEN_TRANSFER_REVERTS,
    U64,
    USDC,
    USER,
    WALLET,
    ZERO,
    reverts,
    token_payload,
)


@pytest.mark.parametrize("bridge_lab", [999, 998], indirect=True)
@pytest.mark.parametrize("dex", [0, SPOT_DEX])
def test_deposit_for_matches_reference(bridge_lab, dex):
    lab, token, wallet = bridge_lab
    amount = 12_345_678
    for contract in (lab.vy, lab.sol):
        contract.bridge_usdc_to_core_for(USER, amount, dex)
        assert wallet.last_recipient() == USER
        assert wallet.last_amount() == amount
        assert wallet.last_dex() == dex
        assert token.balanceOf(contract.address) == START_BALANCE - amount
        assert token.allowance(contract.address, wallet.address) == 0
    assert wallet.call_count() == 2
    assert token.balanceOf(wallet.address) == amount * 2
    assert lab.writer.call_count() == 0


@pytest.mark.parametrize("bridge_lab", [999, 998], indirect=True)
@pytest.mark.parametrize("dex", [0, SPOT_DEX])
def test_self_deposit_uses_own_account_and_explicit_dex(bridge_lab, dex):
    lab, token, wallet = bridge_lab
    lab.vy.bridge_usdc_to_core(10_000_000, dex)
    assert wallet.last_recipient() == lab.vy.address
    assert wallet.last_amount() == 10_000_000
    assert wallet.last_dex() == dex
    assert token.balanceOf(wallet.address) == 10_000_000
    assert token.allowance(lab.vy.address, wallet.address) == 0
    if dex == SPOT_DEX:
        lab.sol.bridge_usdc_to_core_spot(10_000_000)
        assert wallet.last_recipient() == lab.sol.address
        assert wallet.last_amount() == 10_000_000
        assert wallet.last_dex() == dex


def test_perp_return_route_and_units(bridge_lab):
    lab, _, _ = bridge_lab
    lab.vy.bridge_usdc_to_evm(1_000_000, 0)
    assert lab.writer.last_data() == bytes.fromhex("0100000d") + encode(
        ["address", "address", "uint32", "uint32", "uint64", "uint64"],
        ["0x2000000000000000000000000000000000000000", ZERO, 0, SPOT_DEX, 0, CORE_UNIT],
    )


# reason None: a checked conversion overflows, which has no reason string.
@pytest.mark.parametrize(
    "method,args,reason",
    [
        ("bridge_usdc_to_core", (0, 0), "Amount too small"),
        ("bridge_usdc_to_core", (U64 // 100 + 1, SPOT_DEX), None),
        ("bridge_usdc_to_core", (2**256 - 1, SPOT_DEX), None),
        ("bridge_usdc_to_core_for", (ZERO, 1_000_000, 0), "Zero recipient"),
        ("bridge_usdc_to_core_for", (USER, 0, 0), "Amount too small"),
        ("bridge_usdc_to_core_for", (USER, U64 // 100 + 1, 0), None),
        ("bridge_usdc_to_evm", (0, 0), "Amount too small"),
        ("bridge_usdc_to_evm", (U64 // 100 + 1, 0), None),
    ],
)
def test_rejected_amounts_have_no_side_effects(bridge_lab, method, args, reason):
    lab, token, wallet = bridge_lab
    with reverts(reason):
        getattr(lab.vy, method)(*args)
    assert token.balanceOf(lab.vy.address) == START_BALANCE
    assert token.allowance(lab.vy.address, wallet.address) == 0
    assert wallet.call_count() == lab.writer.call_count() == 0


@pytest.mark.parametrize("kwargs", [{"evm": USER}, {"evm": "usdc_token"}, {"wei": 6}, {"extra": 0}])
@pytest.mark.parametrize(
    "method,args",
    [
        ("bridge_usdc_to_core", (1_000_000, 0)),
        ("bridge_usdc_to_core_for", (USER, 1_000_000, 0)),
        ("bridge_usdc_to_evm", (1_000_000, 0)),
    ],
)
def test_wrong_usdc_metadata_fails_before_transfer(bridge_lab, kwargs, method, args):
    lab, token, wallet = bridge_lab
    if kwargs.get("evm") == "usdc_token":
        # Core links USDC to the deposit wallet. A link to the token itself is wrong.
        kwargs = {"evm": USDC[boa.env.evm.patch.chain_id]}
    lab.read(pc.TOKEN_INFO, token_payload(**kwargs))
    reason = "USDC link mismatch" if "evm" in kwargs else "USDC decimals mismatch"
    with boa.reverts(reason):
        getattr(lab.vy, method)(*args)
    assert token.balanceOf(lab.vy.address) == START_BALANCE
    assert token.allowance(lab.vy.address, wallet.address) == 0
    assert wallet.call_count() == lab.writer.call_count() == 0


# The reason of the library, or of the mock contract that failed. An ERC-20
# balance underflow has no reason string.
FAILURE_REASONS = {
    "approval": "USDC approval failed",
    "reset": "USDC approval reset failed",
    "transfer": "Transfer failed",
    "wallet": "Deposit failed",
    "balance": None,
}


@pytest.mark.parametrize("failure", list(FAILURE_REASONS))
@pytest.mark.parametrize("for_recipient", [False, True])
def test_failed_external_call_rolls_everything_back(bridge_lab, failure, for_recipient):
    lab, token, wallet = bridge_lab
    amount = 1_000_000
    if failure in ("approval", "reset", "transfer"):
        modes = {
            "approval": TOKEN_APPROVE_FALSE,
            "reset": TOKEN_RESET_FALSE,
            "transfer": TOKEN_TRANSFER_REVERTS,
        }
        token.set_failure(modes[failure])
    elif failure == "wallet":
        wallet.configure(True, 0)
    else:
        amount = 100_000_001
    with reverts(FAILURE_REASONS[failure]):
        if for_recipient:
            lab.vy.bridge_usdc_to_core_for(USER, amount, SPOT_DEX)
        else:
            lab.vy.bridge_usdc_to_core(amount, SPOT_DEX)
    assert token.balanceOf(lab.vy.address) == START_BALANCE
    assert token.balanceOf(wallet.address) == 0
    assert token.allowance(lab.vy.address, wallet.address) == 0
    assert wallet.call_count() == 0


def test_unused_allowance_is_cleared(bridge_lab):
    lab, token, wallet = bridge_lab
    wallet.configure(False, 500)
    lab.vy.bridge_usdc_to_core(1_000_000, SPOT_DEX)
    assert token.allowance(lab.vy.address, wallet.address) == 0
    assert token.balanceOf(lab.vy.address) == 99_000_500


def test_approval_without_return_data_is_supported(bridge_lab):
    lab, _, wallet = bridge_lab
    chain_id = boa.env.evm.patch.chain_id
    token = boa.loads_partial(NO_RETURN_TOKEN).deploy(override_address=USDC[chain_id])
    token.mint(lab.vy.address, 1_000_000)
    lab.vy.bridge_usdc_to_core(1_000_000, SPOT_DEX)
    assert token.balanceOf(wallet.address) == 1_000_000
    assert token.allowance(lab.vy.address, wallet.address) == 0


def test_missing_deposit_wallet_reverts_atomically(lab):
    token = boa.loads_partial(SIM_TOKEN).deploy(override_address=USDC[999])
    token.mint(lab.vy.address, 1_000_000)
    lab.read(pc.TOKEN_INFO, token_payload())
    with boa.reverts():
        lab.vy.bridge_usdc_to_core(1_000_000, SPOT_DEX)
    assert token.allowance(lab.vy.address, WALLET[999]) == 0


def test_missing_token_contract_cannot_fake_approval(lab):
    wallet = boa.loads_partial(RECORDING_WALLET).deploy(USDC[999], override_address=WALLET[999])
    lab.read(pc.TOKEN_INFO, token_payload())
    with boa.reverts():
        lab.vy.bridge_usdc_to_core(1_000_000, SPOT_DEX)
    assert wallet.call_count() == 0


def test_noncanonical_approval_return_reverts(lab):
    token = boa.loads_partial(BAD_BOOL_TOKEN).deploy(override_address=USDC[999])
    wallet = boa.loads_partial(RECORDING_WALLET).deploy(token.address, override_address=WALLET[999])
    token.mint(lab.vy.address, 1_000_000)
    lab.read(pc.TOKEN_INFO, token_payload())
    with boa.reverts():
        lab.vy.bridge_usdc_to_core(1_000_000, SPOT_DEX)
    assert token.allowance(lab.vy.address, wallet.address) == 0
    assert wallet.call_count() == 0


def test_maximum_bridge_amount_and_minimum_unit(bridge_lab):
    lab, token, wallet = bridge_lab
    amount = U64 // 100
    token.mint(lab.vy.address, amount)
    lab.vy.bridge_usdc_to_core(amount, SPOT_DEX)
    assert wallet.last_amount() == amount
    lab.vy.bridge_usdc_to_evm(amount, SPOT_DEX)
    assert int.from_bytes(lab.writer.last_data()[-32:], "big") == amount * 100
    lab.vy.bridge_usdc_to_evm(1, SPOT_DEX)
    assert int.from_bytes(lab.writer.last_data()[-32:], "big") == 100


def test_library_overflow_check_stops_the_deposit(bridge_lab):
    # The contract holds enough USDC, so only the library's own check can stop this.
    lab, token, wallet = bridge_lab
    amount = U64 // 100 + 1
    token.mint(lab.vy.address, amount)
    with boa.reverts():
        lab.vy.bridge_usdc_to_core(amount, SPOT_DEX)
    assert wallet.call_count() == 0
    assert token.allowance(lab.vy.address, wallet.address) == 0


@pytest.mark.parametrize("for_recipient", [False, True])
def test_deposit_reads_usdc_metadata_and_approves_exact_amount(bridge_lab, for_recipient):
    lab, _, wallet = bridge_lab
    if for_recipient:
        lab.vy.bridge_usdc_to_core_for(USER, 1_234_567, 0)
    else:
        lab.vy.bridge_usdc_to_core(1_234_567, 0)
    assert lab.reads == [(pc.TOKEN_INFO, encode(["uint64"], [0]))]
    assert wallet.seen_allowance() == 1_234_567


def test_return_reads_usdc_metadata(bridge_lab):
    lab, _, _ = bridge_lab
    lab.vy.bridge_usdc_to_evm(1_000_000, SPOT_DEX)
    assert lab.reads == [(pc.TOKEN_INFO, encode(["uint64"], [0]))]
