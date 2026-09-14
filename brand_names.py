"""Lightweight brand detection for the catalog / fit filter.

Extracts two different "brands" from a scraped listing:

  - part maker: the auto-parts manufacturer (ATE, HELLA, FEBI BILSTEIN...).
    Autodoc URLs carry it in the path (/febi-bilstein/1870171); eBay titles
    start with it. Stored in Deal.brand_name and used as a quality signal and
    a filterable column.
  - car makes: every car-maker name mentioned in an eBay title (Bremssattel
    für Audi A3). Stored in Deal.vehicle_brand so generic eBay parts can still
    be matched when a visitor filters by their car make.
"""

import re
import urllib.parse

# Known car-part manufacturers (upper-case tokens used to trust a cheap eBay
# listing: a 2 EUR ATE part is a real part, a 2 EUR no-name doodad is junk).
PARTS_BRANDS = (
    "ATE", "BOSCH", "BEHR", "BEHR MAHLE", "BEHR MAKE", "HELLA", "BILSTEIN",
    "BREMBO", "CORTECO", "CONTINENTAL", "CHAMPION", "DAYCO", "DELPHI",
    "DENSO", "EBC", "FAG", "FEBI", "FEBEST", "FERODO", "FIRSTLINE", "GATES",
    "GKN", "HENGST", "HITACHI", "INA", "JAPANPARTS", "JURID", "KAWE",
    "KNECHT", "KOLBENSCHMIDT", "LIQUI", "LPR", "LUK", "MAGNETI", "MAHLE",
    "MANN", "MAPCO", "MARELLI", "METZGER", "MEYLE", "MOBIL", "MOTUL",
    "NGK", "NTY", "OPTIBELT", "PENRITE", "PIERBURG", "PILENGA", "RAVENOL",
    "RIDEX", "SACHS", "SCT", "SHELL", "SIDEM", "SKF", "SNR", "SPIDAN",
    "STARK", "STELLOX", "SWAG", "TEXTAR", "TOTAL", "TRW", "VAICO", "VALEO",
    "VEMO", "WABER", "WILMINK", "ZF", "ZIMMERMANN",
)

# Car-maker names (and aliases) mentioned in eBay part titles. Used to link
# generic eBay parts to a visitor-selected car make ("fits" panel).
CAR_BRANDS = (
    "volkswagen", "vw", "audi", "bmw", "mini", "mercedes", "benz", "smart",
    "opel", "vauxhall", "ford", "fiesta", "toyota", "honda", "nissan",
    "mazda", "hyundai", "kia", "renault", "peugeot", "citroen", "fiat",
    "alfa", "lancia", "skoda", "seat", "volvo", "porsche", "lexus", "subaru",
    "suzuki", "mitsubishi", "daihatsu", "rover", "landrover", "jaguar",
    "lada", "chevrolet", "jeep", "chrysler", "dodge", "tesla", "dacia",
    "ferrari", "lamborghini", "bugatti", "piaggio", "vespa", "simson",
    "trabant", "wartburg", "barkas", "ifa", "multicar", "mz", "yamaha",
    "ducati", "ktm", "husqvarna", "harley",
)

_CAR_PRETTY = {
    "vw": "VW", "mz": "MZ", "ifa": "IFA", "alfa": "Alfa Romeo",
    "mercedes": "Mercedes-Benz", "benz": "Mercedes-Benz", "simson": "Simson",
    "trabant": "Trabant", "wartburg": "Wartburg", "multicar": "Multicar",
    "vespa": "Vespa", "landrover": "Land Rover",
}


def _flat(text: str) -> str:
    t = (text or "").lower()
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss")):
        t = t.replace(a, b)
    return " ".join(t.split())


# (flat form, original) pairs, longest first, deduped on the flat form so a
# lookup can never return the wrong maker because of a sort/index mismatch.
_KNOWN_PART_PAIRS = []
_seen_flat = set()
for _b in sorted(PARTS_BRANDS, key=lambda b: -len(b)):
    _f = _flat(_b)
    if _f in _seen_flat:
        continue
    _seen_flat.add(_f)
    _KNOWN_PART_PAIRS.append((_f, _b))


def title_has_part_brand(title: str) -> bool:
    """True when a known part maker appears at the very start of the title."""
    t = _flat(title)
    for _f, _orig in _KNOWN_PART_PAIRS:
        if t == _f or t.startswith(_f + " "):
            return True
    return False


def extract_part_brand(source_url: str, title: str = "") -> str:
    """Best-effort part-maker of a listing. Autodoc: slug from the product URL.
    eBay: first title token when it starts with a known brand name."""
    url = source_url or ""
    try:
        path = urllib.parse.urlsplit(url).path
    except Exception:
        path = ""
    if "autodoc" in url.lower():
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2 and segments[-1].isdigit():
            return segments[-2].replace("-", " ").upper()
    t = _flat(title)
    for _f, _orig in _KNOWN_PART_PAIRS:
        if t == _f or t.startswith(_f + " "):
            return _orig.upper()
    return ""


def car_makes_in_title(title: str) -> str:
    """Comma-separated car makers mentioned in an eBay title ('' if none)."""
    t = _flat(title)
    found = []
    for name in CAR_BRANDS:
        if re.search(rf"(^|\s){re.escape(name)}(\s|$|\d)", t):
            pretty = _CAR_PRETTY.get(name, name.title())
            if pretty not in found:
                found.append(pretty)
    return ", ".join(found)