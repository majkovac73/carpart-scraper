"""
Deal discovery pipeline + steady-cadence scheduler.

Finds discounted automotive parts and indexes EVERY scraped product into the
local catalog (so the website can search it instantly), promoting only the
real deals to "pending" / Telegram:

  - Autodoc: searches a part per specific car (brand + model) via Playwright.
  - eBay:    searches generic part keywords inside the Vehicle Parts &
             Accessories category (no browser; REST API).
A product is a DEAL when its price is >= min_discount (default 15%) below the
market average of its search batch (Autodoc: same search; eBay: same part
keyword, only branded/meaningful items count). Everything else is stored as a
searchable catalog row (status "catalog").

Cadence: eBay keywords are re-scanned at most once per --ebay-every hours, so
`--daemon` can loop cheaply forever. Autodoc combos are walked once, then
oldest-first, once per --autodoc-every hours.

Usage:
    python main.py                            # one run (due eBay + autodoc plan)
    python main.py --ebay-all                 # force-scan ALL eBay keywords now
    python main.py --dry-run                  # scrape + filter but do not write
    python main.py --budget 25                # scrape 25 (part x car) combos
    python main.py --daemon                   # loop: eBay hourly, Autodoc daily
    python main.py --telegram                 # after persisting, broadcast deals
"""

import argparse
import os
import random
import sys
import time
import urllib.request
from datetime import datetime

from dotenv import load_dotenv

from database import SessionLocal
from crud import upsert_deal, get_deal_by_product_id
from autodoc_scraper import search_autodoc_part
from ebay_scraper import fetch_ebay_deals
from llm_engine import clean_deals
from deal_filter import average_price, filter_deals_by_average, off_average_percentage, is_worth_deal
from deals_format import format_deal_message
from translate_parts import to_english_title
from affiliate import affiliate_link_for_url
from schedule import build_plan, record_result, EBAY_KEYWORDS, coverage_stats
from parts_catalog import find_part
from brand_names import extract_part_brand, car_makes_in_title, title_has_part_brand
from cadence import due_ebay_keywords, mark_ebay_scanned, purge_stale_ebay

load_dotenv()


def _now():
    return datetime.now().isoformat(timespec="seconds")


DEFAULT_EBAY_DEAL_MIN_PRICE = 12.0
DEFAULT_AUTODOC_DEAL_MIN_PRICE = 8.0
DEFAULT_DEAL_MIN_SAVED = 6.0


def _store(db, raw, *, part_de, part_en, source, vehicles=None,
           min_discount, saved_stats, title_override=None, discount=None):
    """Tags one scraped product with catalog metadata and upserts it.

    status is "pending" for a real deal, otherwise "catalog". A product only
    becomes a deal when is_worth_deal() approves it: a genuine discount proof
    (seller-marked RRP off, or a strong peer-average discount), an absolute
    price floor and a minimum EUR saving. eBay additionally requires a known
    part brand, so cheap no-name junk stays in the catalog and never enters
    the feed. Returns True when the product was promoted (saved as a deal)."""
    product_id = raw.get("product_id")
    sale = raw.get("sale_price")
    title = title_override or raw.get("title") or ""
    off = (discount if discount is not None
           else off_average_percentage(raw.get("average_price"), sale))
    good_quality = source != "ebay" or bool(raw.get("quality"))
    min_price = (float(os.getenv("EBAY_DEAL_MIN_PRICE", str(DEFAULT_EBAY_DEAL_MIN_PRICE)))
                 if source == "ebay" else
                 float(os.getenv("AUTODOC_DEAL_MIN_PRICE", str(DEFAULT_AUTODOC_DEAL_MIN_PRICE))))
    min_saved = float(os.getenv("DEAL_MIN_SAVED", str(DEFAULT_DEAL_MIN_SAVED)))

    if not good_quality or (source == "ebay" and not title_has_part_brand(title)):
        is_deal, pct = False, 0.0
    else:
        is_deal, pct, _base = is_worth_deal(
            sale, raw.get("average_price"), raw.get("retail_price"),
            min_discount=min_discount, min_price=min_price, min_saved=min_saved,
        )

    brand = extract_part_brand(raw.get("raw_url") or "", raw.get("title") or "")
    upsert_deal(
        db,
        product_id=product_id,
        title=title,
        title_en=raw.get("title_en") or to_english_title(title),
        retail_price=raw.get("retail_price"),
        sale_price=sale,
        discount_percentage=pct if is_deal else 0,
        average_price=raw.get("average_price"),
        image_url=raw.get("image_url"),
        source_url=raw.get("raw_url"),
        affiliate_link=affiliate_link_for_url(raw.get("raw_url")),
        compatible_vehicles=vehicles,
        status="pending" if is_deal else "catalog",
        brand_name=brand,
        part_de=part_de,
        part_en=part_en,
        source=source,
        vehicle_brand=car_makes_in_title(raw.get("title") or "") if source == "ebay" else "",
        updated_at=_now(),
    )
    if is_deal:
        saved_stats["saved"] += 1
    else:
        saved_stats["catalog"] += 1
    return is_deal


def collect_autodoc_targets(db, limit, min_discount, dry_run, stats, combos,
                            headless=True):
    saved = 0
    for target in combos:
        part = target["part"]
        brand = target["brand"]
        model = target["model"]
        print(f"\n=== Autodoc | {part} | {brand} {model} ===")
        try:
            raw_deals = search_autodoc_part(part, brand, model, limit=limit,
                                            headless=headless)
        except Exception as exc:
            print(f"  ERROR scraping Autodoc: {exc}")
            stats["errors"] += 1
            record_result(db, target, "error", 0)
            continue

        print(f"  scraped: {len(raw_deals)}")
        record_result(db, target, "found" if raw_deals else "none", len(raw_deals))
        if not raw_deals:
            continue

        avg = average_price(raw_deals)
        vehicles = [{"brand": brand, "model": model}]
        context = f"{brand} {model} {part}"
        # Deal candidates get LLM-cleaned for proper English + fitment.
        worth = filter_deals_by_average(raw_deals, avg, min_discount)
        cleaned = clean_deals(worth, context=context, default_vehicle=vehicles[0])
        cleaned_by_id = {d.get("product_id"): d for d in cleaned}

        for raw in raw_deals:
            row = cleaned_by_id.get(raw.get("product_id"))
            is_deal = row is not None
            if dry_run:
                if is_deal:
                    stats["saved"] += 1
                    saved += 1
                    print_message(row)
                continue

            meta = dict(raw)
            meta["average_price"] = avg
            title = (row or {}).get("clean_title") or meta["title"]
            meta["title_en"] = (row or {}).get("title_en")
            meta["raw_url"] = meta.get("raw_url") or meta.get("source_url")
            if row:
                meta["compatible_vehicles"] = row.get("compatible_vehicles") or vehicles
            got_deal = _store(
                db, meta,
                part_de=target["part"], part_en=target["part_en"], source="autodoc",
                vehicles=vehicles, min_discount=min_discount, saved_stats=stats,
                title_override=title,
                discount=off_average_percentage(avg, meta["sale_price"]),
            )
            if got_deal:
                saved += 1
                row = get_deal_by_product_id(db, meta.get("product_id"))
                print_message(row or meta)
    return saved


def collect_ebay_generic(db, limit, min_discount, dry_run, stats, keywords):
    saved = 0
    for keyword in keywords:
        print(f"\n=== eBay | generic | {keyword} ===")
        try:
            raw_deals = fetch_ebay_deals(keyword, limit=limit)
        except Exception as exc:
            print(f"  ERROR fetching eBay: {exc}")
            stats["errors"] += 1
            mark_ebay_scanned(db, keyword, -1)
            continue

        print(f"  scraped: {len(raw_deals)}")
        mark_ebay_scanned(db, keyword, len(raw_deals))
        if not raw_deals:
            continue

        # The market average covers only items that look like real parts
        # (branded or >= the price floor) so cheap doodads cannot skew it.
        quality = [d for d in raw_deals if d.get("quality")]
        avg = average_price(quality) or average_price(raw_deals)
        part = find_part(keyword)
        part_de = (part or {}).get("de") or keyword
        part_en = (part or {}).get("en") or keyword

        for raw in raw_deals:
            if dry_run:
                off = off_average_percentage(avg, raw.get("sale_price"))
                if off is not None and off >= min_discount and raw.get("quality"):
                    stats["saved"] += 1
                    saved += 1
                    print_message(raw)
                continue

            raw["average_price"] = avg
            raw["raw_url"] = raw.get("raw_url") or raw.get("source_url")
            got_deal = _store(
                db, raw,
                part_de=part_de, part_en=part_en, source="ebay",
                vehicles=None, min_discount=min_discount, saved_stats=stats,
            )
            if got_deal:
                saved += 1
                row = get_deal_by_product_id(db, raw.get("product_id"))
                print_message(row or raw)
    return saved


def _maybe_send_telegram(dry_run: bool, run_in_thread: bool = False):
    """(optional) after a run: broadcast the freshly saved deals.
    In daemon mode the broadcast is deferred to a background thread so
    Telegram's flood-control pacing cannot stall the eBay/Autodoc loop."""
    if dry_run:
        return

    def _worker():
        try:
            from telegram_distribute import run_broadcast
            run_broadcast(dry_run=False, admin_only=False)
        except Exception as exc:
            print(f"\n[telegram] skipped: {exc}")

    if run_in_thread:
        import threading
        threading.Thread(target=_worker, daemon=True).start()
        return
    _worker()


def print_message(deal):
    print("  ✅ " + format_deal_message(deal).replace("\n", " | "))


def run_autodoc_stage(db, args, stats, seed=None, headless=True):
    if args.no_autodoc:
        return
    rng = random.Random(seed)
    combos = build_plan(db, budget=args.budget, rng=rng)
    print(f"Autodoc plan: {len(combos)} combo(s) this run "
          f"({coverage_stats(db)['remaining']} combos left unsearched overall)\n")
    collect_autodoc_targets(db, args.limit, args.min_discount, args.dry_run,
                            stats, combos, headless=headless)


def run_ebay_stage(db, args, stats):
    if args.no_ebay:
        return
    keywords = EBAY_KEYWORDS if args.ebay_all else due_ebay_keywords(
        db, interval_hours=(args.ebay_every / 3600.0))
    print(f"eBay sweep: {len(keywords)}/{len(EBAY_KEYWORDS)} keyword(s) due")
    saved = collect_ebay_generic(db, args.limit, args.min_discount, args.dry_run,
                                 stats, keywords)
    if args.dry_run:
        return
    purged = purge_stale_ebay(db, days=args.ebay_stale_days)
    if purged:
        print(f"  purged {purged} stale eBay catalog rows (> {args.ebay_stale_days}d)")
    return saved


def _ping_site():
    """Keeps the Render free-tier app from spinning down by hitting its home
    page every SITE_PING_INTERVAL_SECONDS. No-op while the interval is 0."""
    url = os.getenv("SITE_URL", "https://trackdeals.eu")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            status = resp.status
    except Exception as exc:
        print(f"  ping {url} FAILED: {exc}")
        return None
    print(f"  ping {url} -> {status}")
    return status


def run_daemon(args):
    print("Daemon mode: eBay every %.0fm, Autodoc every %.0fm"
          % (args.ebay_every / 60, args.autodoc_every / 60))
    ping_every = float(os.getenv("SITE_PING_INTERVAL_SECONDS", "1800"))
    if ping_every <= 0:
        print("  site ping disabled (SITE_PING_INTERVAL_SECONDS=0)")
    else:
        print(f"  pinging {os.getenv('SITE_URL', 'https://trackdeals.eu')} "
              f"every {ping_every/60:.0f}m to keep Render warm")
    next_ebay = next_autodoc = next_ping = next_tg = time.time()
    while True:
        now = time.time()
        if now >= next_ping and ping_every > 0:
            _ping_site()
            next_ping = now + ping_every
        if now >= next_tg and args.telegram:
            print(f"\n--- [{datetime.now():%H:%M:%S}] Telegram broadcast ---")
            _maybe_send_telegram(args.dry_run, run_in_thread=True)
            next_tg = now + args.telegram_every
        if now >= next_ebay and not args.no_ebay:
            print(f"\n--- [{datetime.now():%H:%M:%S}] eBay sweep ---")
            db = SessionLocal()
            stats = _fresh_stats()
            try:
                run_ebay_stage(db, args, stats)
            finally:
                db.close()
            _print_summary(stats, db=None)
            next_ebay = now + args.ebay_every
        if now >= next_autodoc and not args.no_autodoc:
            print(f"\n--- [{datetime.now():%H:%M:%S}] Autodoc plan ---")
            db = SessionLocal()
            stats = _fresh_stats()
            try:
                run_autodoc_stage(db, args, stats, seed=None, headless=args.headless)
            finally:
                db.close()
            _print_summary(stats, db=None)
            next_autodoc = now + args.autodoc_every
        print(f"[{datetime.now():%H:%M:%S}] next eBay ~{max(0, int(next_ebay - time.time()))}s, "
              f"next Autodoc ~{max(0, int(next_autodoc - time.time()))}s ...")
        time.sleep(60)


def _fresh_stats():
    return {"filtered_out": 0, "existing": 0, "saved": 0, "errors": 0, "catalog": 0}


def _print_summary(stats, db):
    print("\n" + "=" * 60)
    print("SUMMARY")
    print(f"  new deals persisted     : {stats['saved']}")
    print(f"  catalog products indexed: {stats['catalog']}")
    print(f"  skipped (already in DB) : {stats['existing']}")
    print(f"  scrape errors           : {stats['errors']}")
    if db is not None:
        cov = coverage_stats(db)
        print(f"  catalog coverage        : {cov['searched']}/{cov['total_combos']} "
              f"searched ({cov['remaining']} remaining)")
    print("=" * 60)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="EU automotive parts discount discovery")
    parser.add_argument("--dry-run", action="store_true",
                        help="scrape/filter but do not write to deals.db")
    parser.add_argument("--limit", type=int, default=15,
                        help="max raw products fetched per search (default 15)")
    parser.add_argument("--budget", type=int,
                        default=int(os.getenv("AUTODOC_BUDGET", "8")),
                        help="how many (part x car) combos to scrape per run (default 8)")
    parser.add_argument("--seed", type=int, default=None,
                        help="fixed shuffle seed for reproducible runs")
    parser.add_argument("--min-discount", type=float,
                        default=float(os.getenv("MIN_DISCOUNT", "15")),
                        help="min percent below market-average price to publish (default 15)")
    parser.add_argument("--no-autodoc", action="store_true")
    parser.add_argument("--no-ebay", action="store_true")
    parser.add_argument("--ebay-all", action="store_true",
                        help="scan every eBay keyword now (not just due ones)")
    parser.add_argument("--ebay-every", type=int,
                        default=int(os.getenv("EBAY_INTERVAL_SECONDS", "3600")),
                        help="min seconds between re-scans of an eBay keyword (default 3600)")
    parser.add_argument("--autodoc-every", type=int,
                        default=int(os.getenv("AUTODOC_INTERVAL_SECONDS", "86400")),
                        help="min seconds between Autodoc plan runs (default 86400)")
    parser.add_argument("--ebay-stale-days", type=int, default=14,
                        help="delete eBay catalog rows not re-seen for N days (default 14)")
    parser.add_argument("--daemon", action="store_true",
                        help="loop forever: eBay hourly, Autodoc daily")
    parser.add_argument("--telegram", action="store_true",
                        help="after persisting, broadcast new deals to Telegram")
    parser.add_argument("--telegram-every", type=int,
                        default=int(os.getenv("TELEGRAM_INTERVAL_SECONDS", "3600")),
                        help="min seconds between Telegram broadcasts in daemon (default 3600)")
    parser.add_argument("--headless", action="store_true",
                        help="run Autodoc browser in headless mode (for background/daemon)")
    args = parser.parse_args()

    print(f"MIN_DISCOUNT = {args.min_discount}%  ({'DRY RUN' if args.dry_run else 'LIVE'})")

    if args.daemon:
        run_daemon(args)
        return

    db = SessionLocal()
    stats = _fresh_stats()
    try:
        run_autodoc_stage(db, args, stats, seed=args.seed, headless=args.headless)
        run_ebay_stage(db, args, stats)
        cov = coverage_stats(db)
    finally:
        db.close()

    if args.telegram:
        _maybe_send_telegram(args.dry_run)

    _print_summary(stats, db=None)
    try:
        db = SessionLocal()
        cov = coverage_stats(db)
        print(f"  catalog coverage        : {cov['searched']}/{cov['total_combos']} "
              f"searched ({cov['remaining']} remaining)")
        db.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()