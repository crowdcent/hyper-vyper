"""Check every CoreWriter action byte for byte.

The expected layout comes from the action table in the Hyperliquid docs
(for-developers/hyperevm/interacting-with-hypercore), not from constants.vy.
Each argument has a distinct value, so a swapped or dropped argument fails.
"""

from pathlib import Path

import boa
import pytest
from eth_abi import encode
from vyper import ast as vy_ast

from tests.support import OTHER, SPOT_DEX, U64, USER, VALIDATOR, VAULT, ZERO

# (Vyper function, documented action ID, documented argument types, arguments)
ACTIONS = [
    (
        "place_limit_order",
        1,
        ["uint32", "bool", "uint64", "uint64", "bool", "uint8", "uint128"],
        (7, True, 3_000_000_000, 250_000_000, False, 3, 2**100 + 5),
    ),
    ("vault_transfer", 2, ["address", "bool", "uint64"], (VAULT, True, 9_000_000)),
    ("delegate_token", 3, ["address", "uint64", "bool"], (VALIDATOR, 123, True)),
    ("staking_deposit", 4, ["uint64"], (456,)),
    ("staking_withdraw", 5, ["uint64"], (789,)),
    ("spot_send", 6, ["address", "uint64", "uint64"], (USER, 42, U64)),
    ("transfer_usd_class", 7, ["uint64", "bool"], (5_000_000, True)),
    ("finalize_evm_contract", 8, ["uint64", "uint8", "uint64"], (11, 2, 33)),
    ("add_api_wallet", 9, ["address", "string"], (USER, "agent-1")),
    ("cancel_order_by_oid", 10, ["uint32", "uint64"], (7, 98_765)),
    ("cancel_order_by_cloid", 11, ["uint32", "uint128"], (7, 2**127 + 1)),
    ("approve_builder_fee", 12, ["uint64", "address"], (10, OTHER)),
    (
        "send_asset",
        13,
        ["address", "address", "uint32", "uint32", "uint64", "uint64"],
        (USER, VAULT, 1, SPOT_DEX, 3, 4),
    ),
    ("borrow_lend", 15, ["uint8", "uint64", "uint64"], (1, 7, 99)),
    ("set_abstraction", 16, ["address", "uint8"], (USER, 2)),
    # Edge values: largest amounts, empty and longest names, every abstraction mode.
    (
        "send_asset",
        13,
        ["address", "address", "uint32", "uint32", "uint64", "uint64"],
        (USER, ZERO, 0, SPOT_DEX, 0, U64),
    ),
    ("add_api_wallet", 9, ["address", "string"], (USER, "")),
    ("add_api_wallet", 9, ["address", "string"], (USER, "x" * 32)),
    ("set_abstraction", 16, ["address", "uint8"], (USER, 1)),
    ("set_abstraction", 16, ["address", "uint8"], (USER, 3)),
    ("vault_transfer", 2, ["address", "bool", "uint64"], (VAULT, True, U64)),
]


@pytest.mark.parametrize(
    "name,action_id,types,args", ACTIONS, ids=[f"{a[0]}-{i}" for i, a in enumerate(ACTIONS)]
)
def test_action_matches_documented_layout_and_reference(lab, name, action_id, types, args):
    expected = bytes([1]) + action_id.to_bytes(3, "big") + encode(types, args)
    getattr(lab.vy, name)(*args)
    assert lab.writer.last_data() == expected
    getattr(lab.sol, name)(*args)
    assert lab.writer.last_data() == expected
    assert lab.writer.call_count() == 2


def test_every_writer_function_is_covered():
    # A new action in core_writer.vy must get a row in ACTIONS.
    source = (Path(__file__).parents[1] / "src" / "hyper_vyper" / "core_writer.vy").read_text()
    tree = vy_ast.parse_to_ast(source)
    public = {
        node.name
        for node in tree.body
        if isinstance(node, vy_ast.FunctionDef) and not node.name.startswith("_")
    }
    assert public == {a[0] for a in ACTIONS}


def test_spot_send_to_self_reverts_before_the_action(lab):
    # Core always rejects a send to the sender, so the library refuses it on EVM.
    with boa.reverts("Self transfer"):
        lab.vy.spot_send(lab.vy.address, 150, 1)
    assert lab.writer.call_count() == 0
