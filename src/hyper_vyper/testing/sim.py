"""A small, deterministic HyperCore simulator for local Vyper tests (Titanoboa).

How it works:
- Precompile reads answer from a snapshot of Core state. The snapshot is taken at
  the start of each EVM block, so a transaction never sees its own Core effects.
- A journal contract at the CoreWriter address stores each raw action. A reverted
  EVM transaction leaves no action, as on HyperEVM.
- A mock CoreDepositWallet takes USDC and writes a deposit to the same journal.
- A mock at the HYPE system address (0x2222...2222) takes native HYPE and writes
  an EVM -> Core transfer to the journal. ERC-20 sends to system addresses are not
  seen, so call `sim.bridge_in(user, token, amount_wei)` after one.
- `sim.advance()` ends the block. Core then applies due actions and deposits in
  submission order, pays Core -> EVM returns on EVM, and takes the next snapshot.
- A failed Core action changes nothing on Core and never reverts the EVM
  transaction. The simulator records the reason in `sim.events`.

The testing quick start in the docs lists the HyperCore rules that the model
follows, the `Policy` settings, and the limits of the model.
"""

from __future__ import annotations

import copy
import heapq
import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Literal, get_args

import boa
from eth.exceptions import Revert
from eth_abi import decode, encode
from eth_abi.exceptions import DecodingError

from hyper_vyper.testing import _precompiles, measured
from hyper_vyper.testing._precompiles import (
    ACCOUNT_MARGIN_SUMMARY,
    BBO,
    CORE_USER_EXISTS,
    L1_BLOCK_NUMBER,
    MARK_PX,
    ORACLE_PX,
    POSITION2,
    SPOT_BALANCE,
    SPOT_PX,
    TOKEN_INFO,
    VAULT_EQUITY,
    WITHDRAWABLE,
)

CORE_WRITER = "0x" + "33" * 20
USDC = {
    999: "0xb88339CB7199b77E23DB6E890353E22632Ba630f",
    998: "0x2B3370eE501B4a559b57D449569354196457D8Ab",
}
WALLET = {  # Circle CoreDepositWallet
    999: "0x6B9E773128f453f5c2C60935Ee2DE2CBc5390A24",
    998: "0x0B80659a4076E9E93C7DbE0f10675A16a3e5C206",
}

# Precompile replies recorded from the real chain by scripts/record_live_replies.py.
LIVE_REPLIES = json.loads(
    resources.files(__package__).joinpath("data", "live_replies.json").read_text()
)


def live_reply(name, chain_id):
    """A precompile reply recorded from the real chain."""
    for entry in LIVE_REPLIES:
        if entry["name"] == name and entry["chain_id"] == chain_id:
            return bytes.fromhex(entry["reply"][2:])
    raise KeyError((name, chain_id))


SPOT_DEX = 2**32 - 1
USDC_TOKEN = 0
HYPE_TOKEN = {999: 150, 998: 1105}
HYPE_SYSTEM = "0x" + "22" * 20
BASE_SYSTEM = 0x2000000000000000000000000000000000000000
CORE_PER_PERP = 100  # USDC: 8 decimals on Core spot, 6 for perp USD and on EVM
HYPE_EVM_PER_CORE = 10**10  # HYPE: 18 decimals on EVM, 8 on Core

# Mock USDC: balances, allowances and `transfer`, so returns can pay out of a reserve.
SIM_TOKEN = """
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])

@external
def mint(user: address, amount: uint256):
    self.balanceOf[user] += amount

@external
def approve(spender: address, amount: uint256) -> bool:
    self.allowance[msg.sender][spender] = amount
    return True

@external
def transferFrom(sender: address, recipient: address, amount: uint256) -> bool:
    self.allowance[sender][msg.sender] -= amount
    self.balanceOf[sender] -= amount
    self.balanceOf[recipient] += amount
    return True

@external
def transfer(recipient: address, amount: uint256) -> bool:
    self.balanceOf[msg.sender] -= amount
    self.balanceOf[recipient] += amount
    return True
"""

# Stands in for CoreWriter. It keeps every action in storage, so a revert drops it.
JOURNAL = """
struct Entry:
    kind: uint8
    sender: address
    block: uint256
    data: Bytes[548]

event RawAction:
    user: indexed(address)
    data: Bytes[548]

OWNER: immutable(address)
entries: public(HashMap[uint256, Entry])
count: public(uint256)
deposit_wallet: public(address)

@deploy
def __init__():
    OWNER = msg.sender

@external
def set_deposit_wallet(wallet: address):
    assert msg.sender == OWNER
    self.deposit_wallet = wallet

@internal
def _push(kind: uint8, sender: address, data: Bytes[548]):
    self.entries[self.count] = Entry(kind=kind, sender=sender, block=block.number, data=data)
    self.count += 1

@external
def sendRawAction(data: Bytes[548]):
    self._push(1, msg.sender, data)
    log RawAction(user=msg.sender, data=data)

@external
def recordDeposit(sender: address, recipient: address, amount: uint256, dex: uint32):
    assert msg.sender == self.deposit_wallet, "Only the deposit wallet"
    self._push(2, sender, abi_encode(recipient, amount, dex))

@external
def recordHype(sender: address, amount: uint256):
    assert msg.sender == 0x2222222222222222222222222222222222222222, "Only the HYPE system"
    self._push(3, sender, abi_encode(amount))
"""

# Stands in for the code at 0x2222..: a payable receive that logs the sender and
# reverts on calldata, as on chain, plus a journal entry so Core sees the transfer.
HYPE_SYSTEM_MOCK = """
interface IJournal:
    def recordHype(sender: address, amount: uint256): nonpayable

event Received:
    user: indexed(address)
    amount: uint256

JOURNAL: immutable(address)

@deploy
def __init__(journal: address):
    JOURNAL = journal

@external
@payable
def __default__():
    assert len(msg.data) == 0
    log Received(user=msg.sender, amount=msg.value)
    extcall IJournal(JOURNAL).recordHype(msg.sender, msg.value)
"""

DEPOSIT_WALLET = """
from ethereum.ercs import IERC20

interface IJournal:
    def recordDeposit(sender: address, recipient: address, amount: uint256, dex: uint32): nonpayable

TOKEN: immutable(address)
JOURNAL: immutable(address)
SYSTEM: immutable(address)

@deploy
def __init__(token: address, journal: address, system: address):
    TOKEN = token
    JOURNAL = journal
    SYSTEM = system

@internal
def _deposit(recipient: address, amount: uint256, dex: uint32):
    assert amount > 0, "Zero deposit"
    assert extcall IERC20(TOKEN).transferFrom(msg.sender, self, amount)
    extcall IJournal(JOURNAL).recordDeposit(msg.sender, recipient, amount, dex)

@external
def deposit(amount: uint256, destinationDex: uint32):
    self._deposit(msg.sender, amount, destinationDex)

@external
def depositFor(recipient: address, amount: uint256, destinationDex: uint32):
    self._deposit(recipient, amount, destinationDex)

@external
def systemCredit(recipient: address, amount: uint256):
    assert msg.sender == SYSTEM, "Only the system"
    assert extcall IERC20(TOKEN).transfer(recipient, amount)
"""

# action id -> (name, ABI argument types, argument names)
ACTIONS = {
    1: (
        "limit_order",
        "uint32,bool,uint64,uint64,bool,uint8,uint128",
        "asset is_buy limit_px sz reduce_only tif cloid",
    ),
    2: ("vault_transfer", "address,bool,uint64", "vault is_deposit usd"),
    3: ("token_delegate", "address,uint64,bool", "validator amount_wei undelegate"),
    4: ("staking_deposit", "uint64", "amount_wei"),
    5: ("staking_withdraw", "uint64", "amount_wei"),
    6: ("spot_send", "address,uint64,uint64", "to token amount_wei"),
    7: ("usd_class_transfer", "uint64,bool", "ntl to_perp"),
    8: ("finalize_evm_contract", "uint64,uint8,uint64", "token variant nonce"),
    9: ("add_api_wallet", "address,string", "wallet name"),
    10: ("cancel_by_oid", "uint32,uint64", "asset oid"),
    11: ("cancel_by_cloid", "uint32,uint128", "asset cloid"),
    12: ("approve_builder_fee", "uint64,address", "max_fee_rate builder"),
    13: (
        "send_asset",
        "address,address,uint32,uint32,uint64,uint64",
        "destination sub_account source_dex destination_dex token amount_wei",
    ),
    15: ("borrow_lend", "uint8,uint64,uint64", "operation token amount_wei"),
    16: ("set_abstraction", "address,uint8", "user mode"),
}
DELAYED = {"limit_order", "vault_transfer"}  # documented extra delay


class CoreFailure(Exception):
    """An action that HyperCore would reject silently."""


DepositToInactive = Literal["activate", "drop"]


@dataclass
class Policy:
    """Timing and behavior settings. Defaults follow the docs and measured chain behavior."""

    block_time: int = 1  # seconds per small EVM block (documented: 1 s)
    transfer_delay_blocks: int = 1  # applied after the block (documented)
    delayed_action_blocks: int = 3  # orders and vault transfers: "a few seconds" (documented)
    deposit_delay_blocks: int = 1  # deposit wallet -> Core: the next block (measured)
    evm_credit_extra_blocks: int = 0  # EVM payout after the Core debit: same block (measured)
    evm_transfer_fee_hype_wei: int = measured.RETURN_GAS_HYPE_WEI
    # Core -> EVM gas in Core USDC wei when Core spot has too little HYPE.
    evm_transfer_fee_usdc_fallback_wei: int = measured.RETURN_GAS_USDC_WEI
    new_account_fee: int = measured.ACTIVATION_FEE_PERP  # paid by the sender
    # A CoreDepositWallet deposit to an account that is not activated: "activate" (the deposit
    # activates it and pays the fee from the amount, measured on mainnet) or "drop"
    # (the testnet wallet with an address that has no mainnet account).
    deposit_to_inactive: DepositToInactive = "activate"
    vault_lock_ms: int = 86_400_000  # user-vault deposit lock: 1 day (documented)

    def __post_init__(self):
        if self.deposit_to_inactive not in get_args(DepositToInactive):
            raise ValueError(f"deposit_to_inactive must be one of {get_args(DepositToInactive)}")


@dataclass
class Perp:
    usd: int = 0  # raw USD, 6 decimals: transfers and realized P&L
    pnl: int = 0  # unrealized P&L, 6 decimals
    margin_used: int = 0
    ntl_pos: int = 0

    @property
    def account_value(self):
        return self.usd + self.pnl

    @property
    def withdrawable(self):
        return max(0, self.account_value - self.margin_used)


@dataclass
class Account:
    spot: dict = field(default_factory=dict)  # token -> [total, hold] in Core wei
    perp: dict = field(default_factory=dict)  # dex -> Perp
    vaults: dict = field(default_factory=dict)  # vault -> [equity, locked_until_ms]
    agents: dict = field(default_factory=dict)  # name -> wallet
    abstraction: int | None = None

    def balance(self, token):
        return self.spot.setdefault(token, [0, 0])

    def perp_dex(self, dex=0):
        return self.perp.setdefault(dex, Perp())


@dataclass
class CoreState:
    accounts: dict = field(default_factory=dict)  # address -> Account, only if activated
    escrow: dict = field(default_factory=dict)  # address -> {token: Core wei}, not in reads
    l1_block: int = 1_000_000
    mark_px: dict = field(default_factory=dict)
    oracle_px: dict = field(default_factory=dict)
    spot_px: dict = field(default_factory=dict)
    bbo: dict = field(default_factory=dict)
    positions: dict = field(default_factory=dict)  # (user, perp) -> 5-tuple
    vaults: set = field(default_factory=set)  # known Core vault addresses


@dataclass
class SimEvent:
    seq: int
    block: int  # EVM block that submitted it
    kind: str  # "action", "deposit", "bridge_in" or "evm_credit"
    name: str
    sender: str
    args: dict
    status: str = "queued"  # queued, applied, failed, recorded
    reason: str = ""
    applied_block: int | None = None


def _addr(value):
    value = getattr(value, "address", value)
    return str(value).lower()


def system_address(token, chain_id):
    if token == HYPE_TOKEN[chain_id]:
        return HYPE_SYSTEM
    return "0x%040x" % (BASE_SYSTEM + token)


def _price_reader(prices):
    """A precompile reader for one of the price tables in CoreState."""

    def read(sim, view, data):
        value = getattr(view, prices).get(decode(["uint64"], data)[0])
        return None if value is None else encode(["uint64"], [value])

    return read


class CoreSim:
    """HyperCore state, block-start precompile reads and a delayed CoreWriter."""

    def __init__(self, chain_id=999, policy=None):
        self.env = boa.env
        self.chain_id = chain_id
        self.policy = policy or Policy()
        self.live = CoreState()
        self.view = CoreState()
        self.events: list[SimEvent] = []
        self.tokens = {
            USDC_TOKEN: live_reply("token_info_usdc", chain_id),
            HYPE_TOKEN[chain_id]: live_reply("token_info_hype", chain_id),
        }
        self.evm_tokens = {}  # token -> (contract, evm_extra_decimals) for non-USDC returns
        self.replies = {}  # (suffix, input or None) -> fixed reply
        self._forced = []  # [(name or None, reason)]
        self._queue = []  # heap of (due_block, seq, kind, payload)
        self._seq = 0
        self._cursor = 0
        self.hype = HYPE_TOKEN[chain_id]

    # --- setup ---

    @classmethod
    def install(cls, chain_id=999, policy=None):
        """Deploy the mocks at their real addresses and register the precompiles."""
        boa.env.evm.patch.chain_id = chain_id
        sim = cls(chain_id, policy)
        sim.usdc = boa.loads_partial(SIM_TOKEN, name="MockUSDC").deploy(
            override_address=USDC[chain_id]
        )
        sim.writer = boa.loads_partial(JOURNAL, name="CoreWriterJournal").deploy(
            override_address=CORE_WRITER
        )
        sim.wallet = boa.loads_partial(DEPOSIT_WALLET, name="SimDepositWallet").deploy(
            sim.usdc.address,
            sim.writer.address,
            system_address(USDC_TOKEN, chain_id),
            override_address=WALLET[chain_id],
        )
        sim.writer.set_deposit_wallet(sim.wallet.address)
        boa.loads_partial(HYPE_SYSTEM_MOCK, name="HypeSystem").deploy(
            sim.writer.address, override_address=HYPE_SYSTEM
        )
        sim.block = sim.env.evm.patch.block_number
        _precompiles.register(sim._precompile)
        sim.publish()
        return sim

    def close(self):
        _precompiles.deregister()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def account(self, user, create=True):
        """The live account. Creating one activates it (see `activate`)."""
        user = _addr(user)
        if user not in self.live.accounts:
            if not create:
                return None
            self._activate(self.live, user)
        return self.live.accounts[user]

    def activate(self, *users):
        """The operator's activation step: the account becomes active with no net
        balance change (the 1 USDC sent pays the fee) and its escrow moves to spot.
        Applies to live state now."""
        for user in users:
            self.account(user)

    def bridge_in(self, user, token, amount_wei):
        """Queue an EVM -> Core transfer that the simulator cannot see, such as an
        ERC-20 sent to its system address. It lands like a HYPE transfer."""
        args = {"user": _addr(user), "token": token, "amount_wei": amount_wei}
        event = self._new_event(self.block, "bridge_in", "bridge_in", _addr(user), args)
        self._schedule(self.block + self.policy.transfer_delay_blocks, "bridge_in", event)
        return event

    def set_spot(self, user, token, total, hold=0):
        self.account(user).spot[token] = [total, hold]

    def set_hype(self, user, amount_wei):
        self.set_spot(user, self.hype, amount_wei)

    def set_perp(self, user, dex=0, **values):
        """Set Perp fields: usd, pnl, margin_used, ntl_pos."""
        perp = self.account(user).perp_dex(dex)
        for name, value in values.items():
            if not hasattr(perp, name):
                raise AttributeError(name)
            setattr(perp, name, value)

    def add_pnl(self, user, unrealized=0, realized=0, dex=0):
        """Market moves between blocks. Realized P&L changes raw USD."""
        perp = self.account(user).perp_dex(dex)
        perp.pnl += unrealized
        perp.usd += realized

    def add_vault(self, vault):
        self.live.vaults.add(_addr(vault))

    def set_vault_equity(self, user, vault, equity, locked_until_ms=0):
        self.add_vault(vault)
        self.account(user).vaults[_addr(vault)] = [equity, locked_until_ms]

    def set_price(self, kind, index, value):
        getattr(self.live, kind)[index] = value

    def set_position(
        self, user, perp, szi=0, entry_ntl=0, isolated_raw_usd=0, leverage=0, iso=False
    ):
        self.live.positions[(_addr(user), perp)] = (szi, entry_ntl, isolated_raw_usd, leverage, iso)

    def set_reply(self, suffix, payload, input=None):
        """A fixed reply for a precompile without a model (metadata only)."""
        self.replies[(suffix, input)] = payload

    def link_evm_token(self, token, contract, evm_extra_decimals, token_info=None):
        """Let returns of a non-USDC token mint `contract` on EVM."""
        self.evm_tokens[token] = (contract, evm_extra_decimals)
        if token_info is not None:
            self.tokens[token] = token_info

    def fail_next(self, name=None, reason="forced failure"):
        """Fail the next processed action or deposit (of this name, if given) on Core."""
        self._forced.append((name, reason))

    def publish(self):
        """Make live state the start-of-block view now. Use it only for test setup."""
        self.view = copy.deepcopy(self.live)

    # --- inspection ---

    def spot(self, user, token=USDC_TOKEN):
        acct = self.live.accounts.get(_addr(user))
        return tuple(acct.spot.get(token, [0, 0])) if acct else (0, 0)

    def perp(self, user, dex=0):
        acct = self.live.accounts.get(_addr(user))
        return copy.copy(acct.perp.get(dex, Perp())) if acct else Perp()

    def escrow(self, user, token=USDC_TOKEN):
        """Escrowed Core wei (the info API's `evmEscrows`). No precompile shows it."""
        return self.live.escrow.get(_addr(user), {}).get(token, 0)

    def account_state(self, user):
        user = _addr(user)
        if user in self.live.accounts:
            return "activated"
        return "escrow" if self.live.escrow.get(user) else "missing"

    @property
    def failures(self):
        return [e for e in self.events if e.status == "failed"]

    @property
    def pending(self):
        return [e for e in self.events if e.status == "queued"]

    # --- block processing ---

    def advance(self, blocks=1, seconds=None):
        """End the current block, let Core run, and start `blocks` later."""
        assert blocks >= 1
        self._check_block()
        self._drain()
        seconds = blocks * self.policy.block_time if seconds is None else seconds
        start_time = self.env.evm.patch.timestamp
        target = self.block + blocks
        self.env.evm.patch.block_number = target
        self.env.evm.patch.timestamp = start_time + seconds
        self.live.l1_block += blocks
        old = self.block
        while self._queue and self._queue[0][0] <= target:
            due, _, kind, event = heapq.heappop(self._queue)
            # Core time when this item runs, for vault lock checks.
            step = max(due, old + 1) - old
            now_ms = (start_time + seconds * step // blocks) * 1000
            self._process(kind, event, due, now_ms)
        self.block = target
        self.publish()
        return [e for e in self.events if e.applied_block and old < e.applied_block <= target]

    def _check_block(self):
        if self.env.evm.patch.block_number != self.block:
            raise RuntimeError("EVM block moved without CoreSim.advance(): Core did not run")

    def _schedule(self, due, kind, event):
        self._seq += 1
        heapq.heappush(self._queue, (due, self._seq, kind, event))

    def _new_event(self, block, kind, name, sender, args):
        event = SimEvent(len(self.events), block, kind, name, sender, args)
        self.events.append(event)
        return event

    def _drain(self):
        count = self.writer.count()
        for i in range(self._cursor, count):
            kind, sender, block, data = self.writer.entries(i)
            sender = _addr(sender)
            if kind == 2:
                recipient, amount, dex = decode(["address", "uint256", "uint32"], data)
                args = {"recipient": recipient.lower(), "amount": amount, "dex": dex}
                event = self._new_event(block, "deposit", "deposit", sender, args)
                self._schedule(block + self.policy.deposit_delay_blocks, "deposit", event)
                continue
            if kind == 3:  # native HYPE sent to 0x2222..
                (amount,) = decode(["uint256"], data)
                amount_wei = amount // HYPE_EVM_PER_CORE
                args = {"user": sender, "token": self.hype, "amount_wei": amount_wei}
                event = self._new_event(block, "bridge_in", "bridge_in", sender, args)
                self._schedule(block + self.policy.transfer_delay_blocks, "bridge_in", event)
                continue
            name, args = self._decode_action(data)
            event = self._new_event(block, "action", name, sender, args)
            delay = self.policy.transfer_delay_blocks
            if name in DELAYED:
                delay += self.policy.delayed_action_blocks
            self._schedule(block + delay, "action", event)
        self._cursor = count

    @staticmethod
    def _decode_action(data):
        if len(data) < 4 or data[0] != 1:
            return "malformed", {"raw": data}
        action_id = int.from_bytes(data[1:4], "big")
        if action_id not in ACTIONS:
            return f"action_{action_id}", {"raw": data}
        name, types, names = ACTIONS[action_id]
        try:
            values = decode(types.split(","), data[4:])
        except DecodingError:
            return "malformed", {"raw": data}
        values = [v.lower() if isinstance(v, str) and v.startswith("0x") else v for v in values]
        return name, dict(zip(names.split(), values, strict=True))

    def _process(self, kind, event, due, now_ms):
        event.applied_block = due
        try:
            if kind == "evm_credit":
                self._pay_evm(event)
                event.status = "applied"
                return
            if kind == "action":  # documented. The action handlers rely on this check.
                self._require(event.sender in self.live.accounts, "sender not activated")
            for i, (name, reason) in enumerate(self._forced):
                if name in (None, event.name):
                    del self._forced[i]
                    raise CoreFailure(reason)
            handler = getattr(self, f"_do_{event.name}", None)
            if handler is None:
                event.status = "recorded"
                event.reason = "not simulated"
                return
            # Work on a copy so a failure part-way leaves Core unchanged.
            trial = copy.deepcopy(self.live)
            handler(trial, event, due, now_ms)
            self.live = trial
            event.status = "applied"
        except CoreFailure as failure:
            event.status = "failed"
            event.reason = str(failure)

    # --- Core rules ---

    @staticmethod
    def _require(condition, reason):
        if not condition:
            raise CoreFailure(reason)

    def _activate(self, state, user):
        acct = state.accounts[user] = Account()
        for token, amount in state.escrow.pop(user, {}).items():
            acct.balance(token)[0] += amount
        return acct

    def _recipient(self, state, event, sender, user, token, amount_wei):
        """The Core recipient. A send of at least 1 USDC to an account that is not
        activated activates it, and the sender pays the fee."""
        acct = state.accounts.get(user)
        if acct is not None:
            return acct
        fee = self.policy.new_account_fee * CORE_PER_PERP
        self._require(
            token == USDC_TOKEN and amount_wei >= fee, "recipient not activated (needs >= 1 USDC)"
        )
        self._debit_spot(sender, USDC_TOKEN, fee)  # the sender pays the fee
        event.reason = "recipient activated: fee charged"
        return self._activate(state, user)

    def _debit_spot(self, acct, token, amount):
        bal = acct.balance(token)
        self._require(bal[0] - bal[1] >= amount, "insufficient spot balance")
        bal[0] -= amount

    def _debit_perp(self, acct, dex, usd):
        self._require(dex == 0, "perp DEX not simulated")
        perp = acct.perp_dex(dex)
        self._require(perp.withdrawable >= usd, "insufficient withdrawable")
        perp.usd -= usd

    def _do_deposit(self, state, event, due, now_ms):
        args = event.args
        dex = args["dex"]
        if dex not in (0, SPOT_DEX):
            dex = SPOT_DEX  # a deposit to a DEX that does not exist credits spot
        usd = args["amount"]
        acct = state.accounts.get(args["recipient"])
        if acct is None and self.policy.deposit_to_inactive == "drop":
            raise CoreFailure("recipient not activated: dropped")
        if acct is None:
            # The deposit activates the account and pays the fee from the amount.
            acct = self._activate(state, args["recipient"])
            usd -= min(usd, self.policy.new_account_fee)
            event.reason = "new Core account: activation fee charged"
        if dex == SPOT_DEX:
            acct.balance(USDC_TOKEN)[0] += usd * CORE_PER_PERP
        else:
            acct.perp_dex(0).usd += usd

    def _do_spot_send(self, state, event, due, now_ms):
        a = event.args
        acct = state.accounts[event.sender]
        self._require(a["to"] != event.sender, "self transfer")
        self._require(a["amount_wei"] > 0, "zero amount")
        self._debit_spot(acct, a["token"], a["amount_wei"])
        if self._is_system(a["to"]):
            self._to_evm(acct, event, a["to"], a["token"], a["amount_wei"], due)
        else:
            target = self._recipient(state, event, acct, a["to"], a["token"], a["amount_wei"])
            target.balance(a["token"])[0] += a["amount_wei"]

    def _do_bridge_in(self, state, event, due, now_ms):
        a = event.args
        acct = state.accounts.get(a["user"])
        if acct is None:
            # A credit for an account that is not activated waits in escrow.
            bucket = state.escrow.setdefault(a["user"], {})
            bucket[a["token"]] = bucket.get(a["token"], 0) + a["amount_wei"]
            event.reason = "recipient not activated: held in escrow"
            return
        acct.balance(a["token"])[0] += a["amount_wei"]

    def _do_usd_class_transfer(self, state, event, due, now_ms):
        a = event.args
        acct = state.accounts[event.sender]
        self._require(a["ntl"] > 0, "zero amount")
        if a["to_perp"]:
            self._debit_spot(acct, USDC_TOKEN, a["ntl"] * CORE_PER_PERP)
            acct.perp_dex(0).usd += a["ntl"]
        else:
            self._debit_perp(acct, 0, a["ntl"])
            acct.balance(USDC_TOKEN)[0] += a["ntl"] * CORE_PER_PERP

    def _do_send_asset(self, state, event, due, now_ms):
        a = event.args
        acct = state.accounts[event.sender]
        token, amount, src, dst = a["token"], a["amount_wei"], a["source_dex"], a["destination_dex"]
        self._require(a["sub_account"] == "0x" + "00" * 20, "sub-accounts not simulated")
        self._require(amount > 0, "zero amount")
        self._require(a["destination"] != event.sender or src != dst, "self transfer")
        to_system = self._is_system(a["destination"])
        if src != SPOT_DEX or dst != SPOT_DEX:
            self._require(token == USDC_TOKEN, "only USDC moves on a perp DEX")
            self._require(amount % CORE_PER_PERP == 0, "amount is not a whole perp unit")
        if src == SPOT_DEX:
            self._debit_spot(acct, token, amount)
        else:
            self._debit_perp(acct, src, amount // CORE_PER_PERP)
        if to_system:
            self._require(dst == SPOT_DEX, "system address takes spot only")
            self._to_evm(acct, event, a["destination"], token, amount, due, src == SPOT_DEX)
            return
        target = acct
        if a["destination"] != event.sender:
            target = self._recipient(state, event, acct, a["destination"], token, amount)
        if dst == SPOT_DEX:
            target.balance(token)[0] += amount
        else:
            self._require(dst == 0, "perp DEX not simulated")
            target.perp_dex(0).usd += amount // CORE_PER_PERP

    def _do_vault_transfer(self, state, event, due, now_ms):
        a = event.args
        acct = state.accounts[event.sender]
        self._require(a["vault"] in state.vaults, "unknown vault")
        self._require(a["usd"] > 0, "zero amount")
        position = acct.vaults.setdefault(a["vault"], [0, 0])
        if a["is_deposit"]:
            self._debit_perp(acct, 0, a["usd"])
            position[0] += a["usd"]
            position[1] = now_ms + self.policy.vault_lock_ms
        else:
            self._require(now_ms > position[1], "vault withdrawal locked")
            self._require(position[0] >= a["usd"], "insufficient vault equity")
            position[0] -= a["usd"]
            acct.perp_dex(0).usd += a["usd"]

    def _do_add_api_wallet(self, state, event, due, now_ms):
        state.accounts[event.sender].agents[event.args["name"]] = event.args["wallet"]

    def _do_set_abstraction(self, state, event, due, now_ms):
        acct = state.accounts[event.sender]
        self._require(event.args["user"] == event.sender, "sub-accounts not simulated")
        self._require(event.args["mode"] in (1, 2, 3), "unknown abstraction mode")
        acct.abstraction = event.args["mode"]

    # --- Core -> EVM ---

    def _is_system(self, address):
        return address == HYPE_SYSTEM or (
            int(address, 16) >> 152 == 0x20 and int(address, 16) - BASE_SYSTEM < 2**32
        )

    def _to_evm(self, acct, event, destination, token, amount_wei, due, from_spot=True):
        self._require(destination == system_address(token, self.chain_id), "wrong system address")
        if token == USDC_TOKEN:
            self._require(amount_wei % CORE_PER_PERP == 0, "amount is not a whole EVM unit")
            evm_amount = amount_wei // CORE_PER_PERP
        elif token == self.hype:
            evm_amount = amount_wei * HYPE_EVM_PER_CORE
        else:
            self._require(token in self.evm_tokens, "token not linked to EVM")
            extra = self.evm_tokens[token][1]
            evm_amount = amount_wei * 10**extra if extra >= 0 else amount_wei // 10**-extra
        # A HYPE return pays no separate gas fee.
        fee = 0 if token == self.hype else self.policy.evm_transfer_fee_hype_wei
        hype = acct.balance(self.hype)
        if fee and hype[0] - hype[1] >= fee:
            hype[0] -= fee
        elif fee:
            # A USDC return without HYPE succeeds. Core takes the gas in USDC from
            # spot, and for a perp-source return without spot USDC, from perp.
            self._require(token == USDC_TOKEN, "no HYPE for EVM gas")
            usdc_fee = self.policy.evm_transfer_fee_usdc_fallback_wei
            spot = acct.balance(USDC_TOKEN)
            if spot[0] - spot[1] >= usdc_fee:
                spot[0] -= usdc_fee
            else:
                self._require(
                    not from_spot and acct.perp_dex(0).withdrawable >= usdc_fee // CORE_PER_PERP,
                    "no HYPE or USDC for EVM gas",
                )
                self._debit_perp(acct, 0, usdc_fee // CORE_PER_PERP)
            event.reason = "gas charged in USDC: no HYPE on Core spot"
        args = {"to": event.sender, "token": token, "amount": evm_amount, "source": event.seq}
        credit = self._new_event(due, "evm_credit", "evm_credit", destination, args)
        self._schedule(due + self.policy.evm_credit_extra_blocks, "evm_credit", credit)

    def _pay_evm(self, event):
        to, token, amount = event.args["to"], event.args["token"], event.args["amount"]
        if token == USDC_TOKEN:
            short = amount - self.usdc.balanceOf(self.wallet.address)
            if short > 0:
                self.usdc.mint(self.wallet.address, short)
            with boa.env.prank(system_address(USDC_TOKEN, self.chain_id)):
                self.wallet.systemCredit(to, amount)
        elif token == self.hype:
            self.env.set_balance(to, self.env.get_balance(to) + amount)
        else:
            self.evm_tokens[token][0].mint(to, amount)

    # --- precompiles (always from the block-start view) ---

    def _precompile(self, suffix):
        def handler(computation):
            data = computation.msg.data_as_bytes
            self._check_block()
            reply = self.replies.get((suffix, data), self.replies.get((suffix, None)))
            if reply is None:
                reply = self._answer(suffix, data)
            computation.consume_gas(_precompiles.read_gas(data, reply or b""), "HyperCore read")
            if reply is None:
                raise Revert(b"not simulated")
            computation.output = reply
            return computation

        return handler

    def _answer(self, suffix, data):
        reader = self._READERS.get(suffix)
        if reader is None:
            return None
        try:
            return reader(self, self.view, data)
        except DecodingError:
            return None  # malformed input reverts

    @staticmethod
    def _account(view, user):
        return view.accounts.get(user.lower())

    def _read_spot_balance(self, view, data):
        user, token = decode(["address", "uint64"], data)
        a = self._account(view, user)
        total, hold = a.spot.get(token, [0, 0]) if a else (0, 0)
        return encode(["uint64"] * 3, [total, hold, 0])

    def _read_vault_equity(self, view, data):
        user, vault = decode(["address", "address"], data)
        a = self._account(view, user)
        return encode(["uint64", "uint64"], a.vaults.get(vault.lower(), [0, 0]) if a else [0, 0])

    def _read_withdrawable(self, view, data):
        (user,) = decode(["address"], data)
        a = self._account(view, user)
        return encode(["uint64"], [a.perp.get(0, Perp()).withdrawable if a else 0])

    def _read_margin_summary(self, view, data):
        dex, user = decode(["uint32", "address"], data)
        a = self._account(view, user)
        p = a.perp.get(dex, Perp()) if a else Perp()
        return encode(
            ["int64", "uint64", "uint64", "int64"],
            [p.account_value, p.margin_used, p.ntl_pos, p.usd],
        )

    def _read_user_exists(self, view, data):
        (user,) = decode(["address"], data)
        return encode(["bool"], [self._account(view, user) is not None])

    def _read_l1_block(self, view, data):
        return encode(["uint64"], [view.l1_block])

    def _read_token_info(self, view, data):
        return self.tokens.get(decode(["uint64"], data)[0])

    def _read_bbo(self, view, data):
        value = view.bbo.get(decode(["uint64"], data)[0])
        return None if value is None else encode(["uint64", "uint64"], value)

    def _read_position(self, view, data):
        user, perp = decode(["address", "uint32"], data)
        position = view.positions.get((user.lower(), perp), (0, 0, 0, 0, False))
        return encode(["int64", "uint64", "int64", "uint32", "bool"], position)

    _READERS = {
        SPOT_BALANCE: _read_spot_balance,
        VAULT_EQUITY: _read_vault_equity,
        WITHDRAWABLE: _read_withdrawable,
        ACCOUNT_MARGIN_SUMMARY: _read_margin_summary,
        CORE_USER_EXISTS: _read_user_exists,
        L1_BLOCK_NUMBER: _read_l1_block,
        TOKEN_INFO: _read_token_info,
        MARK_PX: _price_reader("mark_px"),
        ORACLE_PX: _price_reader("oracle_px"),
        SPOT_PX: _price_reader("spot_px"),
        BBO: _read_bbo,
        POSITION2: _read_position,
    }
