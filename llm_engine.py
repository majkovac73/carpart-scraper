"""
Phase 3.1 - LLM Engine

Cleans raw scraped part data into a strict, structured shape so every deal can be
posted to Telegram / archived on the website with: a clean title, the car it fits
(compatible vehicles), and a normalised condition.

Gemini is used when a GEMINI_API_KEY is present. Without a key (or on any API
error) a deterministic local extractor keeps the pipeline working offline.
"""

import os
import re
import json

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Seed "known chassis code -> vehicle" map used by the local fallback (and as a
# hint for the LLM prompt). Add more entries over time to widen coverage.
VEHICLE_CODE_MAP = [
    (r"\bE30\b", "BMW", "E30"),
    (r"\bE36\b", "BMW", "E36"),
    (r"\bE46\b", "BMW", "E46"),
    (r"\bE60\b", "BMW", "E60"),
    (r"\bE61\b", "BMW", "E61"),
    (r"\bE87\b", "BMW", "E87"),
    (r"\bE88\b", "BMW", "E88"),
    (r"\bE90\b", "BMW", "E90"),
    (r"\bE91\b", "BMW", "E91"),
    (r"\bE92\b", "BMW", "E92"),
    (r"\bE93\b", "BMW", "E93"),
    (r"\bF10\b", "BMW", "F10"),
    (r"\bF30\b", "BMW", "F30"),
    (r"\bF31\b", "BMW", "F31"),
    (r"\bF32\b", "BMW", "F32"),
    (r"\bG20\b", "BMW", "G20"),
    (r"\bW204\b", "Mercedes-Benz", "C-Klasse W204"),
    (r"\bW205\b", "Mercedes-Benz", "C-Klasse W205"),
    (r"\bW211\b", "Mercedes-Benz", "E-Klasse W211"),
    (r"\bW212\b", "Mercedes-Benz", "E-Klasse W212"),
    (r"\bW213\b", "Mercedes-Benz", "E-Klasse W213"),
    (r"\bMK4\b", "VW", "Golf 4"),
    (r"\bMK5\b", "VW", "Golf 5"),
    (r"\bMK6\b", "VW", "Golf 6"),
    (r"\bMK7\b", "VW", "Golf 7"),
    (r"\b1K2?\b", "VW", "Golf 5/6"),
    (r"\b5K2?\b", "VW", "Golf 6"),
    (r"\bGolf 7\b", "VW", "Golf 7"),
    (r"\bGolf 6\b", "VW", "Golf 6"),
    (r"\bGolf 5\b", "VW", "Golf 5"),
    (r"\bGolf 4\b", "VW", "Golf 4"),
    (r"\b8L\b", "Audi", "A3 8L"),
    (r"\b8P\b", "Audi", "A3 8P"),
    (r"\b8V\b", "Audi", "A3 8V"),
    (r"\bA3 8P\b", "Audi", "A3 8P"),
    (r"\bA3 8V\b", "Audi", "A3 8V"),
    (r"\bB8\b", "Audi", "A4 B8"),
    (r"\bB9\b", "Audi", "A4 B9"),
    (r"\bA4 B8\b", "Audi", "A4 B8"),
    (r"\bA4 B9\b", "Audi", "A4 B9"),
    (r"\bX156\b", "Mercedes-Benz", "GLA X156"),
]

PART_BRAND_MAP = [
    "AISIN", "ATE", "BLUE PRINT", "BOSCH", "BREMBO", "CORTECO",
    "FEBI BILSTEIN", "HELLA", "LEMFÖRDER", "MANN-FILTER", "MAPCO",
    "MEYLE", "MOBIL", "NGK", "NTN", "RIDEX", "SACHS", "SKF",
    "TEXTAR", "TRW", "VALEO", "ZF", "MAHLE", "KNECHT",
]

SEO_FILLER = [
    "autoteile günstig", "autoteile online", "online kaufen", "günstig",
    "für ihr auto", "für auto", "im internet", "bestellen", "kaufen",
    "zu attraktiven preisen", "jetzt bestellen", "top angebot",
]

CONDITION_NEW = ("brandneu", "brand new", "neu", "new ", "ungebraucht", "neuwertig")
CONDITION_USED = ("gebraucht", "used", "second hand", "secondhand", "usado", "occasión")
CONDITION_REFURB = ("refurbished", "renoviert", "generalüberholt", "aufbereitet",
                    "rückläufer", "b-ware", "rebuild")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _detect_condition(title: str) -> str:
    low = title.lower()
    if any(tag in low for tag in CONDITION_REFURB):
        return "refurbished"
    if any(tag in low for tag in CONDITION_USED):
        return "used"
    if any(tag in low for tag in CONDITION_NEW):
        return "new"
    return "unknown"


def _clean_title(title: str) -> str:
    clean = _normalise(title)
    for filler in SEO_FILLER:
        clean = re.sub(re.escape(filler), "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*\|\s*", " | ", clean)
    return re.sub(r"\s+", " ", clean).strip(" -|")


def _part_brand(title: str):
    upper = title.upper()
    for brand in PART_BRAND_MAP:
        if re.search(rf"\b{re.escape(brand)}\b", upper):
            return brand.title()
    return None


def _find_vehicles(title: str, default_vehicle=None):
    """Collects vehicles: the search context first, then any chassis codes found in the title."""
    vehicles = []

    def add(brand, model):
        entry = {"brand": brand.strip(), "model": model.strip()}
        if entry not in vehicles:
            vehicles.append(entry)

    if default_vehicle and default_vehicle.get("brand") and default_vehicle.get("model"):
        add(default_vehicle["brand"], default_vehicle["model"])

    for pattern, brand, model in VEHICLE_CODE_MAP:
        if re.search(pattern, title, flags=re.IGNORECASE):
            add(brand, model)

    return vehicles


# ---------------------------------------------------------------------------
# Gemini path
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You clean automotive parts listing data into strict JSON for a deal feed. "
    "For each input listing, return one object inside a JSON array, in the same "
    "order, with exactly these fields:\n"
    '{"product_id": string, "clean_title": string, "part_brand": string|null, '
    '"chassis_code": string|null, "condition": "new"|"used"|"refurbished"|"unknown", '
    '"compatible_vehicles": [{"brand": string, "model": string}]}\n'
    "Rules:\n"
    "- clean_title: collapse whitespace, drop SEO filler ('Autoteile günstig', "
    "'online kaufen', etc.), keep the factual part data.\n"
    "- compatible_vehicles: cars this part is made for. Use the search context when "
    "given, and infer from chassis codes in the title (e.g. E46 -> BMW E46). "
    "Return an empty array if nothing points to a concrete car.\n"
    "- condition: 'new' when brand new, 'used' when pre-owned, 'refurbished' when "
    "professionally rebuilt, otherwise 'unknown'.\n"
    "Return ONLY valid JSON (no markdown, no comments)."
)


def _llm_clean_batch(deals, context, default_vehicle):
    """Sends the whole batch in one Gemini call and returns {product_id: cleaned}."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    payload = []
    for deal in deals:
        item = {
            "product_id": deal.get("product_id"),
            "title": deal.get("title"),
            "source": deal.get("source"),
            "sale_price": deal.get("sale_price"),
            "retail_price": deal.get("retail_price"),
        }
        if context:
            item["search_context"] = context
        if default_vehicle:
            item["search_context"] = (
                f"{item.get('search_context', '')} Searched for vehicle: "
                f"{default_vehicle['brand']} {default_vehicle['model']}".strip()
            )
        payload.append(item)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=SYSTEM_PROMPT + "\n\nINPUT LISTINGS (JSON):\n" + json.dumps(payload, ensure_ascii=False),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
        timeout=90,
    )

    text = response.text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    parsed = json.loads(text)

    if not isinstance(parsed, list):
        return {}

    cleaned = {}
    for row in parsed:
        if isinstance(row, dict) and row.get("product_id"):
            cleaned[row["product_id"]] = row
    return cleaned


# ---------------------------------------------------------------------------
# Local fallback path
# ---------------------------------------------------------------------------
def _local_clean(deal, context, default_vehicle):
    title = deal.get("title") or ""
    cleaned = dict(deal)
    clean_title = _clean_title(title)
    cleaned["clean_title"] = clean_title or "Untitled part"
    cleaned["part_brand"] = _part_brand(title) or _part_brand(context or "")
    cleaned["chassis_code"] = _find_chassis_code(clean_title, context)
    cleaned["condition"] = _detect_condition(title)
    cleaned["compatible_vehicles"] = _find_vehicles(f"{clean_title} {context or ''}", default_vehicle)
    return cleaned


def _find_chassis_code(title: str, context: str = None):
    haystack = f"{title} {context or ''}"
    for pattern, _brand, _model in VEHICLE_CODE_MAP:
        match = re.search(rf"({pattern})", haystack, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def clean_deals(deals, context=None, default_vehicle=None):
    """Cleans a list of raw deal dicts in place-parallel.

    Returns a new list of dicts with clean_title, part_brand, chassis_code,
    condition and compatible_vehicles added. Uses Gemini if a key exists,
    otherwise the local extractor."""
    if not deals:
        return []

    if GEMINI_API_KEY:
        try:
            result = _llm_clean_batch(deals, context, default_vehicle)
            if result:
                cleaned = []
                for deal in deals:
                    row = result.get(deal.get("product_id"))
                    if row:
                        merged = dict(deal)
                        merged["clean_title"] = row.get("clean_title") or _clean_title(deal.get("title"))
                        merged["part_brand"] = row.get("part_brand")
                        merged["chassis_code"] = row.get("chassis_code")
                        merged["condition"] = row.get("condition") or "unknown"
                        merged["compatible_vehicles"] = row.get("compatible_vehicles") or []
                        cleaned.append(merged)
                    else:
                        cleaned.append(_local_clean(deal, context, default_vehicle))
                return cleaned
        except Exception as e:
            print(f"  Gemini cleaning unavailable ({e}) - using local extractor.")

    return [_local_clean(deal, context, default_vehicle) for deal in deals]