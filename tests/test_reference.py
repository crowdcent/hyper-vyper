"""Compare compiled Vyper with the actual pinned Solidity implementation."""

import boa
import pytest
from eth_abi import encode
from eth_utils import keccak
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from hyper_vyper.testing import _precompiles as pc
from tests.support import SPOT_DEX, U64, USER, VAULT, ZERO, normalized, token_payload


@pytest.mark.parametrize(
    "name,args,suffix,words,bad_last",
    [
        ("bbo", (0,), pc.BBO, 2, 2**64),
        ("spot_balance", (USER, 0), pc.SPOT_BALANCE, 3, 2**64),
        ("position", (USER, 0), pc.POSITION2, 5, 2),
        ("account_margin_summary", (0, USER), pc.ACCOUNT_MARGIN_SUMMARY, 4, 2**63),
        ("user_vault_equity", (USER, VAULT), pc.VAULT_EQUITY, 2, 2**64),
        ("delegator_summary", (USER,), pc.DELEGATOR_SUMMARY, 4, 2**64),
        ("borrow_lend_user_state", (USER, 0), pc.BORROW_LEND_USER_STATE, 4, 2**64),
        ("borrow_lend_reserve_state", (0,), pc.BORROW_LEND_RESERVE_STATE, 8, 2**64),
    ],
)
@pytest.mark.parametrize("malformation", ["truncated", "out_of_range"])
def test_static_struct_decoder_rejects_malformed_fields(
    lab, name, args, suffix, words, bad_last, malformation
):
    payload = b"\x00" * (32 * (words - 1))
    if malformation == "out_of_range":
        payload += bad_last.to_bytes(32, "big")
    lab.read(suffix, payload)
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            getattr(contract, name)(*args)


@pytest.mark.parametrize("payload", [b"", b"\x00" * 31, (2**64).to_bytes(32, "big")])
def test_bad_integer_reply_reverts_both(lab, payload):
    lab.read(pc.WITHDRAWABLE, payload)
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.withdrawable(USER)


def test_bad_boolean_reply_reverts_both(lab):
    lab.read(pc.CORE_USER_EXISTS, (2).to_bytes(32, "big"))
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.core_user_exists(USER)


@pytest.mark.parametrize("malformation", ["truncated", "bad_offset"])
def test_malformed_dynamic_reply_reverts_both(lab, malformation):
    payload = token_payload()
    if malformation == "truncated":
        payload = payload[:-32]
    else:
        payload = (2**256 - 1).to_bytes(32, "big") + payload[32:]
    lab.read(pc.TOKEN_INFO, payload)
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.token_info(0)


@pytest.mark.parametrize(
    "name,args,suffix",
    [
        ("withdrawable", (USER,), pc.WITHDRAWABLE),
        ("token_info", (0,), pc.TOKEN_INFO),
        ("borrow_lend_user_state", (USER, 0), pc.BORROW_LEND_USER_STATE),
        ("borrow_lend_reserve_state", (0,), pc.BORROW_LEND_RESERVE_STATE),
    ],
)
def test_failed_read_never_becomes_zero(lab, name, args, suffix):
    lab.read(suffix, fail=True)
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            getattr(contract, name)(*args)


@pytest.mark.parametrize(
    "suffix,method,args,limit",
    [
        # SMALL_READ_GAS and LARGE_READ_GAS in precompiles.vy
        (pc.WITHDRAWABLE, "withdrawable", (USER,), 75_000),
        (pc.TOKEN_INFO, "token_info", (0,), 1_100_000),
    ],
)
def test_read_gas_is_bounded(lab, suffix, method, args, limit):
    lab.read(suffix, gas=limit + 1)
    with boa.reverts():
        getattr(lab.vy, method)(*args)
    assert lab.calls[-1][2] == limit


@pytest.mark.parametrize("count", [0, 1, 256])
def test_token_info_maximum_parity(lab, count):
    lab.read(pc.TOKEN_INFO, token_payload(name="X" * 64, spots=tuple(range(count))))
    assert normalized(lab.vy.token_info(U64)) == normalized(lab.sol.token_info(U64))
    assert lab.calls[0][1] == encode(["uint64"], [U64])


@pytest.mark.parametrize(
    "kind,limit", [("token_info", 256), ("token_supply", 256), ("delegations", 64)]
)
@pytest.mark.parametrize("over_limit", [False, True])
def test_dynamic_bounds(lab, kind, limit, over_limit):
    count = limit + int(over_limit)
    if kind == "token_info":
        payload, suffix, args = token_payload(spots=tuple(range(count))), pc.TOKEN_INFO, (0,)
    elif kind == "token_supply":
        payload = encode(
            ["(uint64,uint64,uint64,uint64,(address,uint64)[])"],
            [(10, 9, 8, 7, [(USER, 1)] * count)],
        )
        suffix, args = pc.TOKEN_SUPPLY, (U64,)
    else:
        payload = encode(["(address,uint64,uint64)[]"], [[(USER, 1, 2)] * count])
        suffix, args = pc.DELEGATIONS, (USER,)
    lab.read(suffix, payload)
    sol = getattr(lab.sol, kind)(*args)
    if over_limit:
        with boa.reverts():
            getattr(lab.vy, kind)(*args)
    else:
        assert normalized(getattr(lab.vy, kind)(*args)) == normalized(sol)


@pytest.mark.parametrize("name", ["X" * 65, "X" * 96])
def test_long_metadata_name_fails_closed(lab, name):
    lab.read(pc.TOKEN_INFO, token_payload(name=name))
    with boa.reverts():
        lab.vy.token_info(0)


@settings(
    max_examples=75, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(amount=st.integers(min_value=0, max_value=U64 // 100))
@example(amount=U64 // 100)
def test_usdc_conversion_property(lab, amount):
    lab.calls.clear()
    lab.read(pc.TOKEN_INFO, token_payload())
    core = amount * 100
    assert lab.vy.evm_to_wei(0, amount) == lab.sol.evm_to_wei(0, amount) == core
    assert lab.vy.wei_to_evm(0, core) == lab.sol.wei_to_evm(0, core) == amount
    assert lab.vy.perp_to_wei(amount) == lab.sol.perp_to_wei(amount) == core
    with_remainder = min(U64, core + 99)
    assert lab.vy.wei_to_perp(with_remainder) == lab.sol.wei_to_perp(with_remainder) == amount


@pytest.mark.parametrize("extra", [-2, 0, 10])
@pytest.mark.parametrize("amount", [0, 1, 99, 100, 1_000_001, U64 // 100])
def test_conversion_rounding_parity(lab, extra, amount):
    lab.read(pc.TOKEN_INFO, token_payload(extra=extra))
    for name in ("evm_to_wei", "wei_to_evm", "wei_to_sz"):
        assert getattr(lab.vy, name)(0, amount) == getattr(lab.sol, name)(0, amount)


@pytest.mark.parametrize("chain_id,token", [(999, 150), (998, 1105)])
def test_native_hype_and_network_addresses(lab, chain_id, token):
    boa.env.evm.patch.chain_id = chain_id
    lab.read(pc.TOKEN_INFO, token_payload(evm=ZERO))
    for name in ("hype_token_index", "usdc_address", "core_deposit_wallet"):
        assert normalized(getattr(lab.vy, name)()) == normalized(getattr(lab.sol, name)())
    assert lab.vy.hype_token_index() == token
    for amount in (0, 1, 10**10 - 1, 5 * 10**18):
        assert lab.vy.evm_to_wei(token, amount) == lab.sol.evm_to_wei(token, amount)
    assert lab.vy.wei_to_evm(token, U64) == lab.sol.wei_to_evm(token, U64)
    for index in (0, token, U64):
        assert lab.vy.system_address(index) == lab.sol.system_address(index)


def test_overflows_revert_both_and_token_index_narrowing_is_stricter(lab):
    lab.read(pc.TOKEN_INFO, token_payload())
    too_large = U64 // 100 + 1
    # Upstream uses SafeCast for amounts and asset IDs; both must reject overflow.
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.evm_to_wei(0, too_large)
        with boa.reverts():
            contract.perp_to_wei(too_large)
        with boa.reverts():
            contract.spot_to_asset_id(2**32 - 10_000)
    with boa.reverts("Token index too large"):
        lab.vy.evm_to_wei(2**32, 1)
    assert lab.sol.evm_to_wei(2**32, 1) == 100


@pytest.mark.parametrize("wei,sz,extra", [(1, 2, -2), (255, 2, 78), (8, 2, -128)])
def test_invalid_conversion_metadata_reverts(lab, wei, sz, extra):
    lab.read(pc.TOKEN_INFO, token_payload(wei=wei, sz=sz, extra=extra))
    name = "sz_to_wei" if wei < sz else "evm_to_wei"
    with boa.reverts():
        getattr(lab.vy, name)(0, 1)


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_vault_lock_boundary_in_milliseconds(lab, delta):
    boa.env.evm.patch.timestamp = 1_700_000_000
    locked_until = boa.env.evm.patch.timestamp * 1000 + delta
    lab.read(pc.VAULT_EQUITY, encode(["uint64", "uint64"], [1000, locked_until]))
    for contract in (lab.vy, lab.sol):
        if delta >= 0:
            with boa.reverts():
                contract.vault_transfer(VAULT, False, 100)
        else:
            contract.vault_transfer(VAULT, False, 100)
        assert lab.calls[-1][1] == encode(["address", "address"], [contract.address, VAULT])
    assert lab.writer.call_count() == (2 if delta < 0 else 0)


def test_writer_failure_propagates(lab):
    lab.writer.set_fail(True)
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.send_asset(USER, ZERO, 0, SPOT_DEX, 0, 100)
    assert lab.writer.call_count() == 0


def test_api_name_bound(lab):
    # Raw calldata tests the contract's ABI decoder, bypassing Python validation.
    data = keccak(text="add_api_wallet(address,string)")[:4] + encode(
        ["address", "string"], [USER, "x" * 33]
    )
    computation = boa.env.execute_code(to_address=lab.vy.address, data=data)
    assert computation.is_error
    assert lab.writer.call_count() == 0


def test_largest_accepted_token_index_matches_reference(lab):
    lab.read(pc.TOKEN_INFO, token_payload())
    largest = 2**32 - 1
    assert lab.vy.evm_to_wei(largest, 7) == lab.sol.evm_to_wei(largest, 7) == 700
    assert lab.calls[0][1] == encode(["uint64"], [largest])


def test_unlinked_token_that_is_not_hype_reverts_both_ways(lab):
    lab.read(pc.TOKEN_INFO, token_payload(evm=ZERO))
    for name, amount in (("evm_to_wei", 10**18), ("wei_to_evm", 1)):
        for contract in (lab.vy, lab.sol):
            with boa.reverts():
                getattr(contract, name)(5, amount)


@pytest.mark.parametrize("amount,expected", [(999_999, 0), (1_000_000, 1), (1_999_999, 1)])
def test_wei_to_sz_rounds_down_at_the_divisor(lab, amount, expected):
    lab.read(pc.TOKEN_INFO, token_payload(wei=8, sz=2))
    assert lab.vy.wei_to_sz(0, amount) == lab.sol.wei_to_sz(0, amount) == expected


def test_known_conversion_values(lab):
    # Fixed values from the Hyperliquid docs, also checked against the reference.
    lab.read(pc.TOKEN_INFO, token_payload(sz=2, wei=8))
    assert lab.vy.sz_to_wei(5, 3) == lab.sol.sz_to_wei(5, 3) == 3 * 10**6
    assert lab.vy.wei_to_sz(5, 3 * 10**6) == lab.sol.wei_to_sz(5, 3 * 10**6) == 3
    assert lab.vy.spot_to_asset_id(107) == lab.sol.spot_to_asset_id(107) == 10_107
    assert lab.vy.asset_to_spot_id(10_107) == lab.sol.asset_to_spot_id(10_107) == 107
    for token, expected in ((0, "0x" + "20" + "00" * 19), (200, "0x20" + "00" * 18 + "c8")):
        assert normalized(lab.vy.system_address(token)) == expected
        assert normalized(lab.sol.system_address(token)) == expected
    assert normalized(lab.vy.system_address(150)) == "0x" + "22" * 20
