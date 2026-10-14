# 5. Place spot and perp orders

In this tutorial a contract trades on HyperCore. It buys and sells HYPE on spot,
and opens and closes a small BTC perp position. It sends immediate-or-cancel
(IOC) limit orders with `core_writer.place_limit_order`, and the script picks a
valid price and size from the order book.

You'll learn:

- How asset IDs work: 10000 plus the market index on spot (11035 for market
  1035), and the perp index on perps (3 for BTC on testnet).
- Why `limit_px` and `sz` are `10**8` times the human values, and how to round
  them to a valid tick and lot above the 10 USDC minimum.
- How to read a perp position through `precompiles.position`, and close it
  with a reduce-only order.

## Prerequisites

| Item | Amount |
|---|---|
| HYPE on HyperEVM | less than 0.003 HYPE for gas |
| USDC in the spot balance of your Core account | 19 USDC: 18 USDC to the contract and 1 USDC activation fee |
| `HYPER_VYPER_TESTNET_KEY` | for all steps with `--execute` |
| `HYPER_VYPER_CORE_FUNDER_KEY` | optional, for the fund step |

Each order pays a trading fee of a few cents.

## Order rules

The script takes these rules from the
[Hyperliquid documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size)
and from the market metadata:

| Rule | HYPE/USDC on testnet |
|---|---|
| Size decimals (`sz_decimals` of HYPE) | 2: sizes like `0.24` |
| Price | At most 5 significant figures and at most `8 - sz_decimals` = 6 decimals |
| Minimum order value | 10 USDC |
| CoreWriter encoding | `limit_px` and `sz` are `10**8` times the human value |

These rules apply to the BTC perp on testnet:

| Rule | BTC perp on testnet |
|---|---|
| Size decimals (`sz_decimals` of BTC) | 5: sizes like `0.00013` |
| Price | At most 5 significant figures and at most `6 - sz_decimals` = 1 decimal |
| Minimum order value | 10 USD |
| `mark_px` precompile | Divide by `10**(6 - sz_decimals)` |
| `position` precompile | `szi` in units of `10**-sz_decimals`: `13` is 0.00013 BTC |

For a buy, the script takes the best ask, adds the slippage (default 1%) and
rounds **up** to a valid tick. It then divides the USDC budget by the limit
price and rounds the size **down** to the lot size. For a sell, it takes the
best bid, subtracts the slippage and rounds **down**. The `order` function in
[`tutorials/spot_order/run.py`](https://github.com/crowdcent/hyper-vyper/blob/main/tutorials/spot_order/run.py)
does this.

## The contract

```vyper
--8<-- "tutorials/spot_order/spot_order.vy"
```

- The markets are constants: spot index 1035 (asset 11035) and perp 3 (BTC).
  Never take an asset from untrusted input.
- `place_ioc` and `place_perp_ioc` run only on chain 998, because the indices
  are testnet indices.
- `market` and `perp_market` let the script compare the on-chain markets with
  the info API before it sends.
- `move_usdc` moves margin between spot and perp, as in
  [tutorial 3](spot-perp.md).
- `place_perp_ioc` takes `reduce_only`. The close step sets it, so the order
  can only make the position smaller.

## Steps

1. Deploy the contract:

    ```bash
    uv run --locked tutorials/spot_order/run.py deploy --execute
    ```

2. Fund the contract with 18 USDC on Core. This send also activates it:

    ```bash
    uv run --locked tutorials/spot_order/run.py fund --execute
    ```

3. Show the buy plan. This step runs the order on a local copy of the chain
   and sends nothing:

    ```bash
    uv run --locked tutorials/spot_order/run.py buy --usdc 12
    ```

    ```text
    market @1035: tokens [1105, 0], HYPE sz_decimals 2
    order: IOC buy 0.25 HYPE at limit 47.390 (best 46.92)
      encoded: limit_px 4739000000, sz 25000000 (x 10**8)
      value at the limit: 11.84750 USDC
    plan: place_ioc(True, 4739000000, 25000000) value 0
    plan only: add --execute to send. Nothing was sent.
    ```

    Check the numbers: 46.92 x 1.01 = 47.3892, and the next valid tick up is
    47.390 (5 significant figures). 12 / 47.390 = 0.253..., which rounds down
    to 0.25.

4. Buy:

    ```bash
    uv run --locked tutorials/spot_order/run.py buy --usdc 12 --execute
    ```

    ```text
    sent place_ioc: 0x... in block N
      block N+8: spot HYPE 0.249825, USDC 6.27
    filled: spot HYPE 24982500 (0.249825 HYPE, 8 decimals)
            spot USDC -1173000000 (-11.73 USDC, 8 decimals)
    ```

    The order filled at 46.92 USDC per HYPE, below the limit. Core takes the buy
    fee from the HYPE that you receive, so you get a little less than 0.25 HYPE.

5. Sell as much HYPE as the size rules allow:

    ```bash
    uv run --locked tutorials/spot_order/run.py sell --execute
    ```

    ```text
    order: IOC sell 0.24 HYPE at limit 45.626 (best 46.087)
      encoded: limit_px 4562600000, sz 24000000 (x 10**8)
      value at the limit: 10.95024 USDC
    sent place_ioc: 0x... in block N
      block N+8: spot HYPE 0.009825, USDC 17.32313739
    filled: spot HYPE -24000000 (-0.24 HYPE, 8 decimals)
            spot USDC 1105313739 (11.05313739 USDC, 8 decimals)
    ```

    The script rounds 0.249825 down to 0.24, and the rest stays on spot.

6. Move 3 USDC to perp as margin:

    ```bash
    uv run --locked tutorials/spot_order/run.py to-perp --amount 3 --execute
    ```

7. Open a BTC long worth about 11 USD:

    ```bash
    uv run --locked tutorials/spot_order/run.py perp-open --usd 11 --execute
    ```

    ```text
    perp BTC (asset 3): sz_decimals 5, max leverage 40
    order: IOC buy 0.00013 BTC at limit 83978 (best 83146.0)
      encoded: limit_px 8397800000000, sz 13000 (x 10**8)
      value at the limit: 10.91714 USD
    plan: place_perp_ioc(True, 8397800000000, 13000, False) value 0
    sent place_perp_ioc: 0x... in block N
      block N+8: BTC szi 13
    position: szi 13 (0.00013 BTC), entry notional 10808980 (10.80898 USD, 6 decimals)
      info API: BTC szi 0.00013
    ```

    The precompile and the info API show the same position.

8. Close the whole position with a reduce-only sell:

    ```bash
    uv run --locked tutorials/spot_order/run.py perp-close --execute
    ```

    ```text
    order: IOC sell (reduce-only) 0.00013 BTC at limit 82313 (best 83145.0)
      encoded: limit_px 8231300000000, sz 13000 (x 10**8)
      value at the limit: 10.70069 USD
    plan: place_perp_ioc(False, 8231300000000, 13000, True) value 0
    sent place_perp_ioc: 0x... in block N
      block N+8: BTC szi 0
    position: szi 0 (0 BTC), entry notional 0 (0 USD, 6 decimals)
    The position is closed.
    ```

9. Move the margin back to spot:

    ```bash
    uv run --locked tutorials/spot_order/run.py to-spot --execute
    ```

    ```text
    move 2990143 (2.990143 USD, 6 decimals) perp -> spot
    ```

    The margin is a little less than 3 USD because of the trading fees.

## What can go wrong

- **`The order value is below 10 USDC`.** The price fell, or the budget is too
  small, so use a larger `--usdc`. For the sell, the HYPE that you bought must
  be worth 10 USDC or more at the limit. If it is not, buy with `--usdc 14`.
- **No fill.** The IOC order did not match before Core canceled it, or Core
  rejected it. Both cases are silent and the EVM transaction still succeeds.
  Run the step again, or increase `--slippage` when the testnet book is thin.
- **A wrong scale.** CoreWriter uses `10**8` for price and size. The price
  precompiles use other scales, so don't pass their values to
  `place_limit_order` directly.
- **`Perp has no margin`.** Run the to-perp step before you open a position.
- **`Close the BTC position first`.** The to-spot step moves only free margin.
- **Mainnet.** The spot index 1035 and the perp index 3 are testnet indices,
  and the markets have other indices on mainnet. The contract refuses other
  chains.

## Clean up

Send the remaining Core USDC and HYPE to the owner on Core:

```bash
uv run --locked tutorials/spot_order/run.py sweep --execute
```
