"""
TrackDeals EU – Car Part Deals Archive (FastAPI + Jinja2).

Routes:
  /            Home with make/model search form + latest deals
  /deals       All real deals (filterable)
  /deal/{id}   Single deal detail page
  /search      Indexed DB search (instant); pass live=1 to trigger Autodoc
  /out/{id}    Short redirect + click tracking
  /about       Affiliate disclosure and data sourcing
  /api/deals   JSON
  /api/models  JSON (for make->model dropdown)
  /api/parts   JSON (catalog autocomplete)

Run locally:
    python website.py                       # http://127.0.0.1:8000
    python website.py --host 0.0.0.0 --port 8000   # visible on your LAN

Deploy: see SETUP.md (Render / Railway / Vercel).
"""

import argparse
import os
import threading
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import SessionLocal, Brand, Deal, DealClick
from crud import (search_deals, get_deal_by_id,
                  get_models_by_brand, get_good_deals, deal_worth_showing)
from deals_format import _fmt_eur, format_deal_message
from translate_parts import to_english_title, title_with_vehicles
from parts_catalog import part_labels

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="TrackDeals Archive", description="EU automotive parts deals archive")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["eur"] = _fmt_eur
templates.env.filters["en"] = to_english_title
templates.env.filters["car"] = title_with_vehicles


def _display_title(deal) -> str:
    """Best English title for a deal: stored translation, else live lookup."""
    title = deal.title_en or deal.title
    return title or "Untitled part"


templates.env.filters["disp"] = _display_title

# Live searches scraped from Autodoc directly (opening a browser window) are
# serialised so one request at a time touches Playwright.
_LIVE_SEARCH_LOCK = threading.Lock()

# Turn live Autodoc browser scraping off by default for production; set
# ALLOW_LIVE_SCRAPE=1 in the environment to re-enable it.
ALLOW_LIVE_SCRAPE = os.getenv("ALLOW_LIVE_SCRAPE", "0") == "1"


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
        "url": deal.affiliate_link or deal.source_url,
        "out_url": f"/out/{deal.id}",
        "clicks": deal.clicks or 0,
        "status": deal.status,
        "vehicles": vehicles,
        "brand_name": deal.brand_name or "",
        "part_en": deal.part_en or "",
        "part_de": deal.part_de or "",
        "source": deal.source or "",
        "vehicle_brand": deal.vehicle_brand or "",
        "updated_at": deal.updated_at or "",
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
    from crud import get_deal_by_product_id, upsert_deal
    from translate_parts import to_german_keyword
    from affiliate import affiliate_link_for_url
    from parts_catalog import find_part_in_text
    from brand_names import extract_part_brand
    from datetime import datetime as _dt

    keyword = to_german_keyword(part) if (brand or model) else (part or "")
    if not keyword:
        return []

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
    now = _dt.now().isoformat(timespec="seconds")
    catalog_part = find_part_in_text(part) if part else None
    part_de = catalog_part["de"] if catalog_part else None
    part_en = catalog_part["en"] if catalog_part else None

    stored = []
    for deal in cleaned:
        deal["product_id"] = "live_" + deal["product_id"].split("_", 1)[-1]
        is_deal = (deal.get("discount_percentage") or 0) >= threshold
        brand_name_val = extract_part_brand(deal.get("raw_url") or "", deal.get("title") or "")
        upsert_deal(
            db,
            product_id=deal["product_id"],
            title=deal.get("clean_title") or deal["title"],
            sale_price=deal["sale_price"],
            discount_percentage=deal["discount_percentage"] if is_deal else 0,
            retail_price=deal.get("retail_price"),
            average_price=deal.get("average_price"),
            image_url=deal.get("image_url"),
            source_url=deal.get("raw_url"),
            affiliate_link=affiliate_link_for_url(deal.get("raw_url")),
            compatible_vehicles=deal.get("compatible_vehicles")
                or ([{"brand": brand, "model": model}] if brand and model else None),
            status="pending" if is_deal else "search",
            brand_name=brand_name_val,
            part_de=part_de,
            part_en=part_en,
            source="autodoc",
            vehicle_brand="",
            updated_at=now,
        )
        row = get_deal_by_product_id(db, deal["product_id"])
        if row:
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
        deals = get_good_deals(db, limit=12)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "brands": brands,
            "deals": deals,
            "parts": part_labels(),
            "page": "home",
        })
    finally:
        db.close()


@app.get("/deals")
def deals_page(
    request: Request,
    brand: str = Query(""),
    model: str = Query(""),
    q: str = Query(""),
    part: str = Query(""),
    mbrand: str = Query(""),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    db = _db()
    try:
        if brand or model or q or part or mbrand:
            deals = search_deals(db, brand=brand, model=model, q=q,
                                 part=part, mbrand=mbrand, limit=limit)
        else:
            deals = get_good_deals(db, skip=skip, limit=limit)
        return templates.TemplateResponse("results.html", {
            "request": request,
            "heading": "Good deals" if not any((brand,model,q,part,mbrand)) else "Results",
            "deals": deals,
            "brands": db.query(Brand).order_by(Brand.name).all(),
            "models": get_models_by_brand(db, brand_name=brand),
            "selected_brand": brand,
            "selected_model": model,
            "selected_q": q,
            "selected_part": part,
            "selected_mbrand": mbrand,
            "parts": part_labels(),
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
    part: str = Query(""),
    mbrand: str = Query(""),
    live: int = Query(0),
    limit: int = Query(60, ge=1, le=200),
):
    db = _db()
    try:
        brands = db.query(Brand).order_by(Brand.name).all()
        deals = search_deals(db, brand=brand, model=model, q=q,
                             part=part, mbrand=mbrand, limit=limit)
        live_scraped = False

        # Nothing cached for this car/part yet -> ask Autodoc right now (only
        # when the visitor explicitly asked for a live search AND it's enabled).
        if live and ALLOW_LIVE_SCRAPE and not deals and (q.strip() or (brand.strip() and model.strip())):
            try:
                live = _live_fetch_and_store(db, part=q or "", brand=brand, model=model)
            except Exception as exc:
                print(f"  [live search] failed: {exc}")
                live = []
            if live:
                deals = live
                live_scraped = True

        heading = "All deals"
        if brand or model or q or part or mbrand:
            parts = []
            if brand:
                parts.append(brand)
            if model:
                parts.append(model)
            heading = "Results for " + (" ".join(parts) if parts else "your search")
            if q:
                heading += f' · keyword "{q}"'
            if part:
                heading += f" · {part}"
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
            "selected_part": part,
            "selected_mbrand": mbrand,
            "parts": part_labels(),
            "allow_live": ALLOW_LIVE_SCRAPE,
        })
    finally:
        db.close()


@app.get("/about")
def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request, "page": "about"})


# ---------------------------------------------------------------------
# JSON API (used by the search form and handy for experiments)
# ---------------------------------------------------------------------

@app.get("/out/{deal_id}")
def out_link(request: Request, deal_id: int):
    """Short redirect used for the 'View deal' buttons.

    Keeps the long EPN URLs out of the page markup (they used to overflow the
    layout) and lets us log every click server-side, so you can verify clicks
    arrive even before the eBay Partner Network dashboard updates."""
    db = _db()
    try:
        deal = get_deal_by_id(db, deal_id)
        if not deal:
            return RedirectResponse("/", status_code=302)
        url = deal.affiliate_link or deal.source_url
        if not url:
            return RedirectResponse(f"/deal/{deal_id}", status_code=302)

        try:
            deal.clicks = (deal.clicks or 0) + 1
            db.add(DealClick(
                deal_id=deal_id,
                clicked_at=datetime.now().isoformat(timespec="seconds"),
                referer=request.headers.get("referer") or "",
            ))
            db.commit()
        except Exception:
            db.rollback()
        return RedirectResponse(url, status_code=302)
    finally:
        db.close()


@app.get("/api/deals")
def api_deals(brand: str = Query(""), model: str = Query(""), q: str = Query(""),
              part: str = Query(""), mbrand: str = Query(""),
              skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200),
              mode: str = Query("smart")):
    db = _db()
    try:
        deals = search_deals(db, brand=brand, model=model, q=q,
                             part=part, mbrand=mbrand, skip=skip, limit=limit)
        if mode == "smart" and deals:
            good = [d for d in deals if deal_worth_showing(d)]
            deals = good or deals
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


@app.get("/api/parts")
def api_parts():
    return [{"en": en, "de": de} for en, de in part_labels()]


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