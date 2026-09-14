"""Backfills the catalog/freshness columns (brand_name, part_de/en, source,
vehicle_brand) for rows that predate them:

    python backfill_columns.py
"""

from dotenv import load_dotenv

from database import SessionLocal, Deal
from parts_catalog import find_part_in_text
from brand_names import extract_part_brand, car_makes_in_title

load_dotenv()


def _source(product_id: str) -> str:
    pid = product_id or ""
    if pid.startswith("autodoc_") or pid.startswith("live_") or pid.startswith("DEMO-"):
        return "autodoc"
    if pid.startswith("ebay"):
        return "ebay"
    return ""


def main():
    db = SessionLocal()
    try:
        rows = db.query(Deal).all()
        changed = 0
        for row in rows:
            src = row.source or _source(row.product_id)
            brand = row.brand_name or extract_part_brand(row.source_url or "", row.title or "")
            part = None
            if not (row.part_de and row.part_en):
                part = find_part_in_text(row.title or "")
            part_de = row.part_de or (part["de"] if part else None)
            part_en = row.part_en or (part["en"] if part else None)
            vbrand = row.vehicle_brand or (car_makes_in_title(row.title or "") if src == "ebay" else "")

            if (src != row.source or brand != row.brand_name
                    or part_de != row.part_de or part_en != row.part_en
                    or vbrand != row.vehicle_brand):
                row.source = src or row.source
                row.brand_name = brand or row.brand_name
                row.part_de = part_de or row.part_de
                row.part_en = part_en or row.part_en
                row.vehicle_brand = vbrand or row.vehicle_brand
                changed += 1
        db.commit()
        print(f"backfilled columns for {changed}/{len(rows)} deals")
    finally:
        db.close()


if __name__ == "__main__":
    main()