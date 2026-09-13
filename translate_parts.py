"""
German -> English auto-translation for car part titles.

Autodoc / eBay list German titles (e.g. "BOSCH Bremsscheibe Vorderachse
260x22mm"). We keep the raw title in the DB but display / search an English
version so the whole website can be used in English.
"""

import re

# (German phrase, English phrase) - longer phrases first so e.g.
# "bremsscheibensatz" wins before "bremsscheibe" + "satz".
_GLOSSARY = [
    ("bremsscheibensatz", "brake disc set"),
    ("bremsscheiben", "brake discs"),
    ("bremsscheibe", "brake disc"),
    ("bremsbelagsatz", "brake pad set"),
    ("bremsbeläge", "brake pads"),
    ("bremsbelage", "brake pads"),
    ("bremsbelag", "brake pad"),
    ("bremssattel", "brake caliper"),
    ("bremsbackensatz", "brake shoe set"),
    ("bremsbacke", "brake shoe"),
    ("bremsleitungen", "brake lines"),
    ("bremsleitung", "brake line"),
    ("bremsflüssigkeit", "brake fluid"),
    ("bremsflüssigkeitsbehälter", "brake fluid reservoir"),
    ("bremslichtschalter", "brake light switch"),
    ("ölfilter", "oil filter"),
    ("kraftstofffilter", "fuel filter"),
    ("luftfilter", "air filter"),
    ("innenraumfilter", "cabin filter"),
    ("pollenfilter", "pollen filter"),
    ("feinstaubfilter", "particulate filter"),
    ("partikelfilter", "particulate filter"),
    ("kraftstoffpumpe", "fuel pump"),
    ("zerstäuber", "injector"),
    ("einspritzdüse", "injector"),
    ("injektor", "injector"),
    ("zündkerzen", "spark plugs"),
    ("zündkerze", "spark plug"),
    ("glühkerzen", "glow plugs"),
    ("glühkerze", "glow plug"),
    ("zündspule", "ignition coil"),
    ("zündkabel", "ignition leads"),
    ("zündverteiler", "ignition distributor"),
    ("stoßdämpfer", "shock absorber"),
    ("stossdämpfer", "shock absorber"),
    ("federbein", "strut"),
    ("schraubenfeder", "coil spring"),
    ("fahrwerksfeder", "suspension spring"),
    ("federn", "springs"),
    ("feder", "spring"),
    ("querlenker", "control arm"),
    ("traggelenk", "ball joint"),
    ("spurstange", "track rod"),
    ("spurstangenkopf", "track rod end"),
    ("radlager", "wheel bearing"),
    ("radlagerkit", "wheel bearing kit"),
    ("radlagersatz", "wheel bearing set"),
    ("reparatursatz", "repair kit"),
    ("antriebswelle", "driveshaft"),
    ("gelenkwelle", "propshaft"),
    ("gleichlaufgelenk", "CV joint"),
    ("achsmanschette", "CV boot"),
    ("manschette", "boot"),
    ("kupplungssatz", "clutch kit"),
    ("kupplung", "clutch"),
    ("ausrücklager", "release bearing"),
    ("getriebeöl", "gearbox oil"),
    ("motoröl", "engine oil"),
    ("getriebe", "gearbox"),
    ("kühler", "radiator"),
    ("kühlmitteltemperatursensor", "coolant temperature sensor"),
    ("kühlmittel", "coolant"),
    ("wasserpumpe", "water pump"),
    ("ölpumpe", "oil pump"),
    ("keilrippenriemen", "serpentine belt"),
    ("keilriemen", "V-belt"),
    ("zahnriemen", "timing belt"),
    ("zahnriemensatz", "timing belt kit"),
    ("zahnriemenrad", "timing belt pulley"),
    ("spannrolle", "tensioner"),
    ("zylinderkopfdichtung", "head gasket"),
    ("dichtungssatz", "gasket set"),
    ("dichtung", "gasket"),
    ("lichtmaschine", "alternator"),
    ("anlasser", "starter motor"),
    ("starter", "starter"),
    ("batterie", "battery"),
    ("scheibenwischer", "wiper blades"),
    ("wischblatt", "wiper blade"),
    ("wischarm", "wiper arm"),
    ("wischanlage", "wiper system"),
    ("lambdasonde", "lambda sensor"),
    ("lambda-sonde", "lambda sensor"),
    ("katalysator", "catalytic converter"),
    ("abgasanlage", "exhaust system"),
    ("auspuff", "exhaust"),
    ("schalldämpfer", "silencer"),
    ("rüßpartikelfilter", "diesel particulate filter"),
    ("dieselpartikelfilter", "diesel particulate filter"),
    ("dpf", "DPF"),
    ("turbolader", "turbocharger"),
    ("turbo", "turbo"),
    ("wastegate-aktuator", "wastegate actuator"),
    ("sensoren", "sensors"),
    ("sensor", "sensor"),
    ("steuergerät", "control unit"),
    ("servopumpe", "power steering pump"),
    ("servolenkung", "power steering"),
    ("lenkgetriebe", "steering rack"),
    ("lenkung", "steering"),
    ("scheinwerfer", "headlight"),
    ("scheinwerferglühlampe", "headlight bulb"),
    ("rückleuchte", "tail light"),
    ("nebelrückleuchte", "rear fog light"),
    ("nebel-scheinwerfer", "fog light"),
    ("nebel-schlussleuchte", "rear fog light"),
    ("blinker", "indicator"),
    ("seitenspiegel", "wing mirror"),
    ("gehäusespiegel", "mirror casing"),
    ("spiegel", "mirror"),
    ("stoßstange", "bumper"),
    ("stossstange", "bumper"),
    ("kotflügel", "wing"),
    ("kühlerhaube", "bonnet"),
    ("haube", "bonnet"),
    ("heckklappe", "tailgate"),
    ("kofferraum", "boot"),
    ("windschutzscheibe", "windscreen"),
    ("frontscheibe", "windscreen"),
    ("dachreling", "roof rails"),
    ("vorderachse", "front axle"),
    ("hinterachse", "rear axle"),
    ("vorder", "front"),
    ("hinter", "rear"),
    ("vorne", "front"),
    ("hinten", "rear"),
    ("links", "left"),
    ("rechts", "right"),
    ("satz", "set"),
    ("satzzubehör", "set accessories"),
    ("glatt", "smooth"),
    ("belüftet", "ventilated"),
    ("gelocht", "drilled"),
    ("genutet", "grooved"),
    ("hochwertig", "premium"),
    ("original", "OE"),
    ("ersatzteil", "spare part"),
    ("neu", "new"),
    ("gebraucht", "used"),
    ("generalüberholt", "refurbished"),
    ("ausgebaut", "removed"),
    ("für", "for"),
    ("mit", "with"),
    ("ohne", "without"),
    ("und", "and"),
    ("inklusive", "incl."),
    ("inkl", "incl"),
    ("inkl.", "incl."),
]

_COMPILED = sorted(
    [
        {
            "rgx": re.compile(r"\b" + re.escape(de) + r"\b", re.IGNORECASE),
            "en": en,
            "n": len(de),
        }
        for de, en in _GLOSSARY
    ],
    key=lambda item: -item["n"],
)


def to_english_title(title: str) -> str:
    """Returns an English version of a (German) part title/full phrase."""
    if not title:
        return ""
    out = str(title)
    for item in _COMPILED:
        out = item["rgx"].sub(item["en"], out)
    return out


def to_english_deal_title(clean_title, raw_title=None) -> str:
    """English display title: prefer a stored/clean title, translated."""
    base = clean_title or raw_title or ""
    return to_english_title(base)


def to_german_keyword(phrase: str) -> str:
    """Reverse lookup: turns an English part phrase ('oil filter') back into
    German ('ölfilter') so Autodoc's German catalog search can find it.
    Unknown words are left as-is."""
    if not phrase:
        return ""
    out = str(phrase).strip()
    for de, en in _GLOSSARY:
        rgx = re.compile(r"\b" + re.escape(en) + r"\b", re.IGNORECASE)
        out = rgx.sub(de, out)
    return out


# Alternative spellings used for cars, so "VW Golf" can match a title that
# already says "Volkswagen Golf" (and vice versa) before we append a car.
_VEHICLE_ALIASES = {
    "Volkswagen": ["VW", "Volkswagen"],
    "VW": ["Volkswagen", "VW"],
    "Mercedes-Benz": ["Mercedes", "Mercedes-Benz"],
    "Mercedes": ["Mercedes", "Mercedes-Benz"],
}


def _car_tokens(brand: str) -> list:
    """All spelling variants of a brand name that count as 'mentioned'."""
    brand = (brand or "").strip()
    if not brand:
        return []
    tokens = [brand]
    tokens += _VEHICLE_ALIASES.get(brand, [])
    for key, values in _VEHICLE_ALIASES.items():
        if brand in values and key not in tokens:
            tokens.append(key)
    return tokens


def _mentioned(text: str, token: str) -> bool:
    return bool(token) and token.lower() in (text or "").lower()


def title_with_vehicles(title, vehicles) -> str:
    """Returns the title with the car(s) the part fits appended, e.g.

        "Oil Filter M20x1.5, Anschraubfilter"  + Opel/Corsa D
        -> "Oil Filter M20x1.5, Anschraubfilter · for Opel Corsa D"

    Only cars that are NOT already mentioned in the title are added (checks
    brand aliases too, so a "VW Golf 7" title won't get VW appended again).
    `vehicles` are Deal.compatible_models entries (SQLAlchemy or dicts with
    brand/model)."""
    if not title:
        return ""
    text = str(title).strip()
    missing = []
    for v in vehicles or []:
        if isinstance(v, dict):
            brand = v.get("brand")
            model = v.get("model")
        else:
            brand = getattr(getattr(v, "brand", None), "name", None) \
                if getattr(v, "brand", None) is not None else None
            model = getattr(v, "name", None)
        if not (brand or model):
            continue
        has_brand = any(_mentioned(text, t) for t in _car_tokens(brand)) if brand else False
        has_model = _mentioned(text, model) if model else False
        if has_brand and has_model:
            continue
        missing.append(" ".join(x for x in (brand, model) if x))
    if not missing:
        return text
    return f"{text} · for {', '.join(dict.fromkeys(missing))}"