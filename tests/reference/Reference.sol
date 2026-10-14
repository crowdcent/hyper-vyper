// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

// Exposes the unmodified pinned upstream library. Do not duplicate its algorithms.
import {CoreWriterLib as W} from "src/CoreWriterLib.sol";
import {PrecompileLib as P} from "src/PrecompileLib.sol";
import {HLConversions as C} from "src/common/HLConversions.sol";
import {HLConstants as K} from "src/common/HLConstants.sol";

contract Reference {
    function bbo(uint64 asset) external view returns (P.Bbo memory) { return P.bbo(asset); }
    function delegator_summary(address user) external view returns (P.DelegatorSummary memory) { return P.delegatorSummary(user); }
    function position(address user, uint32 perp) external view returns (P.Position memory) { return P.position(user, perp); }
    function spot_balance(address user, uint64 token) external view returns (P.SpotBalance memory) { return P.spotBalance(user, token); }
    function account_margin_summary(uint32 dex, address user) external view returns (P.AccountMarginSummary memory) { return P.accountMarginSummary(dex, user); }
    function withdrawable(address user) external view returns (uint64) { return P.withdrawable(user); }
    function core_user_exists(address user) external view returns (bool) { return P.coreUserExists(user); }
    function token_info(uint64 token) external view returns (P.TokenInfo memory) { return P.tokenInfo(token); }
    function token_supply(uint64 token) external view returns (P.TokenSupply memory) { return P.tokenSupply(token); }
    function user_vault_equity(address user, address vault) external view returns (P.UserVaultEquity memory) { return P.userVaultEquity(user, vault); }
    function delegations(address user) external view returns (P.Delegation[] memory) { return P.delegations(user); }
    function evm_to_wei(uint64 token, uint256 amount) external view returns (uint64) { return C.evmToWei(token, amount); }
    function wei_to_evm(uint64 token, uint64 amount) external view returns (uint256) { return C.weiToEvm(token, amount); }
    function sz_to_wei(uint64 token, uint64 amount) external view returns (uint64) { return C.szToWei(token, amount); }
    function wei_to_sz(uint64 token, uint64 amount) external view returns (uint64) { return C.weiToSz(token, amount); }
    function wei_to_perp(uint64 amount) external pure returns (uint64) { return C.weiToPerp(amount); }
    function perp_to_wei(uint64 amount) external pure returns (uint64) { return C.perpToWei(amount); }
    function spot_to_asset_id(uint64 index) external pure returns (uint32) { return C.spotToAssetId(index); }
    function asset_to_spot_id(uint64 asset) external pure returns (uint64) { return C.assetToSpotId(asset); }
    function system_address(uint64 token) external view returns (address) { return W.getSystemAddress(token); }
    function hype_token_index() external view returns (uint64) { return K.hypeTokenIndex(); }
    function usdc_address() external view returns (address) { return K.usdc(); }
    function core_deposit_wallet() external view returns (address) { return K.coreDepositWallet(); }
    function send_asset(address dest, address sub, uint32 fromDex, uint32 toDex, uint64 token, uint64 amount) external { W.sendAsset(dest, sub, fromDex, toDex, token, amount); }
    function add_api_wallet(address wallet, string memory name) external { W.addApiWallet(wallet, name); }
    function set_abstraction(address user, uint8 mode) external { W.setAbstraction(user, mode); }
    function vault_transfer(address vault, bool deposit, uint64 amount) external { W.vaultTransfer(vault, deposit, amount); }
    function spot_send(address to, uint64 token, uint64 amount) external { W.spotSend(to, token, amount); }
    function bridge_usdc_to_core_for(address recipient, uint256 amount, uint32 dex) external { W.bridgeUsdcToCoreFor(recipient, amount, dex); }
    function bridge_usdc_to_core_spot(uint256 amount) external { W.bridgeToCore(uint64(0), amount); }
    function bridge_usdc_to_evm_spot(uint256 amount) external { W.bridgeToEvm(uint64(0), amount, true); }
    function bridge_to_core(uint64 token, uint256 amount) external payable { W.bridgeToCore(token, amount); }
    function bridge_to_evm(uint64 token, uint256 amount, bool isEvmAmount) external { W.bridgeToEvm(token, amount, isEvmAmount); }
    function mark_px(uint32 perp) external view returns (uint64) { return P.markPx(perp); }
    function oracle_px(uint32 perp) external view returns (uint64) { return P.oraclePx(perp); }
    function spot_px(uint64 spot) external view returns (uint64) { return P.spotPx(spot); }
    function perp_asset_info(uint32 perp) external view returns (P.PerpAssetInfo memory) { return P.perpAssetInfo(perp); }
    function spot_info(uint64 spot) external view returns (P.SpotInfo memory) { return P.spotInfo(spot); }
    function l1_block_number() external view returns (uint64) { return P.l1BlockNumber(); }
    function spot_index_for_token(uint64 token) external view returns (uint64) { return P.getSpotIndex(token); }
    function spot_index_for_pair(uint64 token, uint64 quote) external view returns (uint64) { return P.getSpotIndex(token, quote); }
    function normalized_spot_px(uint64 spot) external view returns (uint256) { return P.normalizedSpotPx(spot); }
    function normalized_mark_px(uint32 perp) external view returns (uint256) { return P.normalizedMarkPx(perp); }
    function normalized_oracle_px(uint32 perp) external view returns (uint256) { return P.normalizedOraclePx(perp); }
    function borrow_lend_user_state(address user, uint64 token) external view returns (P.BorrowLendUserTokenState memory) { return P.borrowLendUserState(user, token); }
    function borrow_lend_reserve_state(uint64 token) external view returns (P.BorrowLendReserveState memory) { return P.borrowLendReserveState(token); }
    function token_index(address token) external view returns (uint64) { return P.getTokenIndex(token); }
    function is_usdc(uint64 token) external pure returns (bool) { return K.isUsdc(token); }
    function to_milliseconds(uint64 timestamp) external pure returns (uint64) { return W.toMilliseconds(timestamp); }
    function place_limit_order(uint32 asset, bool isBuy, uint64 px, uint64 sz, bool reduceOnly, uint8 tif, uint128 cloid) external { W.placeLimitOrder(asset, isBuy, px, sz, reduceOnly, tif, cloid); }
    function cancel_order_by_oid(uint32 asset, uint64 oid) external { W.cancelOrderByOrderId(asset, oid); }
    function cancel_order_by_cloid(uint32 asset, uint128 cloid) external { W.cancelOrderByCloid(asset, cloid); }
    function staking_deposit(uint64 amount) external { W.depositStake(amount); }
    function staking_withdraw(uint64 amount) external { W.withdrawStake(amount); }
    function delegate_token(address validator, uint64 amount, bool undelegate) external { W.delegateToken(validator, amount, undelegate); }
    function transfer_usd_class(uint64 ntl, bool toPerp) external { W.transferUsdClass(ntl, toPerp); }
    function finalize_evm_contract(uint64 token, uint8 variant, uint64 nonce) external { W.finalizeEvmContract(token, variant, nonce); }
    function approve_builder_fee(uint64 rate, address builder) external { W.approveBuilderFee(rate, builder); }
    function borrow_lend(uint8 operation, uint64 token, uint64 amount) external { W.borrowLend(operation, token, amount); }
}
