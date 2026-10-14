"""Local EVM fixtures. These simulate submission, not the HyperCore engine."""

from collections import namedtuple
from dataclasses import dataclass, field

import boa
from boa.vm.py_evm import register_raw_precompile
from eth.exceptions import Revert
from eth_abi import decode, encode

from hyper_vyper.testing import _precompiles, system_address

# Re-exported for the tests: one source for the network addresses and recorded replies.
from hyper_vyper.testing import live_reply as live_reply
from hyper_vyper.testing.sim import CORE_WRITER as CORE_WRITER
from hyper_vyper.testing.sim import HYPE_SYSTEM as HYPE_SYSTEM
from hyper_vyper.testing.sim import SIM_TOKEN as SIM_TOKEN
from hyper_vyper.testing.sim import SPOT_DEX as SPOT_DEX
from hyper_vyper.testing.sim import USDC as USDC
from hyper_vyper.testing.sim import WALLET as WALLET

USDC_UNIT = 10**6  # one USDC on EVM and in perp USD
CORE_UNIT = 10**8  # one USDC or HYPE on Core spot
START_BALANCE = 100 * USDC_UNIT  # the EVM USDC of each lab contract
ZERO = "0x" + "00" * 20
USER = "0x" + "12" * 20
VAULT = "0x" + "34" * 20
VALIDATOR = "0x" + "56" * 20
OTHER = "0x" + "78" * 20
SEND_ASSET = bytes.fromhex("0100000d")
U64 = 2**64 - 1
# PROCESSED_AFTER_L1_BLOCKS in examples/usdc_bridge.vy and tutorials/evm_core/evm_core.vy.
PROCESSED = 200
TOKEN_ABI = "(string,uint64[],uint64,address,address,uint8,uint8,int8)"
SPOT_ABI = "(string,uint64[2])"
PERP_ABI = "(string,uint32,uint8,uint8,bool)"
REGISTRY = "0x0b51d1A9098cf8a72C325003F44C194D41d7A85B"  # TokenRegistry on mainnet
STHYPE_EVM = "0x94e8396e0869c9f2200760af0621afd240e1cf38"  # stHYPE ERC-20 on mainnet

TokenInfo = namedtuple(
    "TokenInfo",
    "name spots deployer_trading_fee_share deployer evm_contract sz_decimals wei_decimals "
    "evm_extra_wei_decimals",
)


def token_info(reply):
    """A token_info precompile reply as named fields."""
    return TokenInfo(*decode([TOKEN_ABI], reply)[0])


def send_asset_action(destination, token, amount_wei):
    """The CoreWriter payload of a spot-to-spot sendAsset."""
    return SEND_ASSET + encode(
        ["address", "address", "uint32", "uint32", "uint64", "uint64"],
        [destination, ZERO, SPOT_DEX, SPOT_DEX, token, amount_wei],
    )


def token_payload(name="USDC", spots=(1,), evm=None, sz=2, wei=8, extra=-2):
    # On HyperCore, USDC links to Circle's CoreDepositWallet, not to the USDC token.
    if evm is None:
        evm = WALLET[boa.env.evm.patch.chain_id]
    return encode([TOKEN_ABI], [(name, spots, 0, USER, evm, sz, wei, extra)])


def normalized(value):
    if isinstance(value, (tuple, list)):
        return tuple(normalized(item) for item in value)
    if isinstance(value, str) and value.startswith("0x"):
        return value.lower()
    return value


@dataclass
class Lab:
    vy: object
    sol: object
    writer: object
    calls: list = field(default_factory=list, repr=False)

    @property
    def reads(self):
        """(suffix, input) of each precompile call."""
        return [call[:2] for call in self.calls]

    def read(self, suffix, payload=b"", *, fail=False, gas=None):
        """Mock a precompile. payload is one reply, or a dict from input to reply, where
        an unknown input fails like a bad read."""

        def callback(computation):
            data = computation.msg.data_as_bytes
            self.calls.append((suffix, data, computation.msg.gas))
            if isinstance(payload, dict) and data not in payload:
                raise Revert(b"unexpected precompile input")
            reply = payload[data] if isinstance(payload, dict) else payload
            cost = _precompiles.read_gas(data, reply) if gas is None else gas
            computation.consume_gas(cost, reason="mock HyperCore read")
            if fail:
                raise Revert(b"mock precompile failure")
            computation.output = reply
            return computation

        register_raw_precompile(_precompiles.address(suffix), callback, force=True)


RECORDER = """
last_data: public(Bytes[548])
call_count: public(uint256)
fail: public(bool)

@external
def set_fail(enabled: bool):
    self.fail = enabled

@external
def sendRawAction(data: Bytes[548]):
    assert not self.fail, "CoreWriter unavailable"
    self.last_data = data
    self.call_count += 1
"""

# Mock USDC with failure modes, for rollback checks.
TOKEN_APPROVE_FALSE = 1  # approve() returns False
TOKEN_RESET_FALSE = 2  # approve(spender, 0) returns False
TOKEN_TRANSFER_REVERTS = 3  # transferFrom() reverts
FAILING_TOKEN = """
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
failure: public(uint8)

@external
def mint(user: address, amount: uint256):
    self.balanceOf[user] += amount

@external
def set_failure(mode: uint8):
    self.failure = mode

@external
def approve(spender: address, amount: uint256) -> bool:
    if self.failure == 1:
        return False
    if self.failure == 2 and amount == 0:
        return False
    self.allowance[msg.sender][spender] = amount
    return True

@external
def transferFrom(sender: address, recipient: address, amount: uint256) -> bool:
    assert self.failure != 3, "Transfer failed"
    self.allowance[sender][msg.sender] -= amount
    self.balanceOf[sender] -= amount
    self.balanceOf[recipient] += amount
    return True
"""

# Mock USDC whose approve() returns nothing, like some older ERC-20 tokens.
NO_RETURN_TOKEN = """
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])

@external
def mint(user: address, amount: uint256):
    self.balanceOf[user] += amount

@external
def approve(spender: address, amount: uint256):
    self.allowance[msg.sender][spender] = amount

@external
def transferFrom(sender: address, recipient: address, amount: uint256) -> bool:
    self.allowance[sender][msg.sender] -= amount
    self.balanceOf[sender] -= amount
    self.balanceOf[recipient] += amount
    return True
"""

# Mock USDC whose approve() returns 2, which is not a valid bool.
BAD_BOOL_TOKEN = """
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])

@external
def mint(user: address, amount: uint256):
    self.balanceOf[user] += amount

@external
def approve(spender: address, amount: uint256) -> uint256:
    self.allowance[msg.sender][spender] = amount
    return 2
"""


# A deposit wallet that records each call, for checks on what the library sends.
RECORDING_WALLET = """
from ethereum.ercs import IERC20

TOKEN: immutable(address)
last_recipient: public(address)
last_amount: public(uint256)
last_dex: public(uint32)
call_count: public(uint256)
failure: public(bool)
leave_unspent: public(uint256)
seen_allowance: public(uint256)

@deploy
def __init__(token: address):
    TOKEN = token

@external
def configure(failure: bool, unspent: uint256):
    self.failure = failure
    self.leave_unspent = unspent

@internal
def _deposit(recipient: address, amount: uint256, dex: uint32):
    assert not self.failure, "Deposit failed"
    self.seen_allowance = staticcall IERC20(TOKEN).allowance(msg.sender, self)
    assert extcall IERC20(TOKEN).transferFrom(msg.sender, self, amount - self.leave_unspent)
    self.last_recipient = recipient
    self.last_amount = amount
    self.last_dex = dex
    self.call_count += 1

@external
def deposit(amount: uint256, destinationDex: uint32):
    self._deposit(msg.sender, amount, destinationDex)

@external
def depositFor(recipient: address, amount: uint256, destinationDex: uint32):
    self._deposit(recipient, amount, destinationDex)
"""

# Runtime code at 0x2222...2222 on mainnet and testnet (eth_getCode, identical on
# both): a payable receive() that emits Received(msg.sender, msg.value) and
# reverts on any calldata.
HYPE_SYSTEM_CODE = bytes.fromhex(
    "608060405236603f5760405134815233907f88a5966d370b9919b20f3e2c13ff65706f196a4e32cc2c12"
    "bf57088f885258749060200160405180910390a2005b600080fdfea2646970667358221220ca425db508"
    "98ac19f9e4676e86e8ebed9853baa048942f6306fe8a86b8d4abb964736f6c63430008090033"
)


def system_address_for(token):
    """The system address of a token on the current chain."""
    return system_address(token, boa.env.evm.patch.chain_id)


def send_asset_payload(token, amount_wei):
    """The payload of a return to EVM: a sendAsset to the token's system address."""
    return send_asset_action(system_address_for(token), token, amount_wei)


# Mock linked ERC-20: balances, transfer and failure modes for the generic bridge.
# failure: 1 = transfer returns false, 2 = transfer reverts.
LINKED_TOKEN = """
balanceOf: public(HashMap[address, uint256])
failure: public(uint8)
transfer_count: public(uint256)

@external
def mint(user: address, amount: uint256):
    self.balanceOf[user] += amount

@external
def set_failure(mode: uint8):
    self.failure = mode

@external
def transfer(recipient: address, amount: uint256) -> bool:
    assert self.failure != 2, "Transfer failed"
    if self.failure == 1:
        return False
    self.balanceOf[msg.sender] -= amount
    self.balanceOf[recipient] += amount
    self.transfer_count += 1
    return True
"""

# A HYPE receiver that needs more than the 2300 gas stipend.
GAS_HUNGRY_RECEIVER = """
received: public(uint256)

@external
@payable
def __default__():
    self.received += msg.value
"""


def reverts(reason=None):
    """boa.reverts that also takes None for a revert without a reason string."""
    if reason is None:
        return boa.reverts()
    return boa.reverts(reason)
