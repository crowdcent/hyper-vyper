"""Read-side parity with the pinned PrecompileLib, HLConstants and CoreWriterLib.

Covers spot market lookup, normalized prices, borrow/lend readers, TokenRegistry
lookups, is_usdc and to_milliseconds. Each test compares with the Solidity
reference where upstream has the function, and checks every precompile call.
"""

import boa
import pytest
from eth_abi import encode
from eth_utils import keccak

from hyper_vyper.testing import _precompiles as pc
from tests.support import (
    PERP_ABI,
    REGISTRY,
    SPOT_ABI,
    STHYPE_EVM,
    U64,
    USDC,
    USER,
    VAULT,
    WALLET,
    live_reply,
    normalized,
    token_payload,
)

NOT_FOUND = keccak(text="TokenNotFound(address)")[:4]


def u64(value):
    return encode(["uint64"], [value])


def spot(base, quote, name="@1"):
    return encode([SPOT_ABI], [(name, (base, quote))])


def serve_spots(lab, markets):
    lab.read(pc.SPOT_INFO, {u64(index): spot(*pair) for index, pair in markets.items()})


def live_hype_markets(lab):
    lab.read(pc.TOKEN_INFO, live_reply("token_info_hype", 999))
    names = {107: "usdc", 207: "207", 232: "232", 255: "255"}
    lab.read(
        pc.SPOT_INFO, {u64(i): live_reply(f"spot_info_hype_{n}", 999) for i, n in names.items()}
    )


# --- spot_index_for_token: always the USDC market ---


def test_single_market_not_quoted_in_usdc_reverts_unlike_upstream(lab):
    # Mainnet STHYPE (token 119) has one market, 297, quoted in token 360.
    # Upstream returns that market; this library requires a USDC quote.
    lab.read(pc.TOKEN_INFO, live_reply("token_info_sthype", 999))
    lab.read(pc.SPOT_INFO, live_reply("spot_info_sthype", 999))
    with boa.reverts("No USDC spot market"):
        lab.vy.spot_index_for_token(119)
    assert lab.reads == [(pc.TOKEN_INFO, u64(119)), (pc.SPOT_INFO, u64(297))]
    assert lab.sol.spot_index_for_token(119) == 297


def test_live_hype_finds_the_usdc_market(lab):
    live_hype_markets(lab)
    assert lab.vy.spot_index_for_token(150) == 107
    assert lab.reads == [(pc.TOKEN_INFO, u64(150)), (pc.SPOT_INFO, u64(107))]
    assert lab.sol.spot_index_for_token(150) == 107


def test_usdc_market_listed_last(lab):
    lab.read(pc.TOKEN_INFO, token_payload(spots=(207, 232, 255, 107)))
    serve_spots(lab, {207: (150, 268), 232: (150, 360), 255: (150, 235), 107: (150, 0)})
    assert lab.vy.spot_index_for_token(150) == lab.sol.spot_index_for_token(150) == 107
    reads = [(pc.SPOT_INFO, u64(i)) for i in (207, 232, 255, 107)]
    assert lab.reads == [(pc.TOKEN_INFO, u64(150)), *reads] * 2


def test_single_usdc_market_agrees_with_upstream(lab):
    lab.read(pc.TOKEN_INFO, token_payload(spots=(9,)))
    serve_spots(lab, {9: (5, 0)})
    assert lab.vy.spot_index_for_token(5) == lab.sol.spot_index_for_token(5) == 9
    # This library confirms the quote token; upstream skips the read.
    assert lab.reads == [(pc.TOKEN_INFO, u64(5)), (pc.SPOT_INFO, u64(9)), (pc.TOKEN_INFO, u64(5))]


def test_first_of_two_usdc_markets_wins(lab):
    lab.read(pc.TOKEN_INFO, token_payload(spots=(4, 8, 6)))
    serve_spots(lab, {4: (5, 7), 8: (5, 0), 6: (5, 0)})
    assert lab.vy.spot_index_for_token(5) == lab.sol.spot_index_for_token(5) == 8


@pytest.mark.parametrize("spots", [(), (4, 8)])
def test_no_usdc_market_reverts_both(lab, spots):
    lab.read(pc.TOKEN_INFO, token_payload(spots=spots))
    serve_spots(lab, {4: (5, 7), 8: (5, 360)})
    with boa.reverts("No USDC spot market"):
        lab.vy.spot_index_for_token(5)
    with boa.reverts():
        lab.sol.spot_index_for_token(5)


def test_market_whose_base_is_usdc_is_not_a_usdc_quote(lab):
    # Only the quote (tokens[1]) counts. A market with USDC as base is skipped.
    lab.read(pc.TOKEN_INFO, token_payload(spots=(4, 8)))
    serve_spots(lab, {4: (0, 5), 8: (5, 0)})
    assert lab.vy.spot_index_for_token(5) == lab.sol.spot_index_for_token(5) == 8


def test_failed_spot_info_read_reverts(lab):
    lab.read(pc.TOKEN_INFO, token_payload(spots=(4,)))
    lab.read(pc.SPOT_INFO, fail=True)
    with boa.reverts():
        lab.vy.spot_index_for_token(5)


def test_spot_index_input_is_full_uint64(lab):
    lab.read(pc.TOKEN_INFO, token_payload(spots=(U64,)))
    serve_spots(lab, {U64: (U64, 0)})
    assert lab.vy.spot_index_for_token(U64) == U64
    assert lab.reads == [(pc.TOKEN_INFO, u64(U64)), (pc.SPOT_INFO, u64(U64))]


# --- spot_index_for_pair ---


@pytest.mark.parametrize("quote,expected", [(0, 107), (360, 232), (268, 207), (235, 255)])
def test_live_hype_pairs(lab, quote, expected):
    live_hype_markets(lab)
    assert lab.vy.spot_index_for_pair(150, quote) == expected
    assert lab.sol.spot_index_for_pair(150, quote) == expected
    assert lab.reads[0] == (pc.TOKEN_INFO, u64(150))


def test_live_sthype_pair(lab):
    lab.read(pc.TOKEN_INFO, live_reply("token_info_sthype", 999))
    lab.read(pc.SPOT_INFO, live_reply("spot_info_sthype", 999))
    assert lab.vy.spot_index_for_pair(119, 360) == lab.sol.spot_index_for_pair(119, 360) == 297
    assert lab.reads == [(pc.TOKEN_INFO, u64(119)), (pc.SPOT_INFO, u64(297))] * 2
    with boa.reverts("No spot market for pair"):
        lab.vy.spot_index_for_pair(119, 0)
    with boa.reverts():
        lab.sol.spot_index_for_pair(119, 0)


@pytest.mark.parametrize("spots", [(), (4,)])
def test_pair_missing_reverts_both(lab, spots):
    # One market with a different quote is not returned, unlike upstream getSpotIndex(token).
    lab.read(pc.TOKEN_INFO, token_payload(spots=spots))
    serve_spots(lab, {4: (5, 7)})
    with boa.reverts("No spot market for pair"):
        lab.vy.spot_index_for_pair(5, 8)
    with boa.reverts():
        lab.sol.spot_index_for_pair(5, 8)


def test_pair_quote_is_full_uint64(lab):
    lab.read(pc.TOKEN_INFO, token_payload(spots=(3, 4)))
    serve_spots(lab, {3: (5, U64 - 1), 4: (5, U64)})
    assert lab.vy.spot_index_for_pair(5, U64) == lab.sol.spot_index_for_pair(5, U64) == 4
    assert lab.vy.spot_index_for_pair(5, U64 - 1) == lab.sol.spot_index_for_pair(5, U64 - 1) == 3


# --- normalized prices ---


@pytest.mark.parametrize(
    "px,sz",
    [(0, 0), (1, 0), (U64, 0), (4_400, 2), (U64, 2), (U64, 57), (1, 77), (U64, 58), (2, 77)],
)
def test_normalized_spot_px(lab, px, sz):
    # Spot prices carry 8 - szDecimals decimals; normalized prices carry 8.
    lab.read(pc.SPOT_INFO, spot(150, 360, "@232"))
    lab.read(pc.TOKEN_INFO, token_payload(sz=sz, spots=(232,)))
    lab.read(pc.SPOT_PX, u64(px))
    expected = px * 10**sz
    if expected >= 2**256:
        for contract in (lab.vy, lab.sol):
            with boa.reverts():
                contract.normalized_spot_px(232)
        return
    assert lab.vy.normalized_spot_px(232) == lab.sol.normalized_spot_px(232) == expected
    # The base token (tokens[0]) sets the decimals, never the quote token.
    sequence = [(pc.SPOT_INFO, u64(232)), (pc.TOKEN_INFO, u64(150)), (pc.SPOT_PX, u64(232))]
    assert lab.reads == sequence * 2


@pytest.mark.parametrize("sz", [78, 255])
def test_normalized_spot_px_exponent_overflow_reverts_both(lab, sz):
    lab.read(pc.SPOT_INFO, spot(150, 0))
    lab.read(pc.TOKEN_INFO, token_payload(sz=sz))
    lab.read(pc.SPOT_PX, u64(0))
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.normalized_spot_px(107)


@pytest.mark.parametrize("kind,suffix", [("mark", pc.MARK_PX), ("oracle", pc.ORACLE_PX)])
@pytest.mark.parametrize(
    "px,sz", [(0, 0), (U64, 0), (65_432, 5), (U64, 5), (U64, 57), (1, 77), (U64, 58), (1, 78)]
)
def test_normalized_perp_px(lab, kind, suffix, px, sz):
    # Perp prices carry 6 - szDecimals decimals; normalized prices carry 6.
    name = f"normalized_{kind}_px"
    lab.read(pc.PERP_ASSET_INFO, encode([PERP_ABI], [("BTC", 56, sz, 40, False)]))
    lab.read(suffix, u64(px))
    expected = px * 10**sz
    if expected >= 2**256:
        for contract in (lab.vy, lab.sol):
            with boa.reverts():
                getattr(contract, name)(2**32 - 1)
        return
    assert getattr(lab.vy, name)(2**32 - 1) == getattr(lab.sol, name)(2**32 - 1) == expected
    perp = encode(["uint32"], [2**32 - 1])
    assert lab.reads == [(pc.PERP_ASSET_INFO, perp), (suffix, perp)] * 2


def test_normalized_mark_px_uses_live_btc_decimals(lab):
    lab.read(pc.PERP_ASSET_INFO, live_reply("perp_asset_info_btc", 999))
    lab.read(pc.MARK_PX, u64(654_321))  # 65,432.1 USD at 6 - 5 = 1 decimal
    assert lab.vy.normalized_mark_px(0) == lab.sol.normalized_mark_px(0) == 65_432_100_000


def test_normalized_px_never_hides_a_failed_read(lab):
    lab.read(pc.PERP_ASSET_INFO, encode([PERP_ABI], [("BTC", 56, 5, 40, False)]))
    lab.read(pc.ORACLE_PX, fail=True)
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.normalized_oracle_px(0)


# --- borrow / lend ---

RESERVE_FIELDS = [
    "borrow_yearly_rate_bps",
    "supply_yearly_rate_bps",
    "balance",
    "utilization_bps",
    "oracle_px",
    "ltv_bps",
    "total_supplied",
    "total_borrowed",
]


def test_borrow_lend_user_state_fields(lab):
    lab.read(
        pc.BORROW_LEND_USER_STATE,
        encode(["((uint64,uint64),(uint64,uint64))"], [((11, 22), (33, U64))]),
    )
    result = lab.vy.borrow_lend_user_state(USER, U64)
    assert (result.borrow.basis, result.borrow.value) == (11, 22)
    assert (result.supply.basis, result.supply.value) == (33, U64)
    assert normalized(result) == normalized(lab.sol.borrow_lend_user_state(USER, U64))
    assert (
        lab.reads == [(pc.BORROW_LEND_USER_STATE, encode(["address", "uint64"], [USER, U64]))] * 2
    )
    assert lab.calls[0][2] == 75_000


def test_borrow_lend_reserve_state_fields(lab):
    values = [500, 332, 7, 7_398, 81_058_000, 6_500, U64, 41]
    lab.read(pc.BORROW_LEND_RESERVE_STATE, encode(["uint64"] * 8, values))
    result = lab.vy.borrow_lend_reserve_state(150)
    for name, value in zip(RESERVE_FIELDS, values, strict=True):
        assert getattr(result, name) == value, name
    assert normalized(result) == normalized(lab.sol.borrow_lend_reserve_state(150))
    assert lab.reads == [(pc.BORROW_LEND_RESERVE_STATE, u64(150))] * 2


def test_borrow_lend_reserve_state_mainnet_reply(lab):
    # Values copied from one mainnet read of the HYPE (150) reserve: a flat 8-word
    # static tuple. The live values change every block, so live_replies.json does
    # not keep this reply.
    reply = encode(
        ["uint64"] * 8, [500, 0, 1400047440238045, 0, 81058000, 6500, 1400047440238045, 0]
    )
    lab.read(pc.BORROW_LEND_RESERVE_STATE, reply)
    result = lab.vy.borrow_lend_reserve_state(150)
    assert (result.ltv_bps, result.oracle_px, result.utilization_bps) == (6_500, 81_058_000, 0)
    assert result.balance == result.total_supplied


# --- token_index (TokenRegistry) ---

REGISTRY_MOCK = """
index_of: HashMap[address, uint256]
known: HashMap[address, bool]

@external
def set(token: address, index: uint256):
    self.index_of[token] = index
    self.known[token] = True

@external
@view
def getTokenIndex(evmContract: address) -> uint256:
    if not self.known[evmContract]:
        raw_revert(concat(method_id("TokenNotFound(address)"), abi_encode(evmContract)))
    return self.index_of[evmContract]
"""


@pytest.fixture
def registry(lab):
    # Mirrors the mainnet registry: the CoreDepositWallet is USDC (0), the ERC-20 is not listed.
    mock = boa.loads(REGISTRY_MOCK, override_address=REGISTRY)
    mock.set(WALLET[999], 0)
    mock.set(STHYPE_EVM, 119)
    return mock


@pytest.mark.parametrize("chain_id", [999, 998])
def test_usdc_erc20_is_index_zero_without_the_registry(lab, chain_id):
    # No registry is deployed here, so any registry call would revert.
    boa.env.evm.patch.chain_id = chain_id
    assert lab.vy.token_index(USDC[chain_id]) == lab.sol.token_index(USDC[chain_id]) == 0


def test_registered_token(lab, registry):
    lab.read(pc.TOKEN_INFO, live_reply("token_info_sthype", 999))
    assert lab.vy.token_index(STHYPE_EVM) == lab.sol.token_index(STHYPE_EVM) == 119
    # The library checks the registry answer against the token's own metadata.
    assert lab.calls[-1][:2] == (pc.TOKEN_INFO, encode(["uint64"], [119]))


def test_deposit_wallet_is_not_reported_as_usdc_unlike_upstream(lab, registry):
    # The registry maps the CoreDepositWallet to 0 because Core links USDC to it.
    # It is not a token, so the library rejects it. The Solidity library returns 0.
    lab.read(pc.TOKEN_INFO, live_reply("token_info_usdc", 999))
    with boa.reverts("Registry mismatch"):
        lab.vy.token_index(WALLET[999])
    assert lab.sol.token_index(WALLET[999]) == 0


def test_registry_answer_must_match_core_metadata(lab, registry):
    # Anyone can write to the registry. A mapping to a token with a different
    # linked contract is rejected. The Solidity library returns it.
    registry.set(USER, 5)
    lab.read(pc.TOKEN_INFO, token_payload(evm=VAULT))
    with boa.reverts("Registry mismatch"):
        lab.vy.token_index(USER)
    assert lab.sol.token_index(USER) == 5


def test_unregistered_token_reverts_with_registry_error(lab, registry):
    # The registry's TokenNotFound(address) error reaches the caller unchanged.
    data = keccak(text="token_index(address)")[:4] + encode(["address"], [VAULT])
    for contract in (lab.vy, lab.sol):
        computation = boa.env.execute_code(to_address=contract.address, data=data)
        assert computation.is_error
        assert computation.output == NOT_FOUND + encode(["address"], [VAULT])


def test_registry_index_bounds(lab, registry):
    lab.read(pc.TOKEN_INFO, token_payload(evm=USER))
    registry.set(USER, 2**32 - 1)
    assert lab.vy.token_index(USER) == lab.sol.token_index(USER) == 2**32 - 1
    registry.set(USER, 2**32)
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.token_index(USER)


def test_missing_registry_reverts(lab):
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.token_index(STHYPE_EVM)


def test_other_network_usdc_is_not_special(lab, registry):
    # On testnet the mainnet USDC address is an ordinary (here unregistered) address.
    boa.env.evm.patch.chain_id = 998
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.token_index(USDC[999])


def test_unsupported_chain_reverts_unlike_upstream(lab, registry):
    # Upstream treats every chain except 998 as mainnet.
    boa.env.evm.patch.chain_id = 1
    with boa.reverts("Unsupported chain"):
        lab.vy.token_index(STHYPE_EVM)
    assert lab.sol.token_index(USDC[999]) == 0


# --- is_usdc and to_milliseconds ---


@pytest.mark.parametrize("token,expected", [(0, True), (1, False), (150, False), (U64, False)])
def test_is_usdc(lab, token, expected):
    assert lab.vy.is_usdc(token) == lab.sol.is_usdc(token) == expected


@pytest.mark.parametrize("seconds", [0, 1, 1_700_000_000, U64 // 1000])
def test_to_milliseconds(lab, seconds):
    assert lab.vy.to_milliseconds(seconds) == lab.sol.to_milliseconds(seconds) == seconds * 1000


def test_to_milliseconds_overflow_reverts_both(lab):
    for contract in (lab.vy, lab.sol):
        with boa.reverts():
            contract.to_milliseconds(U64 // 1000 + 1)


@pytest.mark.parametrize(
    "chain_id,token,expected",
    [(999, 150, True), (999, 1105, False), (998, 1105, True), (998, 150, False)],
)
def test_is_hype_is_per_chain(lab, chain_id, token, expected):
    boa.env.evm.patch.chain_id = chain_id
    assert lab.vy.is_hype(token) is expected


def test_checked_token_info_rejects_a_large_index(lab):
    with boa.reverts("Token index too large"):
        lab.vy.checked_token_info(2**32)


def test_evm_to_wei_with_info_matches_evm_to_wei(lab):
    lab.read(pc.TOKEN_INFO, token_payload(extra=10))
    assert lab.vy.evm_to_wei_with_info(5, 10**12) == lab.vy.evm_to_wei(5, 10**12) == 100
