# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
# SPDX-License-Identifier: MIT

"""
@title Tutorial: move USDC between EVM and Core
@notice The owner returns USDC from the Core spot or perp balance of this
        contract to its EVM balance, and deposits EVM USDC back to Core through
        the Circle CoreDepositWallet. Each transfer stays pending until a later
        block shows it at its destination.
@dev Tutorial code, based on examples/usdc_bridge.vy. Nobody has audited it.
     Core charges the gas of each USDC return in HYPE from the spot balance of
     this contract when the contract holds HYPE (about 0.00002 HYPE). Without
     HYPE, Core takes the gas in USDC: from spot (about 0.0009 USDC on testnet),
     or from perp for a perp return when spot has no USDC. A return that Core rejects,
     for example above the balance, fails silently, and the transfer stays
     pending. On testnet, the CoreDepositWallet credits only an address that
     has a Hyperliquid mainnet account, so deposits go to the owner. On mainnet,
     bridge.bridge_usdc_to_core deposits into the contract's own Core account.
"""

from ethereum.ercs import IERC20

from hyper_vyper import bridge
from hyper_vyper import constants
from hyper_vyper import conversions
from hyper_vyper import core_writer
from hyper_vyper import precompiles


struct Pending:
    to_core: bool  # True for a deposit, False for a return
    from_perp: bool  # the source of a return
    amount: uint256  # EVM USDC, 6 decimals
    baseline: uint256  # destination balance at submission: EVM USDC, or the owner's Core spot USDC
    source_baseline: int256  # Core source of a return at submission (spot: 8 decimals, perp: 6)
    evm_block: uint256
    l1_block: uint64


struct Status:
    evm_block: uint256
    core_exists: bool
    spot_usdc: uint64  # Core USDC, 8 decimals
    spot_hype: uint64  # Core HYPE, 8 decimals
    withdrawable: uint64  # perp USD, 6 decimals
    evm_usdc: uint256  # EVM USDC, 6 decimals
    owner_spot_usdc: uint64  # Core USDC of the owner, 8 decimals
    has_pending: bool
    observed: bool


event Submitted:
    to_core: bool
    from_perp: bool
    amount: uint256


event Confirmed:
    to_core: bool
    amount: uint256


event Abandoned:
    to_core: bool
    amount: uint256


# Core handles an action in an L1 block after the EVM block that sent it. After
# this many L1 blocks, a transfer that has not happened will not happen.
PROCESSED_AFTER_L1_BLOCKS: constant(uint64) = 200

OWNER: public(immutable(address))

# One transfer at a time keeps the accounting simple.
pending: public(Pending)
has_pending: public(bool)


@deploy
def __init__():
    OWNER = msg.sender


@internal
@view
def _only_owner():
    assert msg.sender == OWNER, "Only the owner"


@internal
@view
def _evm_usdc() -> uint256:
    return staticcall IERC20(conversions.usdc_address()).balanceOf(self)


@internal
@view
def _owner_spot_usdc() -> uint256:
    return convert(precompiles.spot_balance(OWNER, constants.USDC_TOKEN_INDEX).total, uint256)


@internal
@view
def _source_balance(from_perp: bool) -> int256:
    # Perp raw USD does not change with unrealized profit or loss.
    if from_perp:
        return convert(
            precompiles.account_margin_summary(constants.DEFAULT_PERP_DEX, self).raw_usd, int256
        )
    return convert(precompiles.spot_balance(self, constants.USDC_TOKEN_INDEX).total, int256)


@internal
@view
def _observed() -> bool:
    if not self.has_pending or block.number <= self.pending.evm_block:
        return False
    if self.pending.to_core:
        return self._owner_spot_usdc() >= self.pending.baseline + self.pending.amount * 100
    return self._evm_usdc() >= self.pending.baseline + self.pending.amount


@external
@view
def observed() -> bool:
    """Whether a later block shows the pending transfer at its destination. Other
    transfers to the same balance can fake a result. A real contract must account
    for them."""
    return self._observed()


@external
@view
def status() -> Status:
    usdc: precompiles.SpotBalance = precompiles.spot_balance(self, constants.USDC_TOKEN_INDEX)
    return Status(
        evm_block=block.number,
        core_exists=precompiles.core_user_exists(self),
        spot_usdc=usdc.total,
        spot_hype=precompiles.spot_balance(self, conversions.hype_token_index()).total,
        withdrawable=precompiles.withdrawable(self),
        evm_usdc=self._evm_usdc(),
        owner_spot_usdc=precompiles.spot_balance(OWNER, constants.USDC_TOKEN_INDEX).total,
        has_pending=self.has_pending,
        observed=self._observed(),
    )


@external
def move_usdc(ntl: uint64, to_perp: bool):
    """Move ntl perp USD (6 decimals) between Core spot and Core perp."""
    self._only_owner()
    assert precompiles.core_user_exists(self), "Core account not activated"
    assert ntl > 0, "Zero amount"
    core_writer.transfer_usd_class(ntl, to_perp)


@external
@nonreentrant
def return_usdc(amount: uint256, from_perp: bool):
    """Return amount EVM USDC (6 decimals) from Core perp (from_perp) or Core spot."""
    self._only_owner()
    assert not self.has_pending, "Transfer pending"
    # An account that is not activated cannot send actions. They fail silently.
    assert precompiles.core_user_exists(self), "Core account not activated"
    source: uint32 = constants.SPOT_DEX
    if from_perp:
        source = constants.DEFAULT_PERP_DEX
        assert convert(precompiles.withdrawable(self), uint256) >= amount, "Not withdrawable"
    else:
        spot: precompiles.SpotBalance = precompiles.spot_balance(self, constants.USDC_TOKEN_INDEX)
        assert convert(spot.total - spot.hold, uint256) >= amount * 100, "Spot balance too low"
    self._submit_return(amount, from_perp, source)


@external
@nonreentrant
def return_spot_unchecked(amount: uint256):
    """Tutorial only: return amount EVM USDC (6 decimals) from Core spot without
    the balance check. A return above the spot balance shows a silent failure:
    the EVM transaction succeeds, Core moves nothing, and the return stays
    pending. A real contract checks the balance, as return_usdc does."""
    self._only_owner()
    assert not self.has_pending, "Transfer pending"
    assert precompiles.core_user_exists(self), "Core account not activated"
    self._submit_return(amount, False, constants.SPOT_DEX)


@internal
def _submit_return(amount: uint256, from_perp: bool, source: uint32):
    self.pending = Pending(
        to_core=False,
        from_perp=from_perp,
        amount=amount,
        baseline=self._evm_usdc(),
        source_baseline=self._source_balance(from_perp),
        evm_block=block.number,
        l1_block=precompiles.l1_block_number(),
    )
    self.has_pending = True
    log Submitted(to_core=False, from_perp=from_perp, amount=amount)
    # A fixed source DEX. Never take the DEX index from untrusted input.
    bridge.bridge_usdc_to_evm(amount, source)


@external
@nonreentrant
def deposit(amount: uint256):
    """Deposit amount EVM USDC (6 decimals) into the owner's Core spot balance."""
    self._only_owner()
    assert not self.has_pending, "Transfer pending"
    assert amount > 0, "Zero amount"
    assert self._evm_usdc() >= amount, "EVM balance too low"
    # The owner has a Core account, so the deposit pays no activation fee.
    assert precompiles.core_user_exists(OWNER), "Owner has no Core account"
    self.pending = Pending(
        to_core=True,
        from_perp=False,
        amount=amount,
        baseline=self._owner_spot_usdc(),
        source_baseline=0,
        evm_block=block.number,
        l1_block=precompiles.l1_block_number(),
    )
    self.has_pending = True
    log Submitted(to_core=True, from_perp=False, amount=amount)
    # A fixed recipient and a fixed DEX. Never take either from untrusted input.
    bridge.bridge_usdc_to_core_for(OWNER, amount, constants.SPOT_DEX)


@external
@nonreentrant
def confirm():
    """Clear the pending transfer after a later block shows it at its destination."""
    self._only_owner()
    assert self.has_pending, "No transfer pending"
    assert self._observed(), "Not observed"
    self.has_pending = False
    log Confirmed(to_core=self.pending.to_core, amount=self.pending.amount)


@external
@nonreentrant
def abandon():
    """Clear a pending transfer that Core processed without doing it, for example a
    return above the balance. Core does not report a failure, so this waits until
    Core has processed the action. For a return, it also checks that Core never
    took the USDC, so a return that Core has already paid out cannot be abandoned."""
    self._only_owner()
    assert self.has_pending, "No transfer pending"
    assert precompiles.l1_block_number() > self.pending.l1_block + PROCESSED_AFTER_L1_BLOCKS, "Too early"
    assert not self._observed(), "Observed: confirm it"
    if not self.pending.to_core:
        assert self._source_balance(self.pending.from_perp) >= self.pending.source_baseline, "Core took the USDC"
    self.has_pending = False
    log Abandoned(to_core=self.pending.to_core, amount=self.pending.amount)


@external
@nonreentrant
def withdraw_usdc(amount: uint256):
    """Send EVM USDC (6 decimals) of this contract to the owner (cleanup)."""
    self._only_owner()
    assert not self.has_pending, "Transfer pending"
    assert extcall IERC20(conversions.usdc_address()).transfer(
        OWNER, amount, default_return_value=True
    ), "USDC transfer failed"


@external
def sweep(token: uint64, amount_wei: uint64):
    """Send Core spot funds of this contract to the owner on Core (cleanup).
    amount_wei is in Core wei: 8 decimals for USDC and for HYPE."""
    self._only_owner()
    assert precompiles.core_user_exists(self), "Core account not activated"
    core_writer.send_asset(
        OWNER, empty(address), constants.SPOT_DEX, constants.SPOT_DEX, token, amount_wei
    )
