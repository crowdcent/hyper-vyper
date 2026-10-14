"""Check every reader: precompile address, input bytes and each decoded field by name.

A positional comparison cannot see two swapped fields of the same type, so these
tests read each field by name. Every field has a distinct value.
"""

import pytest
from eth_abi import encode

from hyper_vyper.testing import _precompiles as pc
from tests.support import (
    PERP_ABI,
    SPOT_ABI,
    TOKEN_ABI,
    U64,
    USER,
    VALIDATOR,
    VAULT,
    normalized,
)

# (reader, args, precompile suffix, input types, reply type, reply value, field names)
READERS = [
    (
        "spot_balance",
        (USER, 5),
        pc.SPOT_BALANCE,
        ["address", "uint64"],
        "(uint64,uint64,uint64)",
        (1_000, 200, 30),
        ["total", "hold", "entry_ntl"],
    ),
    (
        "position",
        (USER, 4),
        pc.POSITION2,
        ["address", "uint32"],
        "(int64,uint64,int64,uint32,bool)",
        (-5, 600, -70, 8, True),
        ["szi", "entry_ntl", "isolated_raw_usd", "leverage", "is_isolated"],
    ),
    (
        "user_vault_equity",
        (USER, VAULT),
        pc.VAULT_EQUITY,
        ["address", "address"],
        "(uint64,uint64)",
        (9_000, 1_700_000_000_123),
        ["equity", "locked_until_timestamp"],
    ),
    (
        "delegator_summary",
        (USER,),
        pc.DELEGATOR_SUMMARY,
        ["address"],
        "(uint64,uint64,uint64,uint64)",
        (11, 22, 33, 4),
        ["delegated", "undelegated", "total_pending_withdrawal", "n_pending_withdrawals"],
    ),
    (
        "perp_asset_info",
        (3,),
        pc.PERP_ASSET_INFO,
        ["uint32"],
        PERP_ABI,
        ("ETH", 56, 4, 25, True),
        ["coin", "margin_table_id", "sz_decimals", "max_leverage", "only_isolated"],
    ),
    (
        "spot_info",
        (9,),
        pc.SPOT_INFO,
        ["uint64"],
        SPOT_ABI,
        ("@9", (150, 360)),
        ["name", "tokens"],
    ),
    (
        "token_info",
        (6,),
        pc.TOKEN_INFO,
        ["uint64"],
        TOKEN_ABI,
        ("TKN", (12, 13), 7, USER, VAULT, 2, 8, -2),
        [
            "name",
            "spots",
            "deployer_trading_fee_share",
            "deployer",
            "evm_contract",
            "sz_decimals",
            "wei_decimals",
            "evm_extra_wei_decimals",
        ],
    ),
    ("bbo", (10_007,), pc.BBO, ["uint64"], "(uint64,uint64)", (101, 103), ["bid", "ask"]),
    (
        "account_margin_summary",
        (1, USER),
        pc.ACCOUNT_MARGIN_SUMMARY,
        ["uint32", "address"],
        "(int64,uint64,uint64,int64)",
        (-1_000, 200, 3_000, -40),
        ["account_value", "margin_used", "ntl_pos", "raw_usd"],
    ),
    # The same readers at the edges of their integer types.
    (
        "position",
        (USER, 100_001),
        pc.POSITION2,
        ["address", "uint32"],
        "(int64,uint64,int64,uint32,bool)",
        (-(2**63), U64, -456, 20, True),
        ["szi", "entry_ntl", "isolated_raw_usd", "leverage", "is_isolated"],
    ),
    (
        "spot_balance",
        (USER, U64),
        pc.SPOT_BALANCE,
        ["address", "uint64"],
        "(uint64,uint64,uint64)",
        (U64, 123, 456),
        ["total", "hold", "entry_ntl"],
    ),
    (
        "account_margin_summary",
        (0, USER),
        pc.ACCOUNT_MARGIN_SUMMARY,
        ["uint32", "address"],
        "(int64,uint64,uint64,int64)",
        (-100, U64, 789, -(2**63)),
        ["account_value", "margin_used", "ntl_pos", "raw_usd"],
    ),
    ("bbo", (U64,), pc.BBO, ["uint64"], "(uint64,uint64)", (123, U64), ["bid", "ask"]),
    (
        "delegator_summary",
        (USER,),
        pc.DELEGATOR_SUMMARY,
        ["address"],
        "(uint64,uint64,uint64,uint64)",
        (U64, 1, 2, 3),
        ["delegated", "undelegated", "total_pending_withdrawal", "n_pending_withdrawals"],
    ),
]

# (reader, args, precompile suffix, input types, reply type, reply value)
SCALARS = [
    ("withdrawable", (USER,), pc.WITHDRAWABLE, ["address"], "uint64", 777),
    ("mark_px", (3,), pc.MARK_PX, ["uint32"], "uint64", 3_100_000),
    ("oracle_px", (3,), pc.ORACLE_PX, ["uint32"], "uint64", 3_200_000),
    ("spot_px", (9,), pc.SPOT_PX, ["uint64"], "uint64", 4_400),
    ("l1_block_number", (), pc.L1_BLOCK_NUMBER, [], "uint64", 123_456),
    ("core_user_exists", (USER,), pc.CORE_USER_EXISTS, ["address"], "bool", True),
    ("core_user_exists", (USER,), pc.CORE_USER_EXISTS, ["address"], "bool", False),
    ("withdrawable", (USER,), pc.WITHDRAWABLE, ["address"], "uint64", U64),
]


def _assert_fields(result, names, values):
    for name, value in zip(names, values, strict=True):
        assert normalized(getattr(result, name)) == normalized(value), name


@pytest.mark.parametrize("case", READERS, ids=[f"{c[0]}-{i}" for i, c in enumerate(READERS)])
def test_struct_reader_fields(lab, case):
    name, args, suffix, input_types, reply_type, value, fields = case
    lab.read(suffix, encode([reply_type], [value]))
    result = getattr(lab.vy, name)(*args)
    _assert_fields(result, fields, value)
    assert normalized(result) == normalized(getattr(lab.sol, name)(*args))
    assert lab.reads == [(suffix, encode(input_types, args))] * 2


@pytest.mark.parametrize("case", SCALARS, ids=[f"{c[0]}-{i}" for i, c in enumerate(SCALARS)])
def test_scalar_reader(lab, case):
    name, args, suffix, input_types, reply_type, value = case
    lab.read(suffix, encode([reply_type], [value]))
    assert getattr(lab.vy, name)(*args) == value
    assert getattr(lab.sol, name)(*args) == value
    assert lab.reads == [(suffix, encode(input_types, args))] * 2


def test_list_reader_fields(lab):
    entries = [(VALIDATOR, 500, 1_700_000_000_000), (VAULT, 600, 1_800_000_000_000)]
    lab.read(pc.DELEGATIONS, encode(["(address,uint64,uint64)[]"], [entries]))
    result = lab.vy.delegations(USER)
    for item, value in zip(result, entries, strict=True):
        _assert_fields(item, ["validator", "amount", "locked_until_timestamp"], value)
    assert normalized(result) == normalized(lab.sol.delegations(USER))

    lab.read(
        pc.TOKEN_SUPPLY,
        encode(
            ["(uint64,uint64,uint64,uint64,(address,uint64)[])"], [(40, 30, 20, 10, [(USER, 5)])]
        ),
    )
    supply = lab.vy.token_supply(8)
    _assert_fields(
        supply,
        ["max_supply", "total_supply", "circulating_supply", "future_emissions"],
        (40, 30, 20, 10),
    )
    _assert_fields(supply.non_circulating_user_balances[0], ["user", "balance"], (USER, 5))
    assert normalized(supply) == normalized(lab.sol.token_supply(8))
