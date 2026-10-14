# pragma version 0.4.3
# SPDX-License-Identifier: MIT

"""
@title HyperEVM Bridge
@notice Sends transfers of USDC, HYPE and linked ERC-20 tokens between HyperEVM
        and HyperCore. A successful submission does not prove delivery.
@dev All functions are internal. Import the module:

        from hyper_vyper import bridge

        bridge.bridge_usdc_to_core(amount_evm, constants.SPOT_DEX)

     The importing contract must do access control, reentrancy protection,
     reserves, pending-transfer records and checks of the later Core or EVM
     result.

     EVM -> Core routes. The Core account at the address of this contract is the
     recipient:
     - USDC (token 0): approve and deposit through the Circle CoreDepositWallet.
     - HYPE: native value sent to 0x2222...2222.
     - Any other linked token: ERC-20 transfer to its system address 0x20...<index>.

     WARNING: CoreWriter actions from an account that is not activated fail
     silently. HYPE and linked tokens sent to it wait in an escrow that the
     precompiles do not show (core_user_exists is false, spot_balance is 0). A
     Core transfer of 1 USDC or more activates it, the sender pays the 1 USDC
     fee, and Core releases the escrow to spot. A USDC deposit also activates
     it, and Core takes the 1 USDC fee from the deposit. Check
     precompiles.core_user_exists(self) in your contract before you bridge.

     WARNING: the USDC functions do not restrict the DEX index, and the Circle
     CoreDepositWallet accepts any index. A HIP-3 DEX can use collateral that is
     not USDC, and a wrong source DEX makes a return fail silently. Hard-code
     constants.DEFAULT_PERP_DEX or constants.SPOT_DEX, unless you verified the
     other DEX.

     Core -> EVM: a sendAsset action to the system address of the token. The EVM
     credit goes to the address of this contract (HYPE as native value).
"""

from ethereum.ercs import IERC20

from . import constants
from . import conversions
from . import core_writer
from . import precompiles


interface ICoreDepositWallet:
    def deposit(amount: uint256, destinationDex: uint32): nonpayable
    def depositFor(recipient: address, amount: uint256, destinationDex: uint32): nonpayable


# USDC has 6 decimals on EVM and 8 on Core: one EVM unit is 100 Core wei.
USDC_WEI_PER_EVM_UNIT: constant(uint256) = 100


@internal
@view
def _check_usdc_info(info: precompiles.TokenInfo):
    # Core links USDC to Circle's CoreDepositWallet, not to the USDC token itself.
    assert info.evm_contract == conversions.core_deposit_wallet(), "USDC link mismatch"
    assert info.wei_decimals == 8 and info.evm_extra_wei_decimals == -2, "USDC decimals mismatch"


@internal
@view
def _validate_usdc(amount_evm: uint256) -> uint64:
    # Returns the Core amount. Check it before any external write.
    conversions.usdc_address()  # rejects unsupported networks
    self._check_usdc_info(precompiles.token_info(constants.USDC_TOKEN_INDEX))
    amount_wei: uint64 = convert(amount_evm * USDC_WEI_PER_EVM_UNIT, uint64)
    assert amount_wei > 0, "Amount too small"
    return amount_wei


@internal
@pure
def _evm_units_per_core_unit(hype: bool, info: precompiles.TokenInfo) -> uint256:
    # How many EVM units make one Core wei. 1 when Core has as many or more decimals.
    if hype and info.evm_contract == empty(address):
        return 10 ** constants.HYPE_EVM_EXTRA_DECIMALS
    if info.evm_extra_wei_decimals > 0:
        return 10 ** convert(info.evm_extra_wei_decimals, uint256)
    return 1


@internal
@pure
def _core_units_per_evm_unit(info: precompiles.TokenInfo) -> uint256:
    # How many Core wei make one EVM unit. 1 when EVM has as many or more decimals.
    if info.evm_contract != empty(address) and info.evm_extra_wei_decimals < 0:
        return 10 ** convert(-info.evm_extra_wei_decimals, uint256)
    return 1


@internal
def _deposit_usdc(recipient: address, amount_evm: uint256, destination_dex: uint32) -> uint64:
    # recipient empty(address) means the Core account of this contract.
    amount_wei: uint64 = self._validate_usdc(amount_evm)
    token: address = conversions.usdc_address()
    wallet: address = conversions.core_deposit_wallet()
    assert extcall IERC20(token).approve(wallet, amount_evm, default_return_value=True), "USDC approval failed"
    if recipient == empty(address):
        extcall ICoreDepositWallet(wallet).deposit(amount_evm, destination_dex)
    else:
        extcall ICoreDepositWallet(wallet).depositFor(recipient, amount_evm, destination_dex)
    # Do not leave spend authority if a wallet ever consumes less than approved.
    assert extcall IERC20(token).approve(wallet, 0, default_return_value=True), "USDC approval reset failed"
    return amount_wei


@internal
def bridge_usdc_to_core(amount_evm: uint256, destination_dex: uint32):
    """Submit a deposit to the Core account of this contract.
    Use constants.DEFAULT_PERP_DEX (0) for perps or constants.SPOT_DEX (max uint32)
    for spot, and see the DEX warning in the module docstring. A deposit to an
    account that is not activated activates it and pays the 1 USDC fee."""
    self._deposit_usdc(empty(address), amount_evm, destination_dex)


@internal
def bridge_usdc_to_core_for(recipient: address, amount_evm: uint256, destination_dex: uint32):
    """Submit a deposit for a recipient. Never take the recipient from untrusted input.
    See the DEX warning in the module docstring."""
    assert recipient != empty(address), "Zero recipient"
    self._deposit_usdc(recipient, amount_evm, destination_dex)


@internal
def bridge_usdc_to_evm(amount_evm: uint256, source_dex: uint32):
    """Submit a return from the Core account of this contract to its EVM address.
    The amount is in EVM USDC units (6 decimals). The CoreWriter payload uses 8 decimals.
    Use constants.DEFAULT_PERP_DEX (0) or constants.SPOT_DEX (max uint32) as the
    source, and see the DEX warning in the module docstring. A wrong source DEX
    fails silently. A return above the balance or the withdrawable amount fails
    silently. Core charges the gas of the transfer in HYPE from Core spot, or in
    USDC when the account holds no HYPE. Keep a small HYPE balance, so that the
    USDC accounting stays exact. The security page of the docs gives the amounts."""
    amount_wei: uint64 = self._validate_usdc(amount_evm)
    core_writer.send_asset(
        constants.BASE_SYSTEM_ADDRESS,
        empty(address),
        source_dex,
        constants.SPOT_DEX,
        constants.USDC_TOKEN_INDEX,
        amount_wei,
    )


@internal
def bridge_hype_to_core(amount_evm: uint256) -> uint64:
    """Send native HYPE (18 decimals) from this contract's balance to the HYPE
    system address. The returned Core amount has 8 decimals. Core credits the
    spot balance of this contract only if it is activated. Otherwise Core holds
    the HYPE in an escrow (see the module docstring).
    amount_evm must be a multiple of 10**10, because Core would burn a remainder.
    Reverts if the Core amount is 0 or does not fit in uint64, or if the contract
    balance is too low. Forwards all gas, like the Solidity library."""
    conversions.hype_token_index()  # rejects unsupported networks
    # HYPE has 18 decimals on EVM and 8 on Core. Both checks use this one rule.
    unit: uint256 = 10 ** constants.HYPE_EVM_EXTRA_DECIMALS
    assert amount_evm % unit == 0, "Not a whole Core unit"
    amount_wei: uint64 = convert(amount_evm // unit, uint64)
    assert amount_wei > 0, "Amount too small"
    # The system contract only emits Received(sender, value). It has no hooks.
    raw_call(constants.HYPE_SYSTEM_ADDRESS, b"", value=amount_evm)
    return amount_wei


@internal
def bridge_erc20_to_core(token: uint64, amount_evm: uint256) -> uint64:
    """Transfer a linked ERC-20 (not USDC, not HYPE) to its system address.
    Core credits the spot balance of this contract with the returned Core amount,
    but only if the account is activated. Otherwise Core holds the tokens in an
    escrow (see the module docstring).
    amount_evm must be a whole number of Core wei, because Core would burn a
    remainder. Reverts if the token is not linked, if the Core amount is 0 or does
    not fit in uint64, or if the transfer fails or returns false.
    The linked contract is chosen by the token deployer and can run arbitrary
    code, including reentrant calls into the importing contract. For a token that
    takes a fee on transfer, Core can credit less than the returned amount."""
    assert token != constants.USDC_TOKEN_INDEX, "Use the USDC route"
    assert not conversions.is_hype(token), "Use the HYPE route"  # rejects unsupported networks
    info: precompiles.TokenInfo = conversions.checked_token_info(token)
    # Reverts "Token not linked to EVM" for an unlinked token (HYPE is excluded above).
    amount_wei: uint64 = conversions.evm_to_wei_with_info(token, info, amount_evm)
    assert amount_wei > 0, "Amount too small"
    assert amount_evm % self._evm_units_per_core_unit(False, info) == 0, "Not a whole Core unit"
    assert extcall IERC20(info.evm_contract).transfer(
        conversions.system_address(token), amount_evm, default_return_value=True
    ), "Token transfer failed"
    return amount_wei


@internal
def bridge_to_core(token: uint64, amount_evm: uint256) -> uint64:
    """Bridge any supported token EVM -> Core by HyperCore token index and return
    the submitted Core amount. USDC goes to the spot DEX through the
    CoreDepositWallet. HYPE and other linked tokens go to their system addresses.
    Amount is in EVM units. A USDC deposit activates an account that is not
    activated, and Core takes the 1 USDC fee from it. HYPE and linked tokens wait
    in an escrow until activation (see the module docstring)."""
    if token == constants.USDC_TOKEN_INDEX:
        return self._deposit_usdc(empty(address), amount_evm, constants.SPOT_DEX)
    if conversions.is_hype(token):
        return self.bridge_hype_to_core(amount_evm)
    return self.bridge_erc20_to_core(token, amount_evm)


@internal
def bridge_to_evm(token: uint64, amount: uint256, is_evm_amount: bool) -> uint64:
    """Submit a sendAsset from this contract's Core spot balance to the token's
    system address and return the Core amount sent. With is_evm_amount the amount
    is in EVM units, otherwise in Core wei. The amount must convert exactly,
    because a remainder would stay on Core or be lost. Reverts if the token is not
    linked (HYPE excepted), if the Core amount is 0 or does not fit in uint64, or
    if the amount is not a whole unit on both sides.
    HYPE arrives as native value, so a contract receiver needs a payable default.
    Not checked: this contract must have a Core account that holds the amount, and
    the system address must hold enough EVM supply of the token. Core charges the
    transfer gas in HYPE from Core spot. A USDC return without HYPE pays the gas
    in USDC (see bridge_usdc_to_evm). For any other token, keep HYPE on Core
    spot."""
    hype: bool = conversions.is_hype(token)  # rejects unsupported networks
    info: precompiles.TokenInfo = conversions.checked_token_info(token)
    if token == constants.USDC_TOKEN_INDEX:
        self._check_usdc_info(info)
    amount_wei: uint64 = 0
    if is_evm_amount:
        amount_wei = conversions.evm_to_wei_with_info(token, info, amount)
        assert amount % self._evm_units_per_core_unit(hype, info) == 0, "Not a whole Core unit"
    else:
        assert info.evm_contract != empty(address) or hype, "Token not linked to EVM"
        amount_wei = convert(amount, uint64)
        # Core has more decimals than EVM: only whole EVM units can arrive.
        assert amount % self._core_units_per_evm_unit(info) == 0, "Not a whole EVM unit"
    assert amount_wei > 0, "Amount too small"
    core_writer.send_asset(
        conversions.system_address(token),
        empty(address),
        constants.SPOT_DEX,
        constants.SPOT_DEX,
        token,
        amount_wei,
    )
    return amount_wei
