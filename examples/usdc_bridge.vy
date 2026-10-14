# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
# SPDX-License-Identifier: MIT

"""
@title USDC bridge example
@notice The owner moves USDC between the EVM balance and the HyperCore spot
        balance of this contract. Each transfer stays pending until a later
        block shows its result, or until Core has processed it without a
        result.
@dev An example for the documentation. Nobody has audited it. It shows the
     tasks that the library leaves to the importing contract: access control,
     reentrancy protection, a fixed DEX, an activation check and a record of
     the pending transfer.

     Both directions use Core spot. Trading profit and loss can change a perp
     balance but not a spot balance, so only a transfer, or a gift of the same
     amount, can make a pending transfer look done.
"""

from ethereum.ercs import IERC20

from hyper_vyper import bridge
from hyper_vyper import constants
from hyper_vyper import conversions
from hyper_vyper import precompiles


struct Pending:
    to_core: bool
    amount: uint256  # EVM USDC, 6 decimals
    destination_baseline: uint256  # the balance that must grow, read at submission
    source_baseline: uint256  # Core spot USDC at submission, 8 decimals. Only returns use it.
    evm_block: uint256
    l1_block: uint64


event Submitted:
    to_core: bool
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
def _core_spot_usdc() -> uint256:
    # Core USDC, 8 decimals
    return convert(precompiles.spot_balance(self, constants.USDC_TOKEN_INDEX).total, uint256)


@internal
@view
def _evm_usdc() -> uint256:
    # EVM USDC, 6 decimals
    return staticcall IERC20(conversions.usdc_address()).balanceOf(self)


@internal
@view
def _arrived() -> bool:
    if self.pending.to_core:
        return self._core_spot_usdc() >= self.pending.destination_baseline + self.pending.amount * 100
    return self._evm_usdc() >= self.pending.destination_baseline + self.pending.amount


@internal
def _submit(to_core: bool, amount: uint256):
    assert msg.sender == OWNER, "Only the owner"
    assert not self.has_pending, "Transfer pending"
    assert amount > 0, "Zero amount"
    # Activate first: an account that is not activated cannot send actions.
    assert precompiles.core_user_exists(self), "Core account not activated"
    destination: uint256 = 0
    if to_core:
        destination = self._core_spot_usdc()
    else:
        destination = self._evm_usdc()
    self.pending = Pending(
        to_core=to_core,
        amount=amount,
        destination_baseline=destination,
        source_baseline=self._core_spot_usdc(),
        evm_block=block.number,
        l1_block=precompiles.l1_block_number(),
    )
    self.has_pending = True
    log Submitted(to_core=to_core, amount=amount)


@external
@nonreentrant
def deposit(amount: uint256):
    """Send EVM USDC (6 decimals) to the spot balance of this contract on Core."""
    self._submit(True, amount)
    # A fixed DEX. Never take the DEX index from untrusted input.
    bridge.bridge_usdc_to_core(amount, constants.SPOT_DEX)


@external
@nonreentrant
def withdraw(amount: uint256):
    """Return USDC (6 decimals) from the Core spot balance to this contract on EVM.
    Core charges the gas in HYPE from Core spot when the contract holds HYPE, and
    otherwise in USDC from Core spot."""
    self._submit(False, amount)
    spot: precompiles.SpotBalance = precompiles.spot_balance(self, constants.USDC_TOKEN_INDEX)
    assert convert(spot.total - spot.hold, uint256) >= amount * 100, "Spot balance too low"
    bridge.bridge_usdc_to_evm(amount, constants.SPOT_DEX)


@external
@view
def observed() -> bool:
    """Whether a later block shows the pending transfer at its destination."""
    return self.has_pending and block.number > self.pending.evm_block and self._arrived()


@external
@nonreentrant
def confirm():
    """Clear the pending transfer after its result is visible."""
    assert msg.sender == OWNER, "Only the owner"
    assert self.has_pending, "No transfer pending"
    assert block.number > self.pending.evm_block, "Same block"
    assert self._arrived(), "Not observed"
    self.has_pending = False
    log Confirmed(to_core=self.pending.to_core, amount=self.pending.amount)


@external
@nonreentrant
def abandon():
    """Clear a pending transfer that Core processed without doing it, for example a
    return that Core rejected. Core does not report a failure, so this waits until
    Core has processed the action. For a return, it also checks that Core never
    took the USDC, so a return that Core has paid out cannot be abandoned."""
    assert msg.sender == OWNER, "Only the owner"
    assert self.has_pending, "No transfer pending"
    assert precompiles.l1_block_number() > self.pending.l1_block + PROCESSED_AFTER_L1_BLOCKS, "Too early"
    assert not self._arrived(), "Observed: confirm it"
    if not self.pending.to_core:
        assert self._core_spot_usdc() >= self.pending.source_baseline, "Core took the USDC"
    self.has_pending = False
    log Abandoned(to_core=self.pending.to_core, amount=self.pending.amount)
