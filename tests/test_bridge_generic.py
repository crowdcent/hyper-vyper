"""Generic HyperEVM <-> HyperCore bridging, checked against the pinned reference.

Token metadata is recorded from the real chains (scripts/record_live_replies.py).
Local submission never stands in for remote arrival.
"""

import boa
import pytest
from eth_abi import encode
from eth_utils import keccak

from hyper_vyper.testing import HYPE_TOKEN
from hyper_vyper.testing import _precompiles as pc
from tests.support import (
    GAS_HUNGRY_RECEIVER,
    HYPE_SYSTEM,
    HYPE_SYSTEM_CODE,
    LINKED_TOKEN,
    SPOT_DEX,
    U64,
    USDC,
    USER,
    ZERO,
    live_reply,
    send_asset_payload,
    system_address_for,
    token_info,
    token_payload,
)

# (recorded reply, chain, token index): Core has more decimals than EVM (UBTC),
# fewer (UETH, PURR).
LINKED = [("token_info_ubtc", 999, 197), ("token_info_ueth", 999, 221), ("token_info_purr", 998, 1)]
START = 10**30


def unit_of(extra):
    """Smallest EVM amount worth one Core unit."""
    return 10**extra if extra > 0 else 1


def to_wei(extra, amount):
    if extra >= 0:
        return amount // 10**extra
    return amount * 10**-extra


# Tokens with fewer Core decimals than EVM decimals. Only these can have an EVM
# amount that is not a whole number of Core units.
def extra_decimals(name, chain_id):
    return token_info(live_reply(name, chain_id)).evm_extra_wei_decimals


LINKED_WITH_REMAINDER = [case for case in LINKED if extra_decimals(case[0], case[1]) > 0]


def linked_ids(cases):
    return [case[0][len("token_info_") :] for case in cases]


def setup_linked(lab, case):
    name, chain_id, index = case
    boa.env.evm.patch.chain_id = chain_id
    reply = live_reply(name, chain_id)
    info = token_info(reply)
    token = boa.loads_partial(LINKED_TOKEN).deploy(override_address=info.evm_contract)
    for contract in (lab.vy, lab.sol):
        token.mint(contract.address, START)
    lab.read(pc.TOKEN_INFO, reply)
    return lab, token, index, info.evm_extra_wei_decimals


@pytest.fixture(params=LINKED, ids=linked_ids(LINKED))
def linked(lab, request):
    return setup_linked(lab, request.param)


@pytest.fixture(params=LINKED_WITH_REMAINDER, ids=linked_ids(LINKED_WITH_REMAINDER))
def linked_with_remainder(lab, request):
    return setup_linked(lab, request.param)


@pytest.fixture(params=[999, 998])
def hype(lab, request):
    chain_id = request.param
    boa.env.evm.patch.chain_id = chain_id
    boa.env.set_code(HYPE_SYSTEM, HYPE_SYSTEM_CODE)
    for contract in (lab.vy, lab.sol):
        boa.env.set_balance(contract.address, START)
    lab.read(pc.TOKEN_INFO, live_reply("token_info_hype", chain_id))
    return lab, HYPE_TOKEN[chain_id]


# --- Linked ERC-20, EVM -> Core ---


def test_recorded_tokens_are_linked_erc20s():
    for name, chain_id, _ in LINKED:
        info = token_info(live_reply(name, chain_id))
        assert info.evm_contract != ZERO and info.evm_extra_wei_decimals != 0
    # The cases cover both directions: more Core decimals and fewer Core decimals.
    assert {extra_decimals(name, chain_id) > 0 for name, chain_id, _ in LINKED} == {True, False}


@pytest.mark.parametrize("method", ["bridge_to_core", "bridge_erc20_to_core"])
@pytest.mark.parametrize("units", [1, 3, 10**12])
def test_erc20_to_core_matches_reference(linked, method, units):
    lab, token, index, extra = linked
    amount = units * unit_of(extra)
    system = system_address_for(index)
    assert getattr(lab.vy, method)(index, amount) == to_wei(extra, amount)
    assert token.balanceOf(system) == amount
    lab.sol.bridge_to_core(index, amount)
    assert token.balanceOf(system) == 2 * amount
    assert token.balanceOf(lab.vy.address) == token.balanceOf(lab.sol.address) == START - amount
    assert token.transfer_count() == 2
    assert lab.writer.call_count() == 0


@pytest.mark.parametrize("method", ["bridge_to_core", "bridge_erc20_to_core"])
def test_erc20_to_core_rejects_a_remainder_unlike_upstream(linked_with_remainder, method):
    # Core burns EVM units below one Core unit. The library refuses to send them.
    lab, token, index, extra = linked_with_remainder
    amount = 3 * unit_of(extra) + 1
    with boa.reverts("Not a whole Core unit"):
        getattr(lab.vy, method)(index, amount)
    assert token.balanceOf(lab.vy.address) == START
    lab.sol.bridge_to_core(index, amount)
    assert token.balanceOf(system_address_for(index)) == amount


def test_erc20_to_core_reads_metadata_once(linked):
    lab, _, index, extra = linked
    lab.vy.bridge_to_core(index, unit_of(extra))
    read = (pc.TOKEN_INFO, encode(["uint64"], [index]))
    assert lab.reads == [read]
    lab.calls.clear()
    lab.sol.bridge_to_core(index, unit_of(extra))
    # The reference reads the same metadata twice (conversion, then address).
    assert lab.reads == [read, read]


def test_erc20_amount_that_truncates_to_zero_reverts(linked):
    lab, token, index, extra = linked
    amounts = [0] + ([unit_of(extra) - 1] if extra > 0 else [])
    for amount in amounts:
        for contract in (lab.vy, lab.sol):
            with boa.reverts():
                contract.bridge_to_core(index, amount)
        with boa.reverts("Amount too small"):
            lab.vy.bridge_erc20_to_core(index, amount)
    assert token.transfer_count() == 0


def test_erc20_core_amount_overflow_reverts(linked):
    lab, token, index, extra = linked
    largest = U64 * 10**extra if extra > 0 else U64 // 10**-extra
    token.mint(lab.vy.address, largest + unit_of(extra))
    assert lab.vy.bridge_to_core(index, largest) == to_wei(extra, largest)
    too_large = largest + unit_of(extra)
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.bridge_to_core(index, too_large)
    with boa.reverts():
        lab.vy.bridge_to_core(index, 2**256 - 1)
    assert token.transfer_count() == 1


# 1: transfer returns false. 2: transfer reverts with its own reason.
@pytest.mark.parametrize("failure,reason", [(1, "Token transfer failed"), (2, "Transfer failed")])
def test_failed_erc20_transfer_reverts(linked, failure, reason):
    lab, token, index, extra = linked
    token.set_failure(failure)
    with boa.reverts(reason):
        lab.vy.bridge_to_core(index, unit_of(extra))
    assert token.balanceOf(system_address_for(index)) == 0


def test_insufficient_erc20_balance_reverts(linked):
    lab, token, index, _ = linked
    with boa.reverts():
        lab.vy.bridge_to_core(index, START + 1)
    assert token.balanceOf(lab.vy.address) == START


def test_erc20_without_return_data_is_supported(lab):
    source = LINKED_TOKEN.replace(
        "def transfer(recipient: address, amount: uint256) -> bool:",
        "def transfer(recipient: address, amount: uint256):",
    ).replace("        return False\n", '        raise "False"\n')
    source = source.replace("    return True\n", "")
    token = boa.loads_partial(source).deploy()
    token.mint(lab.vy.address, 10**18)
    lab.read(pc.TOKEN_INFO, token_payload(name="T", evm=token.address, extra=10))
    assert lab.vy.bridge_to_core(5, 10**18) == 10**8
    assert token.balanceOf(system_address_for(5)) == 10**18


def test_linked_address_without_code_reverts(lab):
    lab.read(pc.TOKEN_INFO, token_payload(name="T", evm=USER, extra=0))
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.bridge_to_core(5, 100)


def test_unlinked_token_reverts_before_transfer(lab):
    lab.read(pc.TOKEN_INFO, token_payload(name="T", evm=ZERO, extra=0))
    with boa.reverts("Token not linked to EVM"):
        lab.vy.bridge_to_core(5, 100)
    with boa.reverts():
        lab.sol.bridge_to_core(5, 100)


@pytest.mark.parametrize("index,reason", [(0, "Use the USDC route"), (150, "Use the HYPE route")])
def test_erc20_route_rejects_usdc_and_hype(lab, index, reason):
    with boa.reverts(reason):
        lab.vy.bridge_erc20_to_core(index, 10**18)
    assert lab.calls == []


def test_token_index_above_uint32_is_rejected(lab):
    # Upstream reads metadata for uint32(index) but sends to the system address of
    # the full index, so its two halves describe different tokens.
    token = boa.loads_partial(LINKED_TOKEN).deploy()
    token.mint(lab.sol.address, 100)
    lab.read(pc.TOKEN_INFO, token_payload(name="T", evm=token.address, extra=0))
    index = 2**32 + 5
    for method, args in [("bridge_to_core", (index, 100)), ("bridge_to_evm", (index, 100, True))]:
        with boa.reverts("Token index too large"):
            getattr(lab.vy, method)(*args)
    assert lab.calls == []
    lab.sol.bridge_to_core(index, 100)
    assert token.balanceOf(system_address_for(index)) == 100
    assert lab.reads == [(pc.TOKEN_INFO, encode(["uint64"], [5]))] * 2


# --- HYPE, EVM -> Core ---


@pytest.mark.parametrize("amount", [10**10, 3 * 10**18])
def test_hype_to_core_matches_reference(hype, amount):
    lab, index = hype
    assert lab.vy.bridge_hype_to_core(amount) == amount // 10**10
    assert lab.vy.bridge_to_core(index, amount) == amount // 10**10
    lab.sol.bridge_to_core(index, amount)
    assert boa.env.get_balance(HYPE_SYSTEM) == 3 * amount
    assert boa.env.get_balance(lab.vy.address) == START - 2 * amount
    assert boa.env.get_balance(lab.sol.address) == START - amount
    assert lab.writer.call_count() == 0


def test_hype_to_core_rejects_a_remainder_unlike_upstream(hype):
    lab, index = hype
    for method, args in [
        ("bridge_hype_to_core", (10**10 + 5,)),
        ("bridge_to_core", (index, 10**10 + 5)),
    ]:
        with boa.reverts("Not a whole Core unit"):
            getattr(lab.vy, method)(*args)
    assert boa.env.get_balance(lab.vy.address) == START
    # The reference sends the full value; Core burns the 5 wei remainder.
    lab.sol.bridge_to_core(index, 10**10 + 5)
    assert boa.env.get_balance(HYPE_SYSTEM) == 10**10 + 5


def test_hype_to_core_uses_fixed_decimals_without_a_read(hype):
    # HYPE is always 18 EVM and 8 Core decimals, so no metadata read is needed.
    lab, _ = hype
    assert lab.vy.bridge_hype_to_core(10**18) == 10**8
    assert lab.reads == []


def test_hype_value_sent_with_call_is_bridged(hype):
    lab, index = hype
    boa.env.set_balance(lab.vy.address, 0)
    boa.env.set_balance(boa.env.eoa, 10**18)
    lab.vy.bridge_to_core(index, 10**18, value=10**18)
    assert boa.env.get_balance(HYPE_SYSTEM) == 10**18


@pytest.mark.parametrize("amount", [0, 10**10 - 1])
def test_hype_amount_that_truncates_to_zero_reverts(hype, amount):
    lab, index = hype
    for call in (
        lambda c: c.bridge_to_core(index, amount),
        lambda c: c.bridge_hype_to_core(amount),
    ):
        with boa.reverts():
            call(lab.vy)
    with boa.reverts():
        lab.sol.bridge_to_core(index, amount)
    assert boa.env.get_balance(HYPE_SYSTEM) == 0


def test_hype_core_amount_overflow_reverts(hype):
    lab, index = hype
    too_large = (U64 + 1) * 10**10
    boa.env.set_balance(lab.vy.address, too_large)
    boa.env.set_balance(lab.sol.address, too_large)
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.bridge_to_core(index, too_large)
    assert lab.vy.bridge_to_core(index, U64 * 10**10) == U64


def test_insufficient_hype_balance_reverts(hype):
    lab, _ = hype
    with boa.reverts():
        lab.vy.bridge_hype_to_core(START + 1)
    assert boa.env.get_balance(lab.vy.address) == START


def test_rejecting_hype_receiver_reverts(hype):
    lab, _ = hype
    boa.env.set_code(HYPE_SYSTEM, bytes.fromhex("60006000fd"))  # revert(0, 0)
    with boa.reverts():
        lab.vy.bridge_hype_to_core(10**18)
    assert boa.env.get_balance(lab.vy.address) == START


def test_hype_transfer_forwards_more_than_the_stipend(hype):
    # The reference forwards all gas. A 2300-gas send would fail here.
    lab, _ = hype
    receiver = boa.loads_partial(GAS_HUNGRY_RECEIVER).deploy()
    boa.env.set_code(HYPE_SYSTEM, boa.env.get_code(receiver.address))
    lab.vy.bridge_hype_to_core(10**18)
    assert boa.env.get_balance(HYPE_SYSTEM) == 10**18


def test_live_hype_receiver_emits_received(hype):
    lab, _ = hype
    lab.vy.bridge_hype_to_core(10**18)
    entries = lab.vy._computation.get_log_entries()
    topic = int.from_bytes(keccak(text="Received(address,uint256)"), "big")
    sender = int(lab.vy.address, 16)
    assert any(
        int.from_bytes(address, "big") == int(HYPE_SYSTEM, 16)
        and tuple(topics) == (topic, sender)
        and int.from_bytes(data, "big") == 10**18
        for address, topics, data in entries
    )


# --- USDC keeps its deposit-wallet route ---


@pytest.mark.parametrize("amount", [1, 12_345_678])
def test_usdc_to_core_uses_deposit_wallet_spot(bridge_lab, amount):
    lab, token, wallet = bridge_lab
    for contract in (lab.vy, lab.sol):
        contract.bridge_to_core(0, amount)
        assert wallet.last_recipient() == contract.address
        assert wallet.last_amount() == amount
        assert wallet.last_dex() == SPOT_DEX
        assert token.balanceOf(contract.address) == 100_000_000 - amount
        assert token.allowance(contract.address, wallet.address) == 0
    assert token.balanceOf(wallet.address) == 2 * amount
    assert token.balanceOf(system_address_for(0)) == 0
    assert lab.writer.call_count() == 0


def test_usdc_to_core_returns_core_amount(bridge_lab):
    lab, _, _ = bridge_lab
    assert lab.vy.bridge_to_core(0, 1_000_000) == 100_000_000


@pytest.mark.parametrize("amount", [0, U64 // 100 + 1])
def test_usdc_to_core_rejects_bad_amounts(bridge_lab, amount):
    lab, token, wallet = bridge_lab
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.bridge_to_core(0, amount)
    assert wallet.call_count() == 0


def test_usdc_to_core_rejects_wrong_link(bridge_lab):
    lab, _, wallet = bridge_lab
    lab.read(pc.TOKEN_INFO, token_payload(evm=USDC[boa.env.evm.patch.chain_id]))
    with boa.reverts("USDC link mismatch"):
        lab.vy.bridge_to_core(0, 1_000_000)
    assert wallet.call_count() == 0


# --- Core -> EVM ---


@pytest.mark.parametrize("is_evm_amount", [True, False])
def test_erc20_to_evm_matches_reference(linked, is_evm_amount):
    lab, _, index, extra = linked
    amount = 7 * max(unit_of(extra), 10**-extra if extra < 0 else 1)
    expected = to_wei(extra, amount) if is_evm_amount else amount
    assert lab.vy.bridge_to_evm(index, amount, is_evm_amount) == expected
    payload = lab.writer.last_data()
    assert payload == send_asset_payload(index, expected)
    lab.sol.bridge_to_evm(index, amount, is_evm_amount)
    assert lab.writer.last_data() == payload
    assert lab.reads[0] == (pc.TOKEN_INFO, encode(["uint64"], [index]))


@pytest.mark.parametrize("is_evm_amount", [True, False])
def test_hype_to_evm_matches_reference(hype, is_evm_amount):
    lab, index = hype
    amount = 10**18 if is_evm_amount else 12_345
    expected = amount // 10**10 if is_evm_amount else amount
    assert lab.vy.bridge_to_evm(index, amount, is_evm_amount) == expected
    payload = lab.writer.last_data()
    assert payload == send_asset_payload(index, expected)
    lab.sol.bridge_to_evm(index, amount, is_evm_amount)
    assert lab.writer.last_data() == payload


@pytest.mark.parametrize("is_evm_amount", [True, False])
def test_usdc_to_evm_matches_reference(bridge_lab, is_evm_amount):
    lab, token, _ = bridge_lab
    amount = 1_234_567 if is_evm_amount else 123_456_700
    assert lab.vy.bridge_to_evm(0, amount, is_evm_amount) == 123_456_700
    payload = lab.writer.last_data()
    assert payload == send_asset_payload(0, 123_456_700)
    lab.sol.bridge_to_evm(0, amount, is_evm_amount)
    assert lab.writer.last_data() == payload
    # The existing helper submits the same action from the spot DEX.
    lab.vy.bridge_usdc_to_evm(1_234_567, SPOT_DEX)
    assert lab.writer.last_data() == payload
    assert token.balanceOf(lab.vy.address) == 100_000_000


def test_usdc_to_evm_checks_usdc_metadata(bridge_lab):
    lab, _, _ = bridge_lab
    lab.read(pc.TOKEN_INFO, token_payload(wei=6))
    for is_evm_amount in (True, False):
        with boa.reverts("USDC decimals mismatch"):
            lab.vy.bridge_to_evm(0, 100_000_000, is_evm_amount)
    assert lab.writer.call_count() == 0


def test_to_evm_zero_and_truncated_amounts_revert(linked):
    lab, _, index, extra = linked
    cases = [(0, True), (0, False)] + ([(unit_of(extra) - 1, True)] if extra > 0 else [])
    for amount, is_evm_amount in cases:
        reason = "Amount too small" if amount == 0 else "Not a whole Core unit"
        with boa.reverts(reason):
            lab.vy.bridge_to_evm(index, amount, is_evm_amount)
    assert lab.writer.call_count() == 0
    for amount, is_evm_amount in cases:
        if is_evm_amount:
            with boa.reverts():
                lab.sol.bridge_to_evm(index, amount, is_evm_amount)
    # Divergence: the reference submits a zero Core amount without a check.
    lab.sol.bridge_to_evm(index, 0, False)
    assert lab.writer.last_data() == send_asset_payload(index, 0)


@pytest.mark.parametrize("core_amount", [99, 199])
def test_to_evm_core_amount_must_be_whole_evm_units(lab, core_amount):
    # UBTC has 2 more Core decimals than EVM decimals: 99 Core wei is 0 EVM units,
    # and 199 Core wei is 1 EVM unit plus 99 wei that cannot arrive.
    boa.env.evm.patch.chain_id = 999
    lab.read(pc.TOKEN_INFO, live_reply("token_info_ubtc", 999))
    with boa.reverts("Not a whole EVM unit"):
        lab.vy.bridge_to_evm(197, core_amount, False)
    assert lab.vy.bridge_to_evm(197, 100, False) == 100
    assert lab.vy.bridge_to_evm(197, 200, False) == 200
    lab.read(pc.TOKEN_INFO, live_reply("token_info_usdc", 999))
    with boa.reverts("Not a whole EVM unit"):
        lab.vy.bridge_to_evm(0, core_amount, False)
    # The reference submits these.
    lab.sol.bridge_to_evm(0, 99, False)
    assert lab.writer.last_data() == send_asset_payload(0, 99)


def test_to_evm_amount_overflow_reverts(linked):
    lab, _, index, extra = linked
    core_unit = 10**-extra if extra < 0 else 1
    largest = U64 - U64 % core_unit
    assert lab.vy.bridge_to_evm(index, largest, False) == largest
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.bridge_to_evm(index, U64 + 1, False)
        evm_too_large = (U64 + 1) * 10**extra if extra > 0 else U64 // 10**-extra + 1
        with boa.reverts():
            contract.bridge_to_evm(index, evm_too_large, True)
    assert lab.writer.call_count() == 1


@pytest.mark.parametrize("is_evm_amount", [True, False])
def test_to_evm_unlinked_token_reverts(lab, is_evm_amount):
    lab.read(pc.TOKEN_INFO, token_payload(name="T", evm=ZERO, extra=0))
    with boa.reverts("Token not linked to EVM"):
        lab.vy.bridge_to_evm(5, 100, is_evm_amount)
    assert lab.writer.call_count() == 0
    if is_evm_amount:
        with boa.reverts():
            lab.sol.bridge_to_evm(5, 100, True)
    else:
        # Divergence: with a Core amount the reference never checks the link.
        lab.sol.bridge_to_evm(5, 100, False)
        assert lab.writer.last_data() == send_asset_payload(5, 100)


def test_to_evm_reads_metadata_once_in_both_modes(linked):
    lab, _, index, extra = linked
    read = (pc.TOKEN_INFO, encode(["uint64"], [index]))
    for is_evm_amount in (True, False):
        lab.calls.clear()
        lab.vy.bridge_to_evm(index, 10**15, is_evm_amount)
        assert lab.reads == [read]


def test_failed_core_writer_reverts(linked):
    lab, _, index, _ = linked
    lab.writer.set_fail(True)
    with boa.reverts():
        lab.vy.bridge_to_evm(index, 10**20, False)


# --- Network checks ---


@pytest.mark.parametrize(
    "method,args",
    [
        ("bridge_to_core", (197, 10**18)),
        ("bridge_to_core", (150, 10**18)),
        ("bridge_erc20_to_core", (197, 10**18)),
        ("bridge_hype_to_core", (10**18,)),
        ("bridge_to_evm", (197, 10**18, True)),
        ("bridge_to_evm", (150, 10**18, False)),
        ("bridge_to_evm", (0, 10**8, False)),
        ("usdc_address", ()),
        ("hype_token_index", ()),
        ("core_deposit_wallet", ()),
        ("bridge_usdc_to_core", (1_000_000, 0)),
        ("bridge_usdc_to_core_for", (USER, 1_000_000, 0)),
        ("bridge_usdc_to_evm", (1_000_000, 0)),
    ],
)
def test_unknown_network_reverts_before_any_read_or_write(lab, method, args):
    boa.env.set_balance(lab.vy.address, START)
    boa.env.evm.patch.chain_id = 1
    with boa.reverts("Unsupported chain"):
        getattr(lab.vy, method)(*args)
    assert lab.calls == []
    assert lab.writer.call_count() == 0
    assert boa.env.get_balance(lab.vy.address) == START


def test_hype_index_is_per_chain(lab):
    # The mainnet HYPE index is an ordinary token index on testnet and vice versa.
    boa.env.evm.patch.chain_id = 998
    lab.read(pc.TOKEN_INFO, token_payload(name="T", evm=ZERO, extra=0))
    with boa.reverts("Token not linked to EVM"):
        lab.vy.bridge_to_core(150, 10**18)
    boa.env.evm.patch.chain_id = 999
    with boa.reverts("Token not linked to EVM"):
        lab.vy.bridge_to_core(1105, 10**18)
