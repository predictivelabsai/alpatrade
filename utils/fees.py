"""
Regulatory trading fee calculations.

FINRA TAF and CAT fees applied to equity trades.
"""
import numpy as np


def calculate_finra_taf_fee(shares: int) -> float:
    """
    Calculate FINRA Trading Activity Fee (TAF) for a sell order.

    TAF: $0.000166 per share (sells only)
    - Rounded up to nearest penny
    - Capped at $8.30 per trade

    Args:
        shares: Number of shares being sold

    Returns:
        Fee amount in dollars
    """
    if shares <= 0:
        return 0.0

    fee_per_share = 0.000166
    raw_fee = shares * fee_per_share

    # Round up to nearest penny
    fee = np.ceil(raw_fee * 100) / 100

    # Cap at $8.30
    fee = min(fee, 8.30)

    return fee


def calculate_cat_fee(shares: int) -> float:
    """
    Calculate Consolidated Audit Trail (CAT) fee for a trade.

    CAT Fee: $0.0000265 per share (applies to both buys and sells)
    For NMS Equities: 1:1 ratio.

    Args:
        shares: Number of shares being traded

    Returns:
        Fee amount in dollars
    """
    if shares <= 0:
        return 0.0

    fee_per_share = 0.0000265
    fee = shares * fee_per_share

    return fee
