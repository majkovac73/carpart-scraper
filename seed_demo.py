"""
Dev tool: fills deals.db with a few example deals so you can see the website
and the Telegram dry-run before the first real scraping run.

IDs use the DEMO- prefix so real scans can never collide with them. The
products themselves were scraped from Autodoc live (real product links and
part photos), so every demo deal opens the actual product page.

Usage:
    python seed_demo.py              # refresh the DEMO-* deals
    python seed_demo.py --wipe       # delete ALL deals first, then seed
"""

import argparse

from database import SessionLocal, Deal, deal_model_association
from crud import create_deal, get_deal_by_product_id

DEMO_DEALS = [
    {
        "product_id": "DEMO-0001",
        "title": "Genuine BMW Brake Disc Front Axle 260x22mm BMW 3 Series (E46)",
        "title_en": "Genuine BMW Brake Disc Front Axle 260x22mm BMW 3 Series (E46)",
        "sale_price": 84.26, "retail_price": None, "average_price": 126.93,
        "discount_percentage": 33.6,
        "image_url": "https://cdn.autodoc.de/thumb?id=26474310&m=2&n=0&lng=de&rev=94078092",
        "source_url": "https://www.autodoc.de/bmw/26474310",
        "compatible_vehicles": [{"brand": "BMW", "model": "E46"}],
    },
    {
        "product_id": "DEMO-0002",
        "title": "Genuine BMW Brake Pads Rear Axle BMW 3 Series (E46)",
        "title_en": "Genuine BMW Brake Pads Rear Axle BMW 3 Series (E46)",
        "sale_price": 69.53, "retail_price": None, "average_price": 107.72,
        "discount_percentage": 35.5,
        "image_url": "https://cdn.autodoc.de/thumb?id=27364165&m=2&n=0&lng=de&rev=94078092",
        "source_url": "https://www.autodoc.de/bmw/27364165",
        "compatible_vehicles": [{"brand": "BMW", "model": "E46"}],
    },
    {
        "product_id": "DEMO-0003",
        "title": "MANN-FILTER Oil Filter W 712/75 VW Golf 7 / Audi A3 8V",
        "title_en": "MANN-FILTER Oil Filter W 712/75 VW Golf 7 / Audi A3 8V",
        "sale_price": 6.59, "retail_price": None, "average_price": 9.46,
        "discount_percentage": 30.3,
        "image_url": "https://media.autodoc.de/360_photos/963599/h-preview.jpg",
        "source_url": "https://www.autodoc.de/mann-filter/963599",
        "compatible_vehicles": [
            {"brand": "VW", "model": "Golf 7"},
            {"brand": "Audi", "model": "A3 8V"},
        ],
    },
    {
        "product_id": "DEMO-0004",
        "title": "RIDEX Spark Plug Set for Mercedes C-Class (W204)",
        "title_en": "RIDEX Spark Plug Set for Mercedes C-Class (W204)",
        "sale_price": 2.29, "retail_price": None, "average_price": 9.17,
        "discount_percentage": 75.0,
        "image_url": "https://media.autodoc.de/360_photos/8315422/preview.jpg",
        "source_url": "https://www.autodoc.de/ridex/8315422",
        "compatible_vehicles": [{"brand": "Mercedes-Benz", "model": "W204"}],
    },
    {
        "product_id": "DEMO-0005",
        "title": "BILSTEIN B8 Shock Absorber Rear Gas Audi A4 B8",
        "title_en": "BILSTEIN B8 Shock Absorber Rear Gas Audi A4 B8",
        "sale_price": 97.49, "retail_price": None, "average_price": 159.58,
        "discount_percentage": 38.9,
        "image_url": "https://media.autodoc.de/360_photos/636551/h-preview.jpg",
        "source_url": "https://www.autodoc.de/bilstein/636551",
        "compatible_vehicles": [{"brand": "Audi", "model": "A4 B8"}],
    },
    {
        "product_id": "DEMO-0006",
        "title": "Genuine BMW Air Filter BMW 1 Series (E87)",
        "title_en": "Genuine BMW Air Filter BMW 1 Series (E87)",
        "sale_price": 39.85, "retail_price": None, "average_price": 56.25,
        "discount_percentage": 29.2,
        "image_url": "https://cdn.autodoc.de/thumb?id=26472136&m=2&n=0&lng=de&rev=94078092",
        "source_url": "https://www.autodoc.de/bmw/26472136",
        "compatible_vehicles": [{"brand": "BMW", "model": "E87"}],
    },
    {
        "product_id": "DEMO-0007",
        "title": "RIDEX Oil Filter Chevrolet Cruze 1.7 / 2.0 VCDi",
        "title_en": "RIDEX Oil Filter Chevrolet Cruze 1.7 / 2.0 VCDi",
        "sale_price": 1.99, "retail_price": None, "average_price": 7.92,
        "discount_percentage": 74.9,
        "image_url": "https://media.autodoc.de/360_photos/8097412/h-preview.jpg",
        "source_url": "https://www.autodoc.de/ridex/8097412",
        "compatible_vehicles": [{"brand": "Chevrolet", "model": "Cruze"}],
    },
]


def main():
    parser = argparse.ArgumentParser(description="Seed demo deals")
    parser.add_argument("--wipe", action="store_true", help="delete all deals first")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.wipe:
            db.execute(deal_model_association.delete())
            db.query(Deal).delete()
            db.commit()
            print("all deals wiped.")

        # Refresh demo rows: drop previous DEMO-* so price/link/image updates apply.
        stale = db.query(Deal).filter(Deal.product_id.like("DEMO-%")).all()
        for r in stale:
            db.execute(deal_model_association.delete().where(
                deal_model_association.c.deal_id == r.id))
            db.delete(r)
        db.commit()
        print(f"removed {len(stale)} stale demo deals.")

        count = 0
        for d in DEMO_DEALS:
            create_deal(db, **d)
            count += 1
        print(f"seeded {count} demo deals.")
    finally:
        db.close()


if __name__ == "__main__":
    main()