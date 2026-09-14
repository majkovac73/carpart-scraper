"""Re-aligns previously-stored eBay rows with the current quality rules:

  - rows whose title now trips the junk token filter / part gate are deleted;
  - unbranded rows under the price floor that were wrongly promoted to "pending"
    during the first catalog sweep are demoted to "catalog" (still searchable).

    python prune_ebay_rows.py
"""

from dotenv import load_dotenv

from database import SessionLocal, Deal, deal_model_association, DealClick
from ebay_scraper import _reject_junk, title_matches_any_part, _PARTS_FLOOR
from brand_names import title_has_part_brand

load_dotenv()


def main():
    db = SessionLocal()
    try:
        rows = db.query(Deal).filter(Deal.product_id.like("ebay%")).all()
        deleted = demoted = 0
        for d in rows:
            title = d.title or ""
            brand = title_has_part_brand(title)
            price = d.sale_price if d.sale_price is not None else 0
            quality = brand or price >= _PARTS_FLOOR

            if _reject_junk(title) or not title_matches_any_part(title):
                db.query(deal_model_association).filter(
                    deal_model_association.c.deal_id == d.id).delete()
                db.query(DealClick).filter(DealClick.deal_id == d.id).delete()
                db.delete(d)
                deleted += 1
                continue

            if not quality and d.status != "catalog":
                d.status = "catalog"
                d.discount_percentage = 0.0
                demoted += 1
        db.commit()
        print(f"pruned {len(rows)} eBay rows -> deleted {deleted}, demoted {demoted}")
    finally:
        db.close()


if __name__ == "__main__":
    main()