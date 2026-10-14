# pragma version 0.4.3
# SPDX-License-Identifier: MIT

"""
@title HyperEVM CoreWriter
@notice Typed Vyper wrappers for HyperEVM CoreWriter actions.
        CoreWriter sends actions from HyperEVM to HyperCore.
        Order and vault actions have a built-in few-second delay to prevent frontrunning.
        One action costs about 24,000 to 30,000 gas when a contract
        sends it.
@dev All functions are internal so this file can be imported as a module:

        from hyper_vyper import core_writer

        core_writer.spot_send(recipient, token_index, amount_wei)

     CoreWriter actions are asynchronous. The EVM transaction succeeds when the
     action goes into the queue, and HyperCore runs the action after the block.
     A failed Core action does not revert the EVM transaction, so read the
     result with the precompiles in a later block.

     WARNING: spot_send, send_asset, vault_transfer, delegate_token,
     approve_builder_fee and add_api_wallet move funds or authority to the
     address that you give. Never take that address from untrusted input.

     Units:
     - Token amounts (amount_wei) use the token's Core wei decimals.
     - usd_amount and ntl are perp USD with 6 decimals.
     - limit_px and sz in place_limit_order are 10**8 times the human-readable value.
     Use the conversions module to convert from EVM amounts.
"""

from . import constants
from . import precompiles

# The largest payload is a limit order: 4-byte header + 7 ABI words = 228 bytes.
MAX_ACTION_BYTES: constant(uint256) = 228

interface ICoreWriter:
    def sendRawAction(data: Bytes[MAX_ACTION_BYTES]): nonpayable


@internal
def _send(data: Bytes[MAX_ACTION_BYTES]):
    extcall ICoreWriter(constants.CORE_WRITER).sendRawAction(data)


# --- Trading ---

@internal
def place_limit_order(
    asset: uint32,
    is_buy: bool,
    limit_px: uint64,
    sz: uint64,
    reduce_only: bool,
    tif: uint8,
    cloid: uint128,
):
    """Place a limit order on HyperCore.
    tif is constants.TIF_ALO, constants.TIF_GTC or constants.TIF_IOC.
    Use cloid = 0 for no client order ID.
    limit_px and sz are 10**8 times the human-readable price and size.
    For spot markets, asset = spot_index + constants.SPOT_ASSET_OFFSET."""
    self._send(concat(
        constants.LIMIT_ORDER_HEADER,
        abi_encode(asset, is_buy, limit_px, sz, reduce_only, tif, cloid),
    ))


@internal
def cancel_order_by_oid(asset: uint32, order_id: uint64):
    """Cancel an order by its HyperCore order ID."""
    self._send(concat(
        constants.CANCEL_ORDER_BY_OID_HEADER,
        abi_encode(asset, order_id),
    ))


@internal
def cancel_order_by_cloid(asset: uint32, cloid: uint128):
    """Cancel an order by client order ID."""
    self._send(concat(
        constants.CANCEL_ORDER_BY_CLOID_HEADER,
        abi_encode(asset, cloid),
    ))


# --- Vault ---

@internal
def vault_transfer(vault: address, is_deposit: bool, usd_amount: uint64):
    """Deposit or withdraw USDC from a HyperCore vault. usd_amount is in perp USD (6 decimals).
    The deposit comes from the perp balance and shows after a few seconds. Each
    deposit starts a lock (4 days for HLP). A withdrawal reverts while the vault
    lock of this contract is active.
    WARNING: moves funds to the given vault. Never take it from untrusted input."""
    if not is_deposit:
        equity: precompiles.UserVaultEquity = precompiles.user_vault_equity(self, vault)
        # Match the strict boundary of the Solidity library. Core timestamps are milliseconds.
        # Computed inline so that core_writer does not import conversions.
        timestamp_ms: uint64 = convert(block.timestamp, uint64) * 1000
        assert timestamp_ms > equity.locked_until_timestamp, "Vault withdrawal locked"
    self._send(concat(
        constants.VAULT_TRANSFER_HEADER,
        abi_encode(vault, is_deposit, usd_amount),
    ))


# --- Transfers ---

@internal
def spot_send(to: address, token: uint64, amount_wei: uint64):
    """Send spot tokens to another address on HyperCore.
    A send to the system address of a token bridges it back to EVM.
    Reverts for a send to this contract, because Core always rejects it.
    A send to an account that is not activated fails unless it is 1 USDC or more.
    In unified account mode, Core refuses a user-signed spotSend but accepts a
    CoreWriter spot_send. send_asset is the general transfer, and the library
    uses it for every route.
    The address warning in the module docstring applies."""
    assert to != self, "Self transfer"
    self._send(concat(
        constants.SPOT_SEND_HEADER,
        abi_encode(to, token, amount_wei),
    ))


@internal
def send_asset(
    destination: address,
    sub_account: address,
    source_dex: uint32,
    destination_dex: uint32,
    token: uint64,
    amount_wei: uint64,
):
    """Move an asset between DEXes and addresses on HyperCore.
    Use constants.SPOT_DEX (max uint32) for spot and constants.DEFAULT_PERP_DEX (0)
    for the default perp DEX.
    The address warning in the module docstring applies."""
    self._send(concat(
        constants.SEND_ASSET_HEADER,
        abi_encode(destination, sub_account, source_dex, destination_dex, token, amount_wei),
    ))


@internal
def transfer_usd_class(ntl: uint64, to_perp: bool):
    """Move USDC between the spot and perp balances. ntl is in perp USD (6 decimals).
    In unified account or portfolio margin mode, balance reads can show perp
    funds through spot, so read both balances to check the result. See
    set_abstraction."""
    self._send(concat(
        constants.USD_CLASS_TRANSFER_HEADER,
        abi_encode(ntl, to_perp),
    ))


# --- Staking ---

@internal
def staking_deposit(amount_wei: uint64):
    """Move HYPE from spot to the staking balance. It shows in the next block."""
    self._send(concat(
        constants.STAKING_DEPOSIT_HEADER,
        abi_encode(amount_wei),
    ))


@internal
def staking_withdraw(amount_wei: uint64):
    """Withdraw undelegated HYPE from the staking balance to spot. The HYPE waits in
    a 7-day unstaking queue, and an address can have at most 5 pending
    withdrawals. A withdrawal above the undelegated balance fails silently."""
    self._send(concat(
        constants.STAKING_WITHDRAW_HEADER,
        abi_encode(amount_wei),
    ))


@internal
def delegate_token(validator: address, amount_wei: uint64, undelegate: bool):
    """Delegate or undelegate HYPE to a validator.
    A delegation is locked for 1 day (Delegation.locked_until_timestamp). An
    undelegation during the lock fails silently.
    The address warning in the module docstring applies."""
    self._send(concat(
        constants.TOKEN_DELEGATE_HEADER,
        abi_encode(validator, amount_wei, undelegate),
    ))


# --- Builder / API ---

@internal
def approve_builder_fee(max_fee_rate: uint64, builder: address):
    """Approve a builder fee. max_fee_rate is in decibps (1 decibps = 0.001%).
    Core ignores the approval silently unless the builder has at least 100 USDC
    of perp account value. Spot USDC of a unified account does not count. A rate
    of 0 removes the approval.
    The address warning in the module docstring applies."""
    self._send(concat(
        constants.APPROVE_BUILDER_FEE_HEADER,
        abi_encode(max_fee_rate, builder),
    ))


@internal
def add_api_wallet(wallet: address, name: String[32]):
    """Add or replace an API wallet (Hyperliquid also calls it an agent). An empty
    name selects the unnamed API wallet. The function does not remove a wallet.
    The change takes effect in the next block, and Core then refuses the replaced
    address. An API wallet added this way expires after 90 days (validUntil in the
    info API request extraAgents). The unnamed one does not show in extraAgents,
    so query userRole for its address.
    WARNING: the API wallet can trade with the whole Core account of this
    contract, so never take its address from untrusted input. It stays active when
    you pause the EVM contract. To revoke it, replace it with a new address under
    the same name. Never reuse a replaced address, because Hyperliquid can prune
    its nonce state and old signed actions could then replay."""
    self._send(concat(
        constants.ADD_API_WALLET_HEADER,
        abi_encode(wallet, name),
    ))


# --- Token deployment ---

@internal
def finalize_evm_contract(token: uint64, encoded_variant: uint8, create_nonce: uint64):
    """Finalize the link between a HyperCore token and its EVM contract."""
    self._send(concat(
        constants.FINALIZE_EVM_CONTRACT_HEADER,
        abi_encode(token, encoded_variant, create_nonce),
    ))


# --- Borrow/Lend ---

@internal
def borrow_lend(operation: uint8, token: uint64, amount_wei: uint64):
    """Supply to or withdraw from borrow/lend.
    operation is constants.BLP_SUPPLY or constants.BLP_WITHDRAW.
    WARNING: amount_wei = 0 means the maximum amount (Hyperliquid protocol
    semantics). A computed amount that rounds down to 0 moves the whole balance.
    Validate the amount in your contract before you call this function."""
    self._send(concat(
        constants.BORROW_LEND_HEADER,
        abi_encode(operation, token, amount_wei),
    ))


# --- Account abstraction ---

@internal
def set_abstraction(user: address, abstraction: uint8):
    """Set the account abstraction mode.
    abstraction is constants.ABSTRACTION_DISABLED, constants.ABSTRACTION_UNIFIED_ACCOUNT
    or constants.ABSTRACTION_PORTFOLIO_MARGIN.
    user can be the master user or a sub-account. The info API request
    userAbstraction returns "default" for an account with no mode set, or
    "disabled", "unifiedAccount" or "portfolioMargin". A switch to unified account
    mode moves the perp USDC to spot, and a switch back does not move it back.
    Core ignores portfolio margin unless the account has 10,000 USD of account
    value or 5,000,000 USD of trading volume. In unified account mode, balance
    reads can show perp funds through spot. No precompile reads the current mode.
    Call set_abstraction(self, constants.ABSTRACTION_DISABLED) once after
    activation, check the mode off-chain, and use send_asset for transfers."""
    self._send(concat(
        constants.SET_ABSTRACTION_HEADER,
        abi_encode(user, abstraction),
    ))
