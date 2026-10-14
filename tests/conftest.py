import hashlib
import json
from pathlib import Path

import boa
import pytest
from boa.contracts.abi.abi_contract import ABIContractFactory
from boa.interpret import set_search_paths

from hyper_vyper.testing import CoreSim, Policy, _precompiles
from hyper_vyper.testing import _precompiles as pc
from tests.support import (
    CORE_WRITER,
    FAILING_TOKEN,
    RECORDER,
    RECORDING_WALLET,
    START_BALANCE,
    USDC,
    WALLET,
    Lab,
    live_reply,
)

set_search_paths([str(Path(__file__).resolve().parents[1] / "src")])


EXPOSER_SOURCE = """
# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
# Exposes the library's internal functions as external for testing.
from hyper_vyper import constants
from hyper_vyper import precompiles
from hyper_vyper import core_writer
from hyper_vyper import conversions
from hyper_vyper import bridge


# --- precompiles ---

@external
@view
def l1_block_number() -> uint64:
    return precompiles.l1_block_number()

@external
@view
def mark_px(perp_index: uint32) -> uint64:
    return precompiles.mark_px(perp_index)

@external
@view
def oracle_px(perp_index: uint32) -> uint64:
    return precompiles.oracle_px(perp_index)

@external
@view
def spot_px(spot_index: uint64) -> uint64:
    return precompiles.spot_px(spot_index)

@external
@view
def bbo(asset: uint64) -> precompiles.Bbo:
    return precompiles.bbo(asset)

@external
@view
def spot_balance(user: address, token: uint64) -> precompiles.SpotBalance:
    return precompiles.spot_balance(user, token)

@external
@view
def position(user: address, perp_index: uint32) -> precompiles.Position:
    return precompiles.position(user, perp_index)

@external
@view
def withdrawable(user: address) -> uint64:
    return precompiles.withdrawable(user)

@external
@view
def account_margin_summary(perp_dex_index: uint32, user: address) -> precompiles.AccountMarginSummary:
    return precompiles.account_margin_summary(perp_dex_index, user)

@external
@view
def user_vault_equity(user: address, vault: address) -> precompiles.UserVaultEquity:
    return precompiles.user_vault_equity(user, vault)

@external
@view
def delegator_summary(user: address) -> precompiles.DelegatorSummary:
    return precompiles.delegator_summary(user)

@external
@view
def token_info(token: uint64) -> precompiles.TokenInfo:
    return precompiles.token_info(token)

@external
@view
def spot_info(spot_index: uint64) -> precompiles.SpotInfo:
    return precompiles.spot_info(spot_index)

@external
@view
def perp_asset_info(perp_index: uint32) -> precompiles.PerpAssetInfo:
    return precompiles.perp_asset_info(perp_index)

@external
@view
def token_supply(token: uint64) -> precompiles.TokenSupply:
    return precompiles.token_supply(token)

@external
@view
def spot_index_for_token(token: uint64) -> uint64:
    return precompiles.spot_index_for_token(token)

@external
@view
def spot_index_for_pair(token: uint64, quote: uint64) -> uint64:
    return precompiles.spot_index_for_pair(token, quote)

@external
@view
def normalized_spot_px(spot_index: uint64) -> uint256:
    return precompiles.normalized_spot_px(spot_index)

@external
@view
def normalized_mark_px(perp_index: uint32) -> uint256:
    return precompiles.normalized_mark_px(perp_index)

@external
@view
def normalized_oracle_px(perp_index: uint32) -> uint256:
    return precompiles.normalized_oracle_px(perp_index)

@external
@view
def borrow_lend_user_state(user: address, token: uint64) -> precompiles.BorrowLendUserTokenState:
    return precompiles.borrow_lend_user_state(user, token)

@external
@view
def borrow_lend_reserve_state(token: uint64) -> precompiles.BorrowLendReserveState:
    return precompiles.borrow_lend_reserve_state(token)

@external
@view
def core_user_exists(user: address) -> bool:
    return precompiles.core_user_exists(user)

@external
@view
def delegations(user: address) -> DynArray[precompiles.Delegation, precompiles.MAX_DELEGATIONS]:
    return precompiles.delegations(user)


# --- conversions ---

@external
@view
def hype_token_index() -> uint64:
    return conversions.hype_token_index()

@external
@view
def is_hype(token: uint64) -> bool:
    return conversions.is_hype(token)

@external
@view
def usdc_address() -> address:
    return conversions.usdc_address()

@external
@view
def core_deposit_wallet() -> address:
    return conversions.core_deposit_wallet()

@external
@view
def checked_token_info(token: uint64) -> precompiles.TokenInfo:
    return conversions.checked_token_info(token)

@external
@view
def evm_to_wei_with_info(token: uint64, amount_evm: uint256) -> uint64:
    # The exposer reads the metadata first, as a caller of evm_to_wei_with_info does.
    return conversions.evm_to_wei_with_info(token, conversions.checked_token_info(token), amount_evm)

@external
@view
def system_address(token: uint64) -> address:
    return conversions.system_address(token)

@external
@view
def evm_to_wei(token: uint64, amount_evm: uint256) -> uint64:
    return conversions.evm_to_wei(token, amount_evm)

@external
@view
def wei_to_evm(token: uint64, amount_wei: uint64) -> uint256:
    return conversions.wei_to_evm(token, amount_wei)

@external
@view
def sz_to_wei(token: uint64, sz: uint64) -> uint64:
    return conversions.sz_to_wei(token, sz)

@external
@view
def wei_to_sz(token: uint64, amount_wei: uint64) -> uint64:
    return conversions.wei_to_sz(token, amount_wei)

@external
@pure
def wei_to_perp(amount_wei: uint64) -> uint64:
    return conversions.wei_to_perp(amount_wei)

@external
@pure
def perp_to_wei(perp_amount: uint64) -> uint64:
    return conversions.perp_to_wei(perp_amount)

@external
@pure
def spot_to_asset_id(spot_index: uint64) -> uint32:
    return conversions.spot_to_asset_id(spot_index)

@external
@pure
def asset_to_spot_id(asset: uint64) -> uint64:
    return conversions.asset_to_spot_id(asset)

@external
@view
def token_index(token_address: address) -> uint64:
    return conversions.token_index(token_address)

@external
@pure
def is_usdc(token: uint64) -> bool:
    return conversions.is_usdc(token)

@external
@pure
def to_milliseconds(timestamp: uint64) -> uint64:
    return conversions.to_milliseconds(timestamp)


# --- core_writer ---

@external
def place_limit_order(
    asset: uint32,
    is_buy: bool,
    limit_px: uint64,
    sz: uint64,
    reduce_only: bool,
    tif: uint8,
    cloid: uint128,
):
    core_writer.place_limit_order(asset, is_buy, limit_px, sz, reduce_only, tif, cloid)

@external
def spot_send(to: address, token: uint64, amount_wei: uint64):
    core_writer.spot_send(to, token, amount_wei)

@external
def transfer_usd_class(ntl: uint64, to_perp: bool):
    core_writer.transfer_usd_class(ntl, to_perp)

@external
def vault_transfer(vault: address, is_deposit: bool, usd_amount: uint64):
    core_writer.vault_transfer(vault, is_deposit, usd_amount)

@external
def send_asset(
    destination: address,
    sub_account: address,
    source_dex: uint32,
    destination_dex: uint32,
    token: uint64,
    amount_wei: uint64,
):
    core_writer.send_asset(
        destination, sub_account, source_dex, destination_dex, token, amount_wei
    )

@external
def approve_builder_fee(max_fee_rate: uint64, builder: address):
    core_writer.approve_builder_fee(max_fee_rate, builder)

@external
def cancel_order_by_oid(asset: uint32, order_id: uint64):
    core_writer.cancel_order_by_oid(asset, order_id)

@external
def cancel_order_by_cloid(asset: uint32, cloid: uint128):
    core_writer.cancel_order_by_cloid(asset, cloid)

@external
def staking_deposit(amount_wei: uint64):
    core_writer.staking_deposit(amount_wei)

@external
def staking_withdraw(amount_wei: uint64):
    core_writer.staking_withdraw(amount_wei)

@external
def delegate_token(validator: address, amount_wei: uint64, undelegate: bool):
    core_writer.delegate_token(validator, amount_wei, undelegate)

@external
def finalize_evm_contract(token: uint64, encoded_variant: uint8, create_nonce: uint64):
    core_writer.finalize_evm_contract(token, encoded_variant, create_nonce)

@external
def borrow_lend(operation: uint8, token: uint64, amount_wei: uint64):
    core_writer.borrow_lend(operation, token, amount_wei)

@external
def add_api_wallet(wallet: address, name: String[32]):
    core_writer.add_api_wallet(wallet, name)

@external
def set_abstraction(user: address, mode: uint8):
    core_writer.set_abstraction(user, mode)

@external
def bridge_usdc_to_core(amount: uint256, dex: uint32):
    bridge.bridge_usdc_to_core(amount, dex)

@external
def bridge_usdc_to_core_for(recipient: address, amount: uint256, dex: uint32):
    bridge.bridge_usdc_to_core_for(recipient, amount, dex)

@external
def bridge_usdc_to_evm(amount: uint256, dex: uint32):
    bridge.bridge_usdc_to_evm(amount, dex)

@external
@payable
def bridge_hype_to_core(amount: uint256) -> uint64:
    return bridge.bridge_hype_to_core(amount)

@external
def bridge_erc20_to_core(token: uint64, amount: uint256) -> uint64:
    return bridge.bridge_erc20_to_core(token, amount)

@external
@payable
def bridge_to_core(token: uint64, amount: uint256) -> uint64:
    return bridge.bridge_to_core(token, amount)

@external
def bridge_to_evm(token: uint64, amount: uint256, is_evm_amount: bool) -> uint64:
    return bridge.bridge_to_evm(token, amount, is_evm_amount)

"""


@pytest.fixture(scope="session")
def exposer_deployer():
    return boa.loads_partial(EXPOSER_SOURCE, name="Exposer")


@pytest.fixture(scope="session")
def reference_artifact():
    """The compiled Solidity reference, after a check that its sources are unchanged."""
    reference = Path(__file__).parent / "reference"
    artifact = json.loads((reference / "artifact.json").read_text())
    for filename, key in [
        ("Reference.sol", "wrapper_sha256"),
        ("upstream.json", "upstream_sha256"),
    ]:
        assert hashlib.sha256((reference / filename).read_bytes()).hexdigest() == artifact[key]
    return artifact


@pytest.fixture
def lab(exposer_deployer, reference_artifact):
    boa.reset_env()
    boa.env.evm.patch.chain_id = 999
    address, _ = boa.env.deploy_code(bytecode=bytes.fromhex(reference_artifact["bytecode"]))
    sol = ABIContractFactory.from_abi_dict(reference_artifact["abi"], name="SolidityReference")
    writer = boa.loads_partial(RECORDER).deploy(override_address=CORE_WRITER)
    yield Lab(exposer_deployer.deploy(), sol.at(address), writer)
    _precompiles.deregister()


@pytest.fixture
def bridge_lab(lab, request):
    """The lab with mock USDC, a mock deposit wallet and real USDC metadata on chain 999.
    Parametrize it indirectly with a chain ID to use the addresses of another chain."""
    chain_id = getattr(request, "param", 999)
    boa.env.evm.patch.chain_id = chain_id
    token = boa.loads_partial(FAILING_TOKEN).deploy(override_address=USDC[chain_id])
    wallet = boa.loads_partial(RECORDING_WALLET).deploy(
        token.address, override_address=WALLET[chain_id]
    )
    lab.read(pc.TOKEN_INFO, live_reply("token_info_usdc", chain_id))
    for contract in (lab.vy, lab.sol):
        token.mint(contract.address, START_BALANCE)
    return lab, token, wallet


@pytest.fixture
def make_sim():
    """make_sim(chain_id, **policy_fields) installs a CoreSim on a fresh environment.
    Every simulator it made is closed after the test."""
    made = []

    def make(chain_id=999, **policy_fields):
        boa.reset_env()
        made.append(CoreSim.install(chain_id, Policy(**policy_fields)))
        return made[-1]

    yield make
    for sim in made:
        sim.close()
