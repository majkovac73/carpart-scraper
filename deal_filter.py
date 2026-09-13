"""
Phase 3.2 - Deal Filter (vs. market average)

A "deal" is defined relative to the MARKET, not the listing's own RRP:
  - Autodoc: the average price of all products found in the SAME search
    (same part + car), e.g. "BMW E46 Bremsscheiben".
  - eBay:    the average price of all results for the SAME part keyword,
    e.g. all "Bremsbeläge" results regardless of car.

A product is worth posting when its price is at least `min_discount`
(default 15%) BELOW that average. Deeper discounts are always better -
nothing is cut off at the top. The RRP-based discount no longer gates
deals; it is kept only for information/display.
"""

MIN_OFF_AVERAGE_DEFAULT = 15.0


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