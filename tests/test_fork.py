"""
Fork tests against live HyperEVM mainnet.

Verifies the Vyper wrappers correctly call and decode real precompile responses.
Requires network access; run with: pytest tests/test_fork.py -m fork

HyperEVM's read precompiles are node logic, not on-chain code, so titanoboa's
local copy of the chain has none of them. forward_precompiles answers each read
from the live node, so the Vyper encode and decode paths run against real
HyperCore replies.
"""

import boa
import pytest
from eth_abi import encode
from hyperliquid.info import Info
from hyperliquid.utils.constants import MAINNET_API_URL

from hyper_vyper.testing import _precompiles as pc
from hyper_vyper.testing import forward_precompiles
from hyper_vyper.testing.live import MAINNET_RPC, TESTNET_RPC, RetryingRPC
from hyper_vyper.testing.sim import LIVE_REPLIES
from tests.support import SPOT_DEX, STHYPE_EVM, USDC, WALLET, ZERO, token_info

RPC = {999: RetryingRPC(MAINNET_RPC), 998: RetryingRPC(TESTNET_RPC)}

pytestmark = pytest.mark.fork


def _eth_call(chain_id: int, suffix: int, data: bytes) -> bytes:
    call = {"to": pc.address(suffix), "data": "0x" + data.hex()}
    return bytes.fromhex(RPC[chain_id].fetch("eth_call", [call, "latest"])[2:])


@pytest.fixture(scope="module")
def fork():
    with forward_precompiles(RPC[999]):
        boa.fork(MAINNET_RPC)
        yield
    boa.reset_env()


@pytest.fixture(scope="module")
def hl(fork, exposer_deployer):
    return exposer_deployer.deploy()


def test_l1_block_number_moves_forward(hl):
    first = hl.l1_block_number()
    assert first > 10**8
    assert hl.l1_block_number() >= first


@pytest.fixture(scope="module")
def info():
    """Hyperliquid's info API: an independent source to compare precompile reads with."""
    return Info(MAINNET_API_URL, skip_ws=True)


@pytest.fixture(scope="module")
def perp_meta(info):
    meta, contexts = info.meta_and_asset_ctxs()
    return meta["universe"], contexts


def _near(raw: int, decimals: int, reference: str, tolerance: float = 0.02) -> bool:
    return abs(raw / 10**decimals - float(reference)) <= tolerance * float(reference)


def test_btc_prices_match_info_api(hl, perp_meta):
    universe, contexts = perp_meta
    decimals = 6 - universe[0]["szDecimals"]  # perp prices: 10**(6 - szDecimals)
    assert _near(hl.mark_px(0), decimals, contexts[0]["markPx"])
    assert _near(hl.oracle_px(0), decimals, contexts[0]["oraclePx"])
    bid, ask = hl.bbo(0)
    assert bid <= ask
    assert _near(bid, decimals, contexts[0]["midPx"])


def test_spot_price_matches_info_api(hl, info):
    # HYPE/USDC is spot market 107. Spot prices: 10**(8 - base szDecimals).
    meta, contexts = info.spot_meta_and_asset_ctxs()
    context = next(c for c in contexts if c["coin"] == "@107")
    hype = next(t for t in meta["tokens"] if t["index"] == 150)
    assert _near(hl.spot_px(107), 8 - hype["szDecimals"], context["markPx"])


def test_perp_asset_info_matches_info_api(hl, perp_meta):
    universe, _ = perp_meta
    info = hl.perp_asset_info(0)
    assert info.coin == universe[0]["name"] == "BTC"
    assert info.sz_decimals == universe[0]["szDecimals"]
    assert info.max_leverage == universe[0]["maxLeverage"]
    assert info.margin_table_id == universe[0]["marginTableId"]


def test_token_info_usdc(hl):
    info = hl.token_info(0)
    assert info.name == "USDC"
    assert info.wei_decimals == 8


def test_token_info_hype(hl):
    # HYPE is the native gas token, so token_info has no EVM contract and no extra
    # decimals for it. conversions uses 10 extra EVM decimals (18 EVM, 8 Core) instead.
    info = hl.token_info(150)
    assert info.name == "HYPE"
    assert info.wei_decimals == 8
    assert info.evm_contract == ZERO
    assert info.evm_extra_wei_decimals == 0


def test_spot_info(hl):
    info = hl.spot_info(107)  # HYPE/USDC market
    assert info.tokens[1] == 0  # quoted in USDC


def test_spot_index_for_token_hype(hl):
    spot_index = hl.spot_index_for_token(150)
    assert spot_index == 107


def test_hype_system_address(hl):
    assert hl.system_address(150) == "0x2222222222222222222222222222222222222222"


def test_evm_to_wei_hype_live(hl):
    # 1 HYPE = 10**18 EVM wei = 10**8 Core wei
    assert hl.evm_to_wei(150, 10**18) == 10**8


def test_bridge_accepts_live_usdc_metadata(hl):
    # Runs the USDC checks against real Core metadata, then submits to the real
    # CoreWriter code on the fork. Nothing reaches the live chain.
    hl.bridge_usdc_to_evm(1_000_000, SPOT_DEX)


@pytest.mark.parametrize("chain_id", [999, 998])
def test_live_usdc_links_to_deposit_wallet(chain_id):
    reply = _eth_call(chain_id, pc.TOKEN_INFO, encode(["uint64"], [0]))
    info = token_info(reply)
    assert info.evm_contract.lower() == WALLET[chain_id].lower()
    assert (info.wei_decimals, info.evm_extra_wei_decimals) == (8, -2)


@pytest.mark.parametrize("entry", LIVE_REPLIES, ids=lambda e: f"{e['name']}-{e['chain_id']}")
def test_recorded_replies_still_match_chain(entry):
    # The tests use these recorded replies. If this fails, record them again.
    suffix = int(entry["precompile"], 16)
    live = _eth_call(entry["chain_id"], suffix, bytes.fromhex(entry["input"][2:]))
    recorded = bytes.fromhex(entry["reply"][2:])
    if suffix == pc.TOKEN_INFO:
        # A token can list new spot markets. The recorded ones must still come first.
        live, recorded = token_info(live), token_info(recorded)
        assert live.spots[: len(recorded.spots)] == recorded.spots
        live, recorded = live._replace(spots=()), recorded._replace(spots=())
    assert live == recorded


def test_spot_index_for_token_requires_usdc_quote_live(hl):
    # STHYPE (119) has one market, 297, quoted in USDH (360), not USDC.
    with boa.reverts("No USDC spot market"):
        hl.spot_index_for_token(119)
    assert hl.spot_index_for_pair(119, 360) == 297
    assert hl.spot_index_for_pair(150, 0) == 107


@pytest.mark.parametrize(
    "token,index",
    [
        (USDC[999], 0),  # the USDC ERC-20 is not in the registry
        (STHYPE_EVM, 119),
    ],
)
def test_token_index_live_registry(hl, token, index):
    assert hl.token_index(token) == index


def test_token_index_rejects_the_deposit_wallet_live(hl):
    # The live registry maps the CoreDepositWallet to 0 (USDC). It is not a token.
    with boa.reverts("Registry mismatch"):
        hl.token_index(WALLET[999])


def test_token_index_unregistered_live(hl):
    with boa.reverts():
        hl.token_index("0x" + "12" * 20)


def test_normalized_prices_match_info_api(hl, info, perp_meta):
    _, contexts = perp_meta
    assert _near(hl.normalized_mark_px(0), 6, contexts[0]["markPx"])
    assert _near(hl.normalized_oracle_px(0), 6, contexts[0]["oraclePx"])
    _, spot_contexts = info.spot_meta_and_asset_ctxs()
    context = next(c for c in spot_contexts if c["coin"] == "@107")
    assert _near(hl.normalized_spot_px(107), 8, context["markPx"])


def test_borrow_lend_reserve_state_live(hl):
    reserve = hl.borrow_lend_reserve_state(0)  # USDC
    assert reserve.utilization_bps <= 10_000
    assert reserve.total_borrowed <= reserve.total_supplied
    assert reserve.supply_yearly_rate_bps <= reserve.borrow_yearly_rate_bps
