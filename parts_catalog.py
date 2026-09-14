"""Single source of truth for the car-parts vocabulary the pipeline searches.

Every entry is one searchable part:
  - de    : German keyword sent to Autodoc's catalog search AND used as the eBay
            keyword search inside the Vehicle Parts & Accessories category.
  - en    : human-readable English name (used for file names / summaries).
  - match : lowercase substrings that must appear in an eBay listing title for
            the listing to be kept (junk like "Weltkarte Poster" is dropped).

Because this catalog is imported by schedule.py (rotation), ebay_scraper.py
(title quality filter) and translate_parts.py (German->English display), adding
a part here automatically extends the rotation, the eBay quality gate and the
title translation everywhere.
"""

import re


def _norm(text):
    t = (text or "").lower()
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss")):
        t = t.replace(a, b)
    return " ".join(t.split())


def find_part(keyword_or_name: str):
    """Returns the catalog entry whose keyword (de or en) is an exact,
    whole-word match for the given English/German part name. Used to tag
    scraped products with their catalog part."""
    key = _norm(keyword_or_name or "")
    if not key:
        return None
    for part in PARTS:
        for cand in (part["de"], part["en"], *part.get("match", ())):
            if re.fullmatch(re.escape(_norm(cand)), key) or _norm(cand) == key:
                return part
    return None


def find_part_in_text(title: str):
    """Returns the catalog entry whose match tokens appear in the title; when
    several parts match (e.g. Zahnriemen vs Zahnriemensatz) the most specific
    (longest) token wins."""
    haystack = _norm(title or "")
    if not haystack:
        return None
    best = None
    best_len = 0
    for part in PARTS:
        for token in part.get("match", ()):
            length = len(_norm(token))
            if length > best_len and _norm(token) in haystack:
                best = part
                best_len = length
    return best


def find_all_parts_in_text(title: str):
    """All catalog entries whose match tokens appear in the title (best few)."""
    haystack = _norm(title or "")
    out = []
    for part in PARTS:
        if any(_norm(t) in haystack for t in part.get("match", ())):
            out.append(part)
    return out


def part_labels():
    """(English name, German keyword) pairs for search autocomplete."""
    return [(p["en"], p["de"]) for p in PARTS]

PARTS = [
    # --- Brakes ----------------------------------------------------------
    {"de": "Bremsscheiben", "en": "brake discs",
     "match": ("bremsscheib", "brake disc")},
    {"de": "Bremsbeläge", "en": "brake pads",
     "match": ("bremsbelag", "brake pad")},
    {"de": "Bremsbacken", "en": "brake shoes",
     "match": ("bremsback", "brake shoe")},
    {"de": "Bremssattel", "en": "brake caliper",
     "match": ("bremssattel", "caliper")},
    {"de": "Bremszylinder", "en": "brake cylinder",
     "match": ("bremszylinder", "brake cylinder")},
    {"de": "Bremsleitungen", "en": "brake lines",
     "match": ("bremsleitung", "brake line")},
    {"de": "Bremsflüssigkeit", "en": "brake fluid",
     "match": ("bremsflüssigkeit", "brake fluid")},
    {"de": "Handbremsseil", "en": "handbrake cable",
     "match": ("handbremse", "parking brake", "hand brake")},
    {"de": "Bremskraftverstärker", "en": "brake booster",
     "match": ("bremskraftverstärker", "brake booster")},
    {"de": "ABS-Sensor", "en": "ABS sensor",
     "match": ("abs-sensor", "abs sensor", "wheel speed")},
    {"de": "Bremspedal", "en": "brake pedal",
     "match": ("bremspedal", "brake pedal")},
    {"de": "Bremslichtschalter", "en": "brake light switch",
     "match": ("bremslichtschalter", "brake light")},

    # --- Filters ---------------------------------------------------------
    {"de": "Ölfilter", "en": "oil filter",
     "match": ("ölfilter", "oil filter")},
    {"de": "Kraftstofffilter", "en": "fuel filter",
     "match": ("kraftstofffilter", "fuel filter")},
    {"de": "Luftfilter", "en": "air filter",
     "match": ("luftfilter", "air filter")},
    {"de": "Innenraumfilter", "en": "cabin filter",
     "match": ("innenraumfilter", "cabin filter", "pollen filter", "cabin air")},
    {"de": "Pollenfilter", "en": "pollen filter",
     "match": ("pollenfilter", "pollen filter")},
    {"de": "Feinstaubfilter", "en": "particulate filter",
     "match": ("feinstaubfilter", "particulate")},
    {"de": "Dieselpartikelfilter", "en": "diesel particulate filter",
     "match": ("partikelfilter", "dieselpartikelfilter", "dpf")},

    # --- Ignition / engine ----------------------------------------------
    {"de": "Zündkerzen", "en": "spark plugs",
     "match": ("zündkerz", "spark plug")},
    {"de": "Glühkerzen", "en": "glow plugs",
     "match": ("glühkerz", "glow plug")},
    {"de": "Zündspule", "en": "ignition coil",
     "match": ("zündspule", "ignition coil")},
    {"de": "Zündkabel", "en": "ignition leads",
     "match": ("zündkabel", "ignition lead")},
    {"de": "Zündverteiler", "en": "ignition distributor",
     "match": ("zündverteiler", "distributor")},
    {"de": "Ölpumpe", "en": "oil pump",
     "match": ("ölpumpe", "oil pump")},
    {"de": "Wasserpumpe", "en": "water pump",
     "match": ("wasserpumpe", "water pump")},
    {"de": "Zahnriemen", "en": "timing belt",
     "match": ("zahnriemen", "timing belt", "steuerriemen")},
    {"de": "Zahnriemensatz", "en": "timing belt kit",
     "match": ("zahnriemensatz", "zahnriemen", "timing belt")},
    {"de": "Zahnriemenrad", "en": "timing belt pulley",
     "match": ("zahnriemenrad", "timing pulley")},
    {"de": "Steuerkette", "en": "timing chain",
     "match": ("steuerkette", "timing chain")},
    {"de": "Steuerkettensatz", "en": "timing chain kit",
     "match": ("steuerkettensatz", "timing chain kit", "steuerkette", "timing chain")},
    {"de": "Spannrolle", "en": "belt tensioner",
     "match": ("spannrolle", "tensioner")},
    {"de": "Umlenkrolle", "en": "idler pulley",
     "match": ("umlenkrolle", "idler")},
    {"de": "Keilrippenriemen", "en": "serpentine belt",
     "match": ("keilrippenriemen", "rippenriemen", "keilriemen", "v-belt", "serpentine")},
    {"de": "Keilriemen", "en": "V-belt",
     "match": ("keilriemen", "v-belt")},
    {"de": "Riemenspanner", "en": "belt tensioner",
     "match": ("riemenspann", "belt tensioner")},
    {"de": "Kurbelwellenriemenscheibe", "en": "crankshaft pulley",
     "match": ("kurbelwellenriemenscheibe", "crank pulley", "crankshaft pulley")},
    {"de": "Motoröl", "en": "engine oil",
     "match": ("motoröl", "engine oil")},
    {"de": "Ölwanne", "en": "oil pan",
     "match": ("ölwanne", "oil pan")},
    {"de": "Ölabscheider", "en": "oil separator",
     "match": ("ölabscheider", "oil separator", "pcv")},
    {"de": "Ventildeckel", "en": "valve cover",
     "match": ("ventildeckel", "valve cover")},
    {"de": "Zylinderkopfdichtung", "en": "cylinder head gasket",
     "match": ("zylinderkopfdichtung", "head gasket")},

    # --- Cooling ---------------------------------------------------------
    {"de": "Kühler", "en": "radiator",
     "match": ("kühler", "radiator")},
    {"de": "Kühlmittel", "en": "coolant",
     "match": ("kühlmittel", "coolant", "antifreeze")},
    {"de": "Thermostat", "en": "thermostat",
     "match": ("thermostat",)},
    {"de": "Kühlmitteltemperatursensor", "en": "coolant temperature sensor",
     "match": ("kühlmitteltemperatur", "coolant temp")},
    {"de": "Kühlerlüfter", "en": "radiator fan",
     "match": ("kühlerlüfter", "radiator fan", "lüftermotor")},
    {"de": "Lüfterkupplung", "en": "fan clutch",
     "match": ("lüfterkupplung", "fan clutch")},
    {"de": "Ausgleichsbehälter", "en": "expansion tank",
     "match": ("ausgleichsbehälter", "expansionsbehälter", "expansion tank", "coolant tank")},
    {"de": "Ladeluftkühler", "en": "intercooler",
     "match": ("ladeluftkühler", "intercooler")},

    # --- Exhaust ---------------------------------------------------------
    {"de": "Lambdasonde", "en": "lambda sensor",
     "match": ("lambdasonde", "lambda", "oxygen sensor")},
    {"de": "Katalysator", "en": "catalytic converter",
     "match": ("katalysator", "catalytic")},
    {"de": "Abgasanlage", "en": "exhaust system",
     "match": ("abgasanlage", "exhaust")},
    {"de": "Auspuff", "en": "exhaust",
     "match": ("auspuff", "exhaust")},
    {"de": "Endschalldämpfer", "en": "rear silencer",
     "match": ("endschalldämpfer", "schalldämpfer", "silencer", "muffler")},
    {"de": "Mittelschalldämpfer", "en": "centre silencer",
     "match": ("mittelschalldämpfer", "schalldämpfer", "silencer")},
    {"de": "Abgasrohr", "en": "exhaust pipe",
     "match": ("abgasrohr", "exhaust pipe")},
    {"de": "Abgaskrümmer", "en": "exhaust manifold",
     "match": ("abgaskrümmer", "exhaust manifold")},
    {"de": "AGR-Ventil", "en": "EGR valve",
     "match": ("agr-ventil", "agr ventil", "egr", "abgasrückführung")},

    # --- Electrical ------------------------------------------------------
    {"de": "Lichtmaschine", "en": "alternator",
     "match": ("lichtmaschine", "alternator", "generator")},
    {"de": "Anlasser", "en": "starter motor",
     "match": ("anlasser", "starter")},
    {"de": "Batterie", "en": "battery",
     "match": ("batterie", "battery", "autobatterie")},
    {"de": "Scheinwerfer", "en": "headlight",
     "match": ("scheinwerfer", "headlight")},
    {"de": "Scheinwerferglühlampe", "en": "headlight bulb",
     "match": ("scheinwerferglühlampe", "headlight bulb", "h7", "h4")},
    {"de": "Rückleuchte", "en": "tail light",
     "match": ("rückleuchte", "tail light", "taillight")},
    {"de": "Blinker", "en": "indicator",
     "match": ("blinker", "indicator", "turn signal")},
    {"de": "Nebelscheinwerfer", "en": "fog light",
     "match": ("nebelscheinwerfer", "fog light")},
    {"de": "Lichtschalter", "en": "light switch",
     "match": ("lichtschalter", "light switch")},
    {"de": "Relais", "en": "relay",
     "match": ("relais", "relay")},
    {"de": "Sicherung", "en": "fuse",
     "match": ("sicherung", "fuse")},
    {"de": "Steuergerät", "en": "engine control unit",
     "match": ("steuergerät", "ecu", "control unit")},
    {"de": "Kabelbaum", "en": "wiring harness",
     "match": ("kabelbaum", "harness", "wiring loom")},
    {"de": "Nockenwellensensor", "en": "camshaft sensor",
     "match": ("nockenwellensensor", "camshaft sensor")},
    {"de": "Kurbelwellensensor", "en": "crankshaft sensor",
     "match": ("kurbelwellensensor", "crankshaft sensor")},

    # --- Suspension ------------------------------------------------------
    {"de": "Stoßdämpfer", "en": "shock absorbers",
     "match": ("stoßdämpf", "stossdampf", "dämpfer", "shock absorber", "damper")},
    {"de": "Federbein", "en": "strut",
     "match": ("federbein", "strut")},
    {"de": "Fahrwerksfeder", "en": "suspension spring",
     "match": ("fahrwerksfeder", "suspension spring")},
    {"de": "Schraubenfeder", "en": "coil spring",
     "match": ("schraubenfeder", "coil spring")},
    {"de": "Stabilisator", "en": "anti-roll bar",
     "match": ("stabilisator", "sway bar")},
    {"de": "Querlenker", "en": "control arm",
     "match": ("querlenker", "control arm", "wishbone")},
    {"de": "Traggelenk", "en": "ball joint",
     "match": ("traggelenk", "ball joint")},
    {"de": "Spurstange", "en": "track rod",
     "match": ("spurstange", "track rod")},
    {"de": "Spurstangenkopf", "en": "track rod end",
     "match": ("spurstangenkopf", "track rod", "tie rod")},
    {"de": "Radlager", "en": "wheel bearing",
     "match": ("radlager", "wheel bearing")},
    {"de": "Radlagersatz", "en": "wheel bearing set",
     "match": ("radlagersatz", "wheel bearing")},
    {"de": "Antriebswelle", "en": "driveshaft",
     "match": ("antriebswelle", "driveshaft", "drive shaft")},
    {"de": "Gleichlaufgelenk", "en": "CV joint",
     "match": ("gleichlaufgelenk", "cv joint")},
    {"de": "Achsmanschette", "en": "CV boot",
     "match": ("achsmanschette", "cv boot", "manschette")},
    {"de": "Gelenkwelle", "en": "propshaft",
     "match": ("gelenkwelle", "propshaft", "prop shaft")},
    {"de": "Koppelstange", "en": "anti-roll bar link",
     "match": ("koppelstange", "drop link", "stabilisatorstrebe")},

    # --- Clutch / transmission ------------------------------------------
    {"de": "Kupplungssatz", "en": "clutch kit",
     "match": ("kupplung", "clutch")},
    {"de": "Kupplung", "en": "clutch",
     "match": ("kupplung", "clutch")},
    {"de": "Ausrücklager", "en": "release bearing",
     "match": ("ausrücklager", "release bearing")},
    {"de": "Kupplungsdruckplatte", "en": "pressure plate",
     "match": ("kupplungsdruckplatte", "pressure plate")},
    {"de": "Zweimassenschwungrad", "en": "dual-mass flywheel",
     "match": ("zweimassenschwungrad", "dual mass", "flywheel")},
    {"de": "Getriebeöl", "en": "gearbox oil",
     "match": ("getriebeöl", "gearbox oil")},
    {"de": "Automatikgetriebeöl", "en": "automatic transmission fluid",
     "match": ("automatikgetriebeöl", "atf", "transmission fluid")},
    {"de": "Schaltgetriebe", "en": "manual gearbox",
     "match": ("schaltgetriebe", "gearbox", "transmission")},
    {"de": "Getriebelager", "en": "gearbox mount",
     "match": ("getriebelager", "gearbox mount")},

    # --- Steering --------------------------------------------------------
    {"de": "Servopumpe", "en": "power steering pump",
     "match": ("servopumpe", "power steering", "servopump")},
    {"de": "Servolenkung", "en": "power steering",
     "match": ("servolenkung", "power steering")},
    {"de": "Lenkgetriebe", "en": "steering rack",
     "match": ("lenkgetriebe", "steering rack")},
    {"de": "Lenkwelle", "en": "steering column",
     "match": ("lenkwelle", "steering column")},

    # --- Fuel system -----------------------------------------------------
    {"de": "Kraftstoffpumpe", "en": "fuel pump",
     "match": ("kraftstoffpumpe", "fuel pump", "benzinpumpe")},
    {"de": "Einspritzdüse", "en": "fuel injector",
     "match": ("einspritzdüse", "injector")},
    {"de": "Injektor", "en": "fuel injector",
     "match": ("injektor", "injector")},
    {"de": "Tankgeber", "en": "fuel sender",
     "match": ("tankgeber", "fuel sender", "fuel level")},

    # --- Body ------------------------------------------------------------
    {"de": "Stoßstange", "en": "bumper",
     "match": ("stoßstange", "stußstange", "bumper")},
    {"de": "Kotflügel", "en": "wing",
     "match": ("kotflügel", "wing", "fender")},
    {"de": "Kühlerhaube", "en": "bonnet",
     "match": ("kühlerhaube", "bonnet", "hood")},
    {"de": "Heckklappe", "en": "tailgate",
     "match": ("heckklappe", "tailgate")},
    {"de": "Türschloss", "en": "door lock",
     "match": ("türschloss", "door lock")},
    {"de": "Türgriff", "en": "door handle",
     "match": ("türgriff", "door handle")},
    {"de": "Seitenspiegel", "en": "wing mirror",
     "match": ("seitenspiegel", "wing mirror", "spiegel")},
    {"de": "Windschutzscheibe", "en": "windscreen",
     "match": ("windschutzscheibe", "windscreen", "windshield")},

    # --- Service / other -------------------------------------------------
    {"de": "Scheibenwischer", "en": "wiper blades",
     "match": ("scheibenwischer", "wischblatt", "wiper")},
    {"de": "Wischarm", "en": "wiper arm",
     "match": ("wischarm", "wiper arm")},
    {"de": "Turbolader", "en": "turbocharger",
     "match": ("turbolader", "turbocharger", "turbo")},
    {"de": "Kurbelgehäuseentlüftung", "en": "crankcase ventilation",
     "match": ("kurbelgehäuseentlüftung", "crankcase", "pcv")},
    {"de": "Motorlager", "en": "engine mount",
     "match": ("motorlager", "engine mount")},
    {"de": "Kompressor", "en": "compressor",
     "match": ("kompressor", "compressor")},
]

# eBay generic keyword searches run every pipeline run (cheap API calls).
EBAY_KEYWORDS = [p["de"] for p in PARTS]