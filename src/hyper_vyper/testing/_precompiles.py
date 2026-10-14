"""The HyperCore read precompiles, as CoreSim and forward_precompiles register them."""

from boa.vm.py_evm import deregister_raw_precompile, register_raw_precompile

# Address suffixes of the read precompiles, named as in constants.vy.
POSITION = 0x800  # legacy, the library reads POSITION2
SPOT_BALANCE = 0x801
VAULT_EQUITY = 0x802
WITHDRAWABLE = 0x803
DELEGATIONS = 0x804
DELEGATOR_SUMMARY = 0x805
MARK_PX = 0x806
ORACLE_PX = 0x807
SPOT_PX = 0x808
L1_BLOCK_NUMBER = 0x809
PERP_ASSET_INFO = 0x80A
SPOT_INFO = 0x80B
TOKEN_INFO = 0x80C
TOKEN_SUPPLY = 0x80D
BBO = 0x80E
ACCOUNT_MARGIN_SUMMARY = 0x80F
CORE_USER_EXISTS = 0x810
BORROW_LEND_USER_STATE = 0x811
BORROW_LEND_RESERVE_STATE = 0x812
POSITION2 = 0x813

SUFFIXES = range(POSITION, POSITION2 + 1)


def address(suffix: int) -> str:
    return f"0x{suffix:040x}"


def read_gas(data: bytes, reply: bytes) -> int:
    """The approximate gas of one HyperCore read."""
    return 2000 + 65 * (len(data) + len(reply))


def register(make_handler) -> None:
    """Register make_handler(suffix) at every read precompile."""
    for suffix in SUFFIXES:
        register_raw_precompile(address(suffix), make_handler(suffix), force=True)


def deregister() -> None:
    for suffix in SUFFIXES:
        deregister_raw_precompile(address(suffix), force=True)
