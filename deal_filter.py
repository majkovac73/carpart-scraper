"""
Phase 3.2 - Deal Filter (vs. market average)

A product is worth posting as a DEAL when it meets BOTH a genuine discount
proof AND a minimum absolute value, so cheap junk never leaks into the feed:

  Proof A (seller-marked): the listing itself advertises a discount off its
                           own RRP (Autodoc list price / eBay marketingPrice).
  Proof B (peer discount): the price is >= min_discount below the market
                           average of the same batch (same part, same car).

On top of both proofs the product must cost at least `min_price` and save at
least `min_saved` EUR in absolute terms. eBay additionally requires a known
part brand (generic no-name parts are almost never real deals).

Everything scraped is still indexed as a catalog row; only `is_worth_deal()`
decides promotion to "pending"/broadcast.
"""

MIN_OFF_AVERAGE_DEFAULT = 15.0


def is_worth_deal(
    sale_price,
    average_price,
    retail_price,
    *,
    min_discount: float = MIN_OFF_AVERAGE_DEFAULT,
    min_price: float = 0.0,
    min_saved: float = 0.0,
) -> tuple:
    """True when the product is a real deal worth broadcasting.

    Returns (is_deal, discount_percentage, selected_base) where
    selected_base is "rrp" (seller's own discount) or "avg" (peer discount)
    and discount_percentage is the percent the pct was computed from."""
    try:
        sale = float(sale_price or 0)
    except (TypeError, ValueError):
        return False, 0.0, None
    if sale <= 0:
        return False, 0.0, None
    if min_price and sale < min_price:
        return False, 0.0, None

    # Proof A: seller-marked discount off its own RRP.
    try:
        retail = float(retail_price or 0)
    except (TypeError, ValueError):
        retail = 0.0
    if retail > sale:
        saved = retail - sale
        if saved >= min_saved and saved / retail * 100 >= min_discount:
            return True, round(saved / retail * 100, 1), "rrp"

    # Proof B: strong discount vs the peer/market average.
    try:
        avg = float(average_price or 0)
    except (TypeError, ValueError):
        avg = 0.0
    if avg > sale:
        saved = avg - sale
        if saved >= min_saved and saved / avg * 100 >= min_discount:
            return True, round(saved / avg * 100, 1), "avg"

    return False, 0.0, None


def calculate_discount_percentage(retail_price, sale_price) -> float:
    """((retail - sale) / retail) * 100. Kept for display/information only."""
    try:
        retail = float(retail_price)
        sale = float(sale_price)
    except (TypeError, ValueError):
        return 0.0

    if retail > 0 and 0 < sale < retail:
        return round(((retail - sale) / retail) * 100, 1)
    return 0.0


def off_average_percentage(avg_price: float, sale_price: float) -> float:
    """Percent the sale price is below the market average. 0 for at/above market."""
    try:
        avg = float(avg_price)
        sale = float(sale_price)
    except (TypeError, ValueError):
        return 0.0

    if avg > 0 and 0 < sale < avg:
        return round(((avg - sale) / avg) * 100, 1)
    return 0.0


def average_price(deals: list):
    """Mean sale price of the group. Items without a valid price are ignored."""
    prices = []
    for deal in deals:
        try:
            price = float(deal.get("sale_price") or 0)
        except (TypeError, ValueError):
            continue
        if price > 0:
            prices.append(price)

    if not prices:
        return None
    return sum(prices) / len(prices)


def filter_deals_by_average(
    deals: list,
    avg_price: float = None,
    min_discount: float = MIN_OFF_AVERAGE_DEFAULT,
) -> list:
    """Keeps only products priced >= min_discount below the group average.

    When avg_price is omitted it is computed from the batch itself. Passing
    deals adds off_average_percentage / average_price / discount_percentage
    (all meaning "% below market average").
    """
    if avg_price is None:
        avg_price = average_price(deals)

    if not avg_price or avg_price <= 0:
        return []

    passed = []
    for deal in deals:
        try:
            sale = float(deal.get("sale_price") or 0)
        except (TypeError, ValueError):
            continue
        if sale <= 0:
            continue

        title = (deal.get("title") or deal.get("clean_title") or "").strip()
        if len(title) < 5:
            continue

        off = off_average_percentage(avg_price, sale)
        if off >= min_discount:
            enriched = dict(deal)
            enriched["off_average_percentage"] = off
            enriched["average_price"] = round(avg_price, 2)
            enriched["discount_percentage"] = off
            passed.append(enriched)

    return passed