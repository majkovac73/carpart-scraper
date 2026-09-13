"""
Shared, DB-agnostic text formatting for deals.

Used by the pipeline (main.py), the Telegram broadcaster and the website so
every channel shows identical wording. Accepts both deal dicts (pipeline) and
SQLAlchemy Deal rows (website / telegram).
"""


from translate_parts import to_english_title


def _fmt_eur(value) -> str:
    """Formats floats the EU way: 12.345,67."""
    try:
        return f"{float(value):,.2f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def _get(deal, key, default=None):
    """Read a field from either a deal dict or a SQLAlchemy Deal row."""
    if isinstance(deal, dict):
        return deal.get(key, default)
    return getattr(deal, key, default)


def _vehicle_labels(deal):
    labels = []
    vehicles = _get(deal, "compatible_vehicles") or _get(deal, "compatible_models")
    if not vehicles:
        return labels
    for v in vehicles:
        if isinstance(v, dict):
            brand = v.get("brand")
            model = v.get("model")
        else:
            brand = getattr(v, "brand", None)
            brand = getattr(brand, "name", brand) if brand is not None else None
            model = getattr(v, "name", None)
        if brand and model:
            labels.append(f"{brand} {model}")
        elif model:
            labels.append(str(model))
        elif brand:
            labels.append(str(brand))
    return labels


def _deal_url(deal):
    return (
        _get(deal, "affiliate_link")
        or _get(deal, "source_url")
        or _get(deal, "raw_url")
    )


def _display_title(deal) -> str:
    """English title: stored title_en, else live-translate the raw title."""
    title = _get(deal, "title_en") or _get(deal, "clean_title") or _get(deal, "title")
    if not title:
        return "Untitled part"
    if _get(deal, "title_en"):
        return title
    return to_english_title(title)


def format_deal_message(deal) -> str:
    """Full view: title, cars, price vs market average, RRP, link."""
    lines = [_display_title(deal)]

    veh = _vehicle_labels(deal)
    if veh:
        lines.append("🚗 " + ", ".join(veh))

    sale = _get(deal, "sale_price") or 0
    avg = _get(deal, "average_price")
    off = _get(deal, "discount_percentage", 0)

    if avg:
        price_line = f"💶 {_fmt_eur(sale)} € (avg {_fmt_eur(avg)} €, −{off}%)"
    else:
        price_line = f"💶 {_fmt_eur(sale)} € (−{off}%)"

    retail = _get(deal, "retail_price")
    try:
        if retail is not None and float(retail) > float(sale or 0):
            price_line += f" · RRP {_fmt_eur(retail)} €"
    except (TypeError, ValueError):
        pass

    lines.append(price_line)

    url = _deal_url(deal)
    if url:
        lines.append(f"🔗 {url}")

    return "\n".join(lines)


def x_copy_text(deal) -> str:
    """X/Twitter copy WITHOUT the URL (paste manually -> no X API fee)."""
    title = _display_title(deal)
    veh = _vehicle_labels(deal)
    car = (" for " + ", ".join(veh)) if veh else ""

    sale = _get(deal, "sale_price") or 0
    avg = _get(deal, "average_price")
    off = _get(deal, "discount_percentage", 0)

    if avg:
        price = f"💶 {_fmt_eur(sale)} € (avg {_fmt_eur(avg)} €, −{off}%)"
    else:
        price = f"💶 {_fmt_eur(sale)} €"

    return f"🛠️ {title}{car}\n{price}"