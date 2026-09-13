"""
Phase 5.3 - TrackDeals web archive (FastAPI + Jinja2).

Reads deals.db directly (no keys needed) and lets visitors search parts
for their specific car by brand / model / keyword.

Run locally:
    python website.py                       # http://127.0.0.1:8000
    python website.py --host 0.0.0.0 --port 8000   # visible on your LAN

Deploy: see SETUP.md (Render / Railway / Vercel).
"""

import argparse
import os
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from database import SessionLocal, Brand
from crud import (search_deals, get_deal_by_id,
                  get_models_by_brand, get_good_deals, deal_worth_showing)
from deals_format import _fmt_eur, format_deal_message
from translate_parts import to_english_title, title_with_vehicles

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="TrackDeals Archive", description="EU automotive parts deals archive")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["eur"] = _fmt_eur
templates.env.filters["en"] = to_english_title
templates.env.filters["car"] = title_with_vehicles

# Live searches scraped from Autodoc directly (opening a browser window) are
# serialised so one request at a time touches Playwright.
_LIVE_SEARCH_LOCK = threading.Lock()


def _db():
    return SessionLocal()


def _deal_payload(deal) -> dict:
    """Plain-dict version of a Deal for the JSON API (session-safe)."""
    vehicles = [
        {"brand": m.brand.name, "model": m.name} for m in deal.compatible_models
    ]
    title = deal.title_en or to_english_title(deal.title)
    return {
        "id": deal.id,
        "product_id": deal.product_id,
        "title": deal.title,
        "title_en": title,
        "display_title": title_with_vehicles(title, vehicles),
        "sale_price": deal.sale_price,
        "retail_price": deal.retail_price,
        "discount_percentage": deal.discount_percentage,
        "average_price": deal.average_price,
        "image_url": deal.image_url,
        "url": deal.source_url or deal.affiliate_link,
        "status": deal.status,
        "vehicles": vehicles,
    }


def _live_fetch_and_store(db, part: str, brand: str = "", model: str = ""):
    """Scrapes Autodoc live for the given car + part, caches the results in
    deals.db and returns the stored Deal objects (cheapest first).

    Cached offers get status "search" (visible on the site, never broadcast).
    Offers priced >= MIN_DISCOUNT below the market average are saved as real
    "pending" deals so they enter the normal Telegram pipeline. Nothing is
    saved twice - a product id that already exists is left untouched.
    """
    from autodoc_scraper import search_autodoc_part
    from deal_filter import average_price, filter_deals_by_average
    from llm_engine import clean_deals
    from crud import get_deal_by_product_id, create_deal
    from translate_parts import to_german_keyword
    from affiliate import affiliate_link_for_url

    keyword = to_german_keyword(part) if (brand or model) else (part or "")
    if not keyword:
        return []

    # A real (non-headless) renderer is required so Cloudflare lets us through,
    # but the scraper positions its window off-screen by default so nothing
    # pops up in front of the visitor. Set AUTODOC_WINDOW_VISIBLE=1 to debug.
    with _LIVE_SEARCH_LOCK:
        raw = search_autodoc_part(keyword, brand or "", model or "",
                                  limit=15, headless=False)
    if not raw:
        return []

    avg = average_price(raw)
    enriched = filter_deals_by_average(raw, min_discount=0) if avg else []
    if not enriched:
        return []

    context = " ".join(filter(None, (brand, model, part)))
    cleaned = clean_deals(
        enriched,
        context=context,
        default_vehicle=({"brand": brand, "model": model} if brand and model else None),
    )

    threshold = float(os.getenv("MIN_DISCOUNT", "15"))
    stored = []
    for deal in cleaned:
        deal["product_id"] = "live_" + deal["product_id"].split("_", 1)[-1]
        if get_deal_by_product_id(db, deal["product_id"]):
            continue
        is_deal = (deal.get("discount_percentage") or 0) >= threshold
        row = create_deal(
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
            compatible_vehicles=deal.get("compatible_vehicles")
                or ([{"brand": brand, "model": model}] if brand and model else None),
            status="pending" if is_deal else "search",
        )
        stored.append(row)
    stored.sort(key=lambda d: d.sale_price)
    return stored


# ---------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------

@app.get("/")
def home(request: Request):
    db = _db()
    try:
        brands = db.query(Brand).order_by(Brand.name).all()
        deals = get_good_deals(db, limit=8)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "brands": brands,
            "deals": deals,
            "page": "home",
        })
    finally:
        db.close()


@app.get("/deals")
def deals_page(request: Request, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    db = _db()
    try:
        deals = get_good_deals(db, skip=skip, limit=limit)
        return templates.TemplateResponse("results.html", {
            "request": request,
            "heading": "Good deals",
            "deals": deals,
            "brands": db.query(Brand).order_by(Brand.name).all(),
            "models": get_models_by_brand(db, brand_name=""),
            "selected_brand": "",
            "selected_model": "",
            "selected_q": "",
        })
    finally:
        db.close()


@app.get("/deal/{deal_id}")
def deal_detail(request: Request, deal_id: int):
    db = _db()
    try:
        deal = get_deal_by_id(db, deal_id)
        if not deal:
            return templates.TemplateResponse("deal.html", {
                "request": request, "deal": None, "message": "",
            }, status_code=404)
        return templates.TemplateResponse("deal.html", {
            "request": request,
            "deal": deal,
            "message": format_deal_message(deal),
        })
    finally:
        db.close()


@app.get("/search")
def search(
    request: Request,
    brand: str = Query(""),
    model: str = Query(""),
    q: str = Query(""),
    limit: int = Query(60, ge=1, le=200),
):
    db = _db()
    try:
        brands = db.query(Brand).order_by(Brand.name).all()
        deals = search_deals(db, brand=brand, model=model, q=q, limit=limit)
        live_scraped = False

        # Nothing cached for this car/part yet -> ask Autodoc right now and cache it.
        if not deals and (q.strip() or (brand.strip() and model.strip())):
            try:
                live = _live_fetch_and_store(db, part=q or "", brand=brand, model=model)
            except Exception as exc:
                print(f"  [live search] failed: {exc}")
                live = []
            if live:
                deals = live
                live_scraped = True

        # Display rule: real good deals first; if there are none for this query,
        # still show the single cheapest result so the visitor sees *something*.
        good = [d for d in deals if deal_worth_showing(d)]
        if good:
            deals = good
        elif deals:
            deals = [min(deals, key=lambda d: (d.sale_price is None, d.sale_price or 0))]

        heading = "All deals"
        if brand or model or q:
            parts = []
            if brand:
                parts.append(brand)
            if model:
                parts.append(model)
            heading = "Results for " + (" ".join(parts) if parts else "your search")
            if q:
                heading += f' · keyword "{q}"'
        if live_scraped:
            heading = "Live results from Autodoc for " + (
                " ".join(filter(None, (brand, model)))
            ) + (f' · "{q}"' if q else "") + " (newly searched & saved)"
        return templates.TemplateResponse("results.html", {
            "request": request,
            "heading": heading,
            "deals": deals,
            "brands": brands,
            "models": get_models_by_brand(db, brand_name=brand),
            "selected_brand": brand,
            "selected_model": model,
            "selected_q": q,
        })
    finally:
        db.close()


# ---------------------------------------------------------------------
# JSON API (used by the search form and handy for experiments)
# ---------------------------------------------------------------------

@app.get("/api/deals")
def api_deals(brand: str = Query(""), model: str = Query(""), q: str = Query(""),
              skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200),
              mode: str = Query("smart")):
    db = _db()
    try:
        deals = search_deals(db, brand=brand, model=model, q=q, skip=skip, limit=limit)
        if not deals and (q.strip() or (brand.strip() and model.strip())):
            try:
                deals = _live_fetch_and_store(db, part=q or "", brand=brand, model=model)
            except Exception as exc:
                print(f"  [live search] failed: {exc}")
        if mode == "smart" and deals:
            good = [d for d in deals if deal_worth_showing(d)]
            deals = good or [min(deals, key=lambda d: (d.sale_price is None, d.sale_price or 0))]
        return [_deal_payload(d) for d in deals]
    finally:
        db.close()


@app.get("/api/models")
def api_models(brand: str = Query("")):
    db = _db()
    try:
        models = get_models_by_brand(db, brand_name=brand)
        return [{"id": m.id, "name": m.name, "brand": m.brand.name} for m in models]
    finally:
        db.close()


@app.get("/api/health")
def api_health():
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TrackDeals website")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    print(f"TrackDeals running at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)