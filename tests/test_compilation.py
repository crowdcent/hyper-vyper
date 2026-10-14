"""Verify that unrelated internal library modules do not enlarge a consumer."""

import boa


def test_unused_modules_do_not_change_runtime_bytecode():
    consumer = """
# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
from hyper_vyper import precompiles

@external
@view
def core_balance() -> uint64:
    return precompiles.spot_balance(self, 0).total
"""
    with_unused = consumer.replace(
        "from hyper_vyper import precompiles",
        "from hyper_vyper import precompiles\nfrom hyper_vyper import bridge\nfrom hyper_vyper import core_writer\nfrom hyper_vyper import conversions",
    )
    minimal = boa.loads_partial(consumer).compiler_data.bytecode_runtime
    expanded = boa.loads_partial(with_unused).compiler_data.bytecode_runtime
    assert minimal == expanded
