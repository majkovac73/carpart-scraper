import os
import base64
import time
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

# eBay API Endpoints (Production)
OAUTH_ENDPOINT = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_API_ENDPOINT = "https://api.ebay.com/buy/browse/v1/item_summary/search"

# eBay Buy API: "Vehicle Parts & Accessories" meta-category root for ALL
# non-US marketplaces (incl. EBAY_DE). Keeps keyword searches inside the
# car-parts tree so we find generic cheap parts, not unrelated products.
DEFAULT_CAR_PARTS_CATEGORY = "131090"

# Cheap no-name doodads (< ~4 EUR) do not make real deals. A branded part at
# 2 EUR (e.g. HELLA light switch) is fine; an unbranded circlip at 1 EUR is
# junk for the catalog. This floor is only applied to the "quality" flag that
# decides whether a scraped item is a *deal candidate*; every item still goes
# into the catalog (status="catalog") as a searchable product.
_PARTS_FLOOR = 4.0

# Loose eBay keyword searches still return unrelated junk (posters, fuses...).
# A listing is only kept when its title contains one of the catalog "match"
# terms for the part keyword. Unterpunkt/umlauts are flattened first
# (ö->o, ü->u, ä->a, ß->ss) and the term source stays in parts_catalog.py so
# adding a part automatically widens both the search and the quality gate.
from parts_catalog import PARTS as _CATALOG_PARTS
from brand_names import title_has_part_brand

TERM_ALIASES = {p["de"]: tuple(p["match"]) for p in _CATALOG_PARTS}


def _flat(text: str) -> str:
    """Lowercase, umlauts flattened, whitespace collapsed."""
    t = (text or "").lower()
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss")):
        t = t.replace(a, b)
    return " ".join(t.split())


# Listing titles that contain decorative/merch/junk words are never car parts.
_JUNK_TOKENS = (
    "poster", "plakat", "deko", "dekor", "kunst", "kunstdruck", "wandbild",
    "wanddeko", "decorative", "art print", "decor", "spielzeug", "lied", # lied = song/record
    "modellbau", "t-shirt", "tee-shirt", "tassen", "becher", "kleidung",
    "tasche", "taschen", "handyhülle", "aufkleber", "sticker", "lederarmband",
    "kette - schmuck", "auflage für", "sitzauflage", "buch -", "magazin",
    "testbericht", "prospekt", "postkarte", "briefmarke", "werbung",
    "werbeanzeige", "fahrzeugbrief", "ersatzteilkatalog", "catalog 19", "anzeige",
)


def _reject_junk(title: str) -> bool:
    t = _flat(title)
    return any(tok in t for tok in _JUNK_TOKENS)


def _title_matches(title: str, keyword: str) -> bool:
    """True when a normalized part alias for this keyword appears in the title."""
    if _reject_junk(title):
        return False
    haystack = _flat(title)
    aliases = TERM_ALIASES.get(keyword, (_flat(keyword),))
    return any(_flat(a) in haystack for a in aliases)


def title_matches_any_part(title: str) -> bool:
    """True when the title matches at least one part alias from ANY keyword
    (used to purge unrelated listings already persisted in the DB)."""
    return any(_title_matches(title, kw) for kw in TERM_ALIASES)

# Token is kept for its full lifetime (OAuth tokens are valid ~2h),
# so repeated keyword searches don't hammer the token endpoint.
_token_cache = {"token": None, "expires_at": 0.0}


def get_ebay_token():
    """Generates (and caches) an OAuth 2.0 Application Token via Client Credentials."""
    if not EBAY_CLIENT_ID or EBAY_CLIENT_ID == "your_client_id_here":
        print("Waiting for eBay API keys. Skipping eBay fetch...")
        return None

    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    # Base64 encode the Client ID and Secret
    credential_string = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credential_string.encode()).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {encoded_credentials}",
    }

    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }

    response = requests.post(OAUTH_ENDPOINT, headers=headers, data=data)

    if response.status_code == 200:
        payload = response.json()
        _token_cache["token"] = payload.get("access_token")
        _token_cache["expires_at"] = time.time() + float(payload.get("expires_in", 7200))
        return _token_cache["token"]
    else:
        print(f"Error fetching eBay token: {response.text}")
        return None


def _build_filters(price_min: float, price_max: float) -> str:
    """Combines Buy-It-Now, EUR currency and optional price-range filters."""
    filters = ["buyingOptions:{FIXED_PRICE}", "priceCurrency:EUR"]

    if price_min is not None or price_max is not None:
        lo = price_min if price_min is not None else 0.01
        hi = price_max if price_max is not None else 100000.0
        filters.append(f"price:[{lo:.2f}..{hi:.2f}]")

    return ",".join(filters)


def fetch_ebay_deals(
    keyword: str,
    category_id: str = DEFAULT_CAR_PARTS_CATEGORY,
    limit: int = 40,
    price_min: float = 5.0,
    price_max: float = 400.0,
    marketplace: str = "EBAY_DE",
):
    """
    Fetches generic car parts from eBay using a plain part keyword
    (e.g. "Bremsbeläge", "Ölfilter"), NOT a specific car or model.

    Constrains the search to the Vehicle Parts & Accessories category and
    skips the sub-5 EUR junk band (single screws, clamps, moped bits) so the
    sample and its batch average reflect real parts. Results use best-match
    ranking (a representative mix) instead of cheapest-first so a genuine
    discounted branded part has a chance to surface against a fair average.
    Discounted items include the original price / discount percentage.
    """
    token = get_ebay_token()
    if not token:
        return []

    # X-EBAY-C-MARKETPLACE-ID sets the regional marketplace (Germany/EU by default)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": marketplace,
    }

    params = {
        "q": keyword,
        "limit": limit,
        "filter": _build_filters(price_min, price_max),
    }

    if category_id:
        params["category_ids"] = category_id

    response = requests.get(BROWSE_API_ENDPOINT, headers=headers, params=params)

    if response.status_code != 200:
        print(f"Error fetching eBay deals: {response.text}")
        return []

    deals = []

    for item in response.json().get("itemSummaries", []):
        price = item.get("price") or {}
        sale_price = float(price.get("value") or 0)
        if sale_price <= 0:
            continue
        title = item.get("title") or ""
        if not _title_matches(title, keyword):
            continue

        # markjetingPrice is only present when the seller offers a discount.
        marketing = item.get("marketingPrice") or {}
        original_price = float((marketing.get("originalPrice") or {}).get("value") or 0)
        discount_percentage = float(marketing.get("discountPercentage") or 0)

        deals.append({
            "product_id": f"ebay_{item.get('itemId')}",
            "title": title,
            "sale_price": sale_price,
            "retail_price": original_price if original_price > sale_price else sale_price,
            "discount_percentage": round(discount_percentage, 1) if discount_percentage else 0.0,
            "currency": price.get("currency") or "EUR",
            "image_url": (item.get("image") or {}).get("imageUrl"),
            "raw_url": item.get("itemWebUrl"),
            "condition": (item.get("condition") or "").lower(),
            "source": "ebay",
            "quality": title_has_part_brand(title) or sale_price >= _PARTS_FLOOR,
        })

    deals.sort(key=lambda d: d["sale_price"])
    return deals[:limit]


# Local test block (generic parts only - no brand/model)
if __name__ == "__main__":
    print("Testing eBay API logic (generic cheap car parts)...")
    sample_deals = fetch_ebay_deals("Bremsbeläge")
    if sample_deals:
        for idx, deal in enumerate(sample_deals[:10], start=1):
            print(f"\n--- Result #{idx} ---")
            print(f"Title: {deal['title']}")
            print(f"Price: {deal['sale_price']} {deal['currency']}  "
                  f"(RRP {deal['retail_price']} {deal['currency']}, {deal['discount_percentage']}% off)")
            print(f"URL: {deal['raw_url']}")
    else:
        print("No deals returned (missing API keys or an API error).")