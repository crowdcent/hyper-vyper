"""HyperCore amounts measured with transactions on mainnet and testnet.

CoreSim uses them as `Policy` defaults, and the tutorial scripts use them to
explain fees.
"""

# The activation fee: 1 USDC in perp units (6 decimals). The sender of the
# activating Core send pays it, or Core takes it from an activating deposit.
ACTIVATION_FEE_PERP = 1_000_000

# The gas of a Core -> EVM return, paid from Core spot.
RETURN_GAS_HYPE_WEI = 2_000  # 0.00002 HYPE: 200k gas at 0.1 gwei
RETURN_GAS_USDC_WEI = 92_700  # without HYPE, on testnet. Mainnet: 0.001 to 0.002 USDC.
