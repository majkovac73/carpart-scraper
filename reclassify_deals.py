"""Re-applies the CURRENT deal definition (is_worth_deal) to every stored row.

  * Rows that no longer qualify are demoted to catalog (searchable, never
    broadcast) with discount_percentage reset to 0.
  * Catalog rows that now qualify are promoted to "pending" deals so the
    corrected sweep can surface genuinely discounted branded parts.

    python reclassify_deals.py
"""

import os

from dotenv import load_dotenv

from database import SessionLocal, Deal, deal_model_association, DealClick
from deal_filter import is_worth_deal
from brand_names import title_has_part_brand

load_dotenv()


def _deal_check(d, min_discount, min_saved, ebay_min_price, autodoc_min_price):
    if d.source == "ebay":
        min_price, requires_brand = ebay_min_price, True
    else:
        min_price, requires_brand = autodoc_min_price, False
    if requires_brand and not title_has_part_brand(d.title or ""):
        return False, 0.0
    is_deal, pct, _base = is_worth_deal(
        d.sale_price, d.average_price, d.retail_price,
        min_discount=min_discount, min_price=min_price, min_saved=min_saved,
    )
    return is_deal, pct


def main():
    min_discount = float(os.getenv("MIN_DISCOUNT", "15"))
    min_saved = float(os.getenv("DEAL_MIN_SAVED", "6"))
    ebay_min_price = float(os.getenv("EBAY_DEAL_MIN_PRICE", "12"))
    autodoc_min_price = float(os.getenv("AUTODOC_DEAL_MIN_PRICE", "8"))

    db = SessionLocal()
    try:
        active = db.query(Deal).filter(Deal.status.notin_(["catalog", "search"])).all()
        promoted = demoted = 0
        for d in active:
            is_deal, pct = _deal_check(d, min_discount, min_saved,
                                       ebay_min_price, autodoc_min_price)
            if is_deal:
                d.discount_percentage = pct
                continue
            d.status = "catalog"
            d.discount_percentage = 0.0
            demoted += 1

        catalog = db.query(Deal).filter(Deal.status == "catalog").all()
        for d in catalog:
            is_deal, pct = _deal_check(d, min_discount, min_saved,
                                       ebay_min_price, autodoc_min_price)
            if is_deal:
                d.status = "pending"
                d.discount_percentage = pct
                promoted += 1

        db.commit()

        from collections import Counter
        statuses = Counter(s for (s,) in db.query(Deal.status).all())
        prints = []
        prints.append(f"active revisited: {len(active)}  demoted -> {demoted}")
        prints.append(f"catalog revisited: {len(catalog)}  promoted -> {promoted}")
        prints.append("statuses: %s" % dict(statuses))
        print("\n".join(prints))
    finally:
        db.close()


if __name__ == "__main__":
    main()