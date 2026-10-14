# pragma version 0.4.3
# pragma evm-version cancun
# pragma optimize gas
# SPDX-License-Identifier: MIT

"""
@title Core balance reader
@notice Reads the Core spot USDC balance of any address through a precompile.
"""

from hyper_vyper import constants
from hyper_vyper import precompiles


@external
@view
def core_usdc_balance(user: address) -> uint64:
    """Core spot total in 8-decimal USDC units, including held funds."""
    balance: precompiles.SpotBalance = precompiles.spot_balance(user, constants.USDC_TOKEN_INDEX)
    return balance.total
