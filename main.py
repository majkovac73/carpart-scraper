"""
Deal discovery pipeline (Phase 1-3 wired together).

Finds discounted automotive parts for DIFFERENT cars:
  - Autodoc: searches a part per specific car (brand + model) via Playwright.
  - eBay:    searches generic part keywords inside the Vehicle Parts & Accessories
             category (no specific car), sorts by lowest price.
Each scraped deal is compared against the MARKET AVERAGE price of its search:
a product is a deal when it is >= min_discount (default 15%) cheaper than that
average (Autodoc: same search batch; eBay: same part keyword). Deals are then
cleaned by the LLM engine (Gemini or local fallback), deduplicated against the
database and persisted as a "pending" Deal ready for Telegram / website
distribution.

Usage:
    python main.py                    # full run, persist to deals.db
    python main.py --dry-run          # scrape + filter but do not write to DB
    python main.py --min-discount 0   # keep every valid item, not only >=15%
"""

import argparse
import os

from dotenv import load_dotenv

from database import SessionLocal
from crud import get_deal_by_product_id, create_deal
from autodoc_scraper import search_autodoc_part
from ebay_scraper import fetch_ebay_deals
from llm_engine import clean_deals
from deal_filter import filter_deals_by_average
from deals_format import format_deal_message
from translate_parts import to_english_title
from affiliate import affiliate_link_for_url

load_dotenv()

# Cars the pipeline hunts parts for. Add / remove models freely.
TARGET_VEHICLES = [
    {"part": "Bremsscheiben", "brand": "BMW", "model": "E46"},
    {"part": "Stoßdämpfer",   "brand": "BMW", "model": "E46"},
    {"part": "Bremsbeläge",   "brand": "BMW", "model": "E87"},
    {"part": "Bremsbeläge",   "brand": "VW",  "model": "Golf 6"},
    {"part": "Ölfilter",      "brand": "VW",  "model": "Golf 6"},
    {"part": "Bremsscheiben", "brand": "Mercedes-Benz", "model": "W204"},
    {"part": "Zündkerzen",    "brand": "Audi", "model": "A4 B8"},
    {"part": "Bremsbeläge",   "brand": "Audi", "model": "A4 B8"},
    {"part": "Ölfilter",      "brand": "Chevrolet", "model": "Cruze"},
]

# Generic keywords: found cheap in the Vehicle Parts category, for no single car.
GENERIC_PART_KEYWORDS = [
    "Bremsbeläge",
    "Ölfilter",
    "Luftfilter",
    "Stoßdämpfer",
    "Zündkerzen",
    "Lambdasonde",
]


def collect_autodoc_targets(db, limit, min_discount, dry_run, stats):
    saved = 0
    for target in TARGET_VEHICLES:
        part = target["part"]
        brand = target["brand"]
        model = target["model"]
        print(f"\n=== Autodoc | {part} | {brand} {model} ===")
        try:
            raw_deals = search_autodoc_part(part, brand, model, limit=limit)
        except Exception as exc:
            print(f"  ERROR scraping Autodoc: {exc}")
            stats["errors"] += 1
            continue

        print(f"  scraped: {len(raw_deals)}")
        worth = filter_deals_by_average(raw_deals, min_discount=min_discount)
        stats["filtered_out"] += len(raw_deals) - len(worth)
        if not worth:
            continue

        context = f"{brand} {model} {part}"
        cleaned = clean_deals(
            worth,
            context=context,
            default_vehicle={"brand": brand, "model": model},
        )
        for deal in cleaned:
            if dt_skip_if_exists(db, deal, stats):
                continue
            if dry_run:
                deal["clean_title"] = deal.get("clean_title") or deal.get("title")
                print_message(deal)
                saved += 1
                continue
            create_deal(
                db,
                product_id=deal["product_id"],
                title=deal.get("clean_title") or deal["title"],
                title_en=to_english_title(deal.get("clean_title") or deal["title"]),
                sale_price=deal["sale_price"],
                discount_percentage=deal["discount_percentage"],
                retail_price=deal.get("retail_price"),
                average_price=deal.get("average_price"),
                image_url=deal.get("image_url"),
                source_url=deal.get("raw_url"),
                affiliate_link=affiliate_link_for_url(deal.get("raw_url")),
                compatible_vehicles=deal.get("compatible_vehicles") or None,
            )
            stats["saved"] += 1
            saved += 1
            print_message(deal)
    return saved


def collect_ebay_generic(db, limit, min_discount, dry_run, stats):
    saved = 0
    for keyword in GENERIC_PART_KEYWORDS:
        print(f"\n=== eBay | generic | {keyword} ===")
        try:
            raw_deals = fetch_ebay_deals(keyword, limit=limit)
        except Exception as exc:
            print(f"  ERROR fetching eBay: {exc}")
            stats["errors"] += 1
            continue

        print(f"  scraped: {len(raw_deals)}")
        # Average base for eBay = all results of this part keyword (across its searches).
        worth = filter_deals_by_average(raw_deals, min_discount=min_discount)
        stats["filtered_out"] += len(raw_deals) - len(worth)
        if not worth:
            continue

        cleaned = clean_deals(worth, context=f"Generic '{keyword}' - no specific car")
        for deal in cleaned:
            if dt_skip_if_exists(db, deal, stats):
                continue
            if dry_run:
                deal["clean_title"] = deal.get("clean_title") or deal.get("title")
                print_message(deal)
                saved += 1
                continue
            create_deal(
                db,
                product_id=deal["product_id"],
                title=deal.get("clean_title") or deal["title"],
                title_en=to_english_title(deal.get("clean_title") or deal["title"]),
                sale_price=deal["sale_price"],
                discount_percentage=deal["discount_percentage"],
                retail_price=deal.get("retail_price"),
                average_price=deal.get("average_price"),
                image_url=deal.get("image_url"),
                source_url=deal.get("raw_url"),
                affiliate_link=affiliate_link_for_url(deal.get("raw_url")),
                compatible_vehicles=deal.get("compatible_vehicles") or None,
            )
            stats["saved"] += 1
            saved += 1
            print_message(deal)
    return saved


def _maybe_send_telegram(dry_run: bool):
    """(optional) after a live run: broadcast the freshly saved deals."""
    if dry_run:
        return
    try:
        from telegram_distribute import run_broadcast
        run_broadcast(dry_run=False, admin_only=False)
    except Exception as exc:
        print(f"\n[telegram] skipped: {exc}")


def dt_skip_if_exists(db, deal, stats):
    if get_deal_by_product_id(db, deal["product_id"]):
        stats["existing"] += 1
        return True
    return False


def print_message(deal):
    print("  ✅ " + format_deal_message(deal).replace("\n", " | "))


def main():
    parser = argparse.ArgumentParser(description="EU automotive parts discount discovery")
    parser.add_argument("--dry-run", action="store_true",
                        help="scrape/filter but do not write to deals.db")
    parser.add_argument("--limit", type=int, default=15,
                        help="max raw deals fetched per search (default 15)")
    parser.add_argument("--min-discount", type=float,
                        default=float(os.getenv("MIN_DISCOUNT", "15")),
                        help="min % below market-average price to publish (default 15)")
    parser.add_argument("--no-autodoc", action="store_true")
    parser.add_argument("--no-ebay", action="store_true")
    parser.add_argument("--telegram", action="store_true",
                        help="after persisting, broadcast new deals to Telegram")
    args = parser.parse_args()

    print(f"MIN_DISCOUNT = {args.min_discount}%  ({'DRY RUN' if args.dry_run else 'LIVE'})\n")

    db = SessionLocal()
    stats = {"filtered_out": 0, "existing": 0, "saved": 0, "errors": 0}

    try:
        if not args.no_autodoc:
            collect_autodoc_targets(db, args.limit, args.min_discount, args.dry_run, stats)
        if not args.no_ebay:
            collect_ebay_generic(db, args.limit, args.min_discount, args.dry_run, stats)
    finally:
        db.close()

    if args.telegram:
        _maybe_send_telegram(args.dry_run)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print(f"  new deals persisted   : {stats['saved']}")
    print(f"  skipped (already in DB): {stats['existing']}")
    print(f"  rejected (< discount) : {stats['filtered_out']}")
    print(f"  scrape errors         : {stats['errors']}")
    print("=" * 60)


if __name__ == "__main__":
    main()