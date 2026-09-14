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

# Every catalog part doubles as a translation pair, so a part added to
# parts_catalog.py is automatically translated here too (plural + umlaut-flat
# variant + naive singular where it is safe).
from parts_catalog import PARTS as _CATALOG_PARTS


def _flat_de(word: str) -> str:
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss")):
        word = word.replace(a, b)
    return word


def _catalog_glossary() -> list:
    pairs = []
    for p in _CATALOG_PARTS:
        de = p["de"].lower()
        en = p["en"]
        pairs.append((de, en))
        flat = _flat_de(de)
        if flat != de:
            pairs.append((flat, en))
        if de.endswith("en") and len(de) > 5:
            sing = de[:-1]
            pairs.append((sing, en))
    return pairs


# German part vocabulary commonly seen on Autodoc / eBay titles that we do not
# search for themselves, but still need displayed in English.
_EXTRA_GLOSSARY = [
    # Connectors / fitment phrases
    ("passend für", "for"), ("passend", "for"), ("für", "for"),
    ("mit", "with"), ("ohne", "without"), ("und", "and"), ("oder", "or"),
    ("inklusive", "incl."), ("inkl", "incl"), ("inkl.", "incl."),
    ("exklusive", "excl."), ("exkl.", "excl."),
    ("original ersatzteil", "OE part"), ("originalteil", "OE part"),
    ("original", "OE"), ("neu original", "brand new"),
    ("für motoren", "for engines"), ("motoren", "engines"), ("motor", "engine"),
    ("fahrzeug", "vehicle"), ("fahrzeuge", "vehicles"), ("fahrzeugtypen", "vehicle types"),
    ("entspricht", "matches"), ("entsprechend", "corresponding"),
    ("ersetzt", "replaces"), ("ersetzung", "replacement"),
    ("artikelnummer", "part number"), ("teilenummer", "part number"),
    ("oe-nummer", "OE number"), ("oe nummer", "OE number"),
    ("hersteller", "manufacturer"), ("hergestellt", "manufactured"),
    ("gefertigt", "made"), ("bietet an", "offers"),
    # System context
    ("bremssystem", "brake system"), ("abgassystem", "exhaust system"),
    ("kühlkreislauf", "cooling circuit"), ("kühlkreislauf", "cooling circuit"),
    ("kühlsystem", "cooling system"), ("schmiersystem", "lubrication system"),
    ("einspritzsystem", "injection system"), ("kraftstoffsystem", "fuel system"),
    ("auspuffanlage", "exhaust system"), ("bremsanlage", "brake system"),
    # Positions
    ("vorderachse", "front axle"), ("hinterachse", "rear axle"),
    ("vorderachse links", "front left"), ("vorderachse rechts", "front right"),
    ("links", "left"), ("rechts", "right"), ("vorne", "front"), ("hinten", "rear"),
    ("vorderer", "front"), ("hinterer", "rear"), ("vordere", "front"),
    ("hintere", "rear"), ("vorderseite", "front side"), ("rückseite", "rear side"),
    ("außen", "outside"), ("innen", "inside"), ("äußere", "outer"),
    ("innere", "inner"), ("obere", "upper"), ("untere", "lower"),
    ("linkes", "left"), ("rechtes", "right"),
    ("rad vorne", "front wheel"), ("rad hinten", "rear wheel"),
    # Sets / parts vocabulary
    ("komplettsatz", "complete set"), ("vollsatz", "full set"),
    ("einzelteil", "single part"), ("einzelteile", "single parts"),
    ("ersatzteil", "spare part"), ("ersatzteile", "spare parts"),
    ("verschleißteil", "wear part"), ("verschleiß","wear"),
    ("wartung", "maintenance"), ("wartungssatz", "service kit"),
    ("dienstleistungen", "services"), ("service", "service"),
    ("zubehör", "accessory"), ("zubehörsatz", "accessory set"),
    ("montage", "installation"), ("montieren", "to install"),
    ("einbau", "installation"), ("verbaut", "installed"), ("eingebaut", "installed"),
    ("nicht notwendig", "not required"), ("nicht nötig", "not required"),
    ("notwendig", "required"), ("erforderlich", "required"),
    ("erforderlichen", "required"), ("benötigt", "needed"), ("gebraucht für", "used for"),
    ("speziell", "special"), ("spezial", "special"),
    ("hochwertig", "premium"), ("hochwertige", "premium"),
    ("qualität", "quality"), ("top-qualität", "top quality"),
    ("einwandfrei", "perfect"), ("in ordnung", "ok"),
    # Condition
    ("gebürstet", "brushed"), ("demontiert", "removed"), ("ausgebaut", "removed"),
    ("gebraucht", "used"), ("gebrauchte", "used"), ("gebrauchter", "used"),
    ("neuwertig", "as new"), ("neu", "new"), ("neue", "new"), ("neuer", "new"),
    ("generalüberholt", "refurbished"), ("überholt", "overhauled"),
    ("aufbereitet", "refurbished"), ("rückläufer", "returns"),
    ("b-ware", "B-stock"), ("sofortkauf", "Buy It Now"), ("auktion", "auction"),
    ("voll funktionsfähig", "fully functional"), ("funktionsfähig", "functional"),
    ("unbenutzt", "unused"), ("verpackung", "packaging"), ("unverschlossen", "unsealed"),
    ("original verpackt", "in original packaging"),
    # Marketing fluff
    ("kaufen", "buy"), ("bestellen", "order"), ("preiswert", "affordable"),
    ("günstig", "cheap"), ("sonderangebot", "special offer"), ("angebot", "offer"),
    ("ersparnis", "savings"), ("reduziert", "reduced"), ("reduktion", "reduction"),
    # Engine internals
    ("zweimassenschwungrad", "dual-mass flywheel"), ("schwungrad", "flywheel"),
    ("kurbelwelle", "crankshaft"), ("nockenwelle", "camshaft"),
    ("kurbelgehäuse", "crankcase"), ("pleuel", "connecting rod"),
    ("kolben", "piston"), ("zylinderkopf", "cylinder head"),
    ("zylinder", "cylinder"), ("zylinderzahlen", "cylinder count"),
    ("ventildeckeldichtung", "valve cover gasket"),
    ("ventilschaftdichtung", "valve stem seal"), ("ventile", "valves"),
    ("ventil", "valve"), ("kolbenring", "piston ring"),
    ("kolbenringsatz", "piston ring set"), ("ölsaugrohr", "oil pickup"),
    ("ölabscheider", "oil separator"), ("ölkühler", "oil cooler"),
    # Seals / covers
    ("dichtungssatz", "gasket set"), ("dichtungen", "gaskets"),
    ("dichtring", "sealing ring"), ("dichtringe", "sealing rings"),
    ("o-ring", "O-ring"), ("oring", "O-ring"), ("simmerring", "oil seal"),
    ("simmerringe", "oil seals"), ("abdeckung", "cover"), ("deckel", "cover"),
    ("gehäuse", "housing"), ("gehäusedichtung", "housing gasket"),
    ("schutzkappe", "protective cap"), ("verschlusskappe", "cap"),
    ("puffer", "buffer"), ("stütze", "support"),
    # Oil / fluids
    ("ölfiltergehäuse", "oil filter housing"), ("ölfilterkappe", "oil filter cap"),
    ("ölwanne", "oil pan"), ("ölwannendichtung", "oil pan gasket"),
    ("ölstand", "oil level"), ("ölablassschraube", "oil drain plug"),
    ("ablassschraube", "drain plug"), ("ölkontrolleuchte", "oil warning light"),
    ("frischöl", "fresh oil"), ("ölfüllmenge", "oil capacity"),
    # Disc features
    ("innenbelüftet", "internally ventilated"), ("belüftete", "ventilated"),
    ("belüftet", "ventilated"), ("gelocht", "drilled"), ("geschlitzt", "slotted"),
    ("genutet", "grooved"), ("glatt", "smooth"), ("hochkarbon", "high carbon"),
    ("höhenverstellbar", "height-adjustable"),
    # Dimensions
    ("durchmesser", "diameter"), ("durchm", "diameter"), ("diam", "diameter"),
    ("durchmesser mm", "diameter mm"), ("dicke", "thickness"),
    ("stärke", "thickness"), ("höhe", "height"), ("breite", "width"),
    ("länge", "length"), ("tiefe", "depth"), ("zoll", "inches"),
    ("schraube", "screw"), ("schrauben", "screws"), ("bolzen", "bolt"),
    ("muttern", "nuts"), ("mutter", "nut"), ("unterlegscheibe", "washer"),
    ("scheibe", "washer"), ("gewinde", "thread"), ("gewinder", "thread"),
    ("steigung", "pitch"), ("schlüsselweite", "spanner size"),
    # Electrical
    ("kabelbaum", "wiring harness"), ("kabelstrang", "wiring"),
    ("kabel", "cable"), ("anschlüsse", "connections"), ("anschluss", "connection"),
    ("stecker", "connector"), ("steckverbinder", "connector"),
    ("steckverbindersatz", "connector set"), ("klemmverbinder", "crimp connector"),
    ("sensorik", "sensors"), ("fühler", "sensor"), ("geber", "sender"),
    ("temperatur", "temperature"), ("drehzahl", "RPM"), ("druck", "pressure"),
    ("spannung", "voltage"), ("stromstärke", "current"),
    # Pumps / filters / belts
    ("pumpe", "pump"), ("förderpumpe", "feed pump"),
    ("umwälzpumpe", "circulation pump"), ("filtereinsatz", "filter element"),
    ("filtergehäuse", "filter housing"), ("filterzubehör", "filter accessory"),
    ("riesenfilter", "large filter"), ("patrone", "cartridge"),
    ("riemen", "belt"), ("steuerkette", "timing chain"),
    ("kette", "chain"), ("kettenrad", "sprocket"), ("spannrohr", "tensioning tube"),
    ("rollen", "pulleys"), ("rolle", "pulley"), ("zugfeder", "tension spring"),
    # Chassis / suspension details
    ("träger", "mount"), ("halter", "holder"), ("halterung", "bracket"),
    ("führung", "guide"), ("führungsbuchse", "guide bush"), ("buchse", "bushing"),
    ("gummi", "rubber"), ("gummilager", "rubber mount"),
    ("lagerung", "mounting"), ("aufhängung", "suspension"),
    ("abstützlager", "support bearing"), ("drucklager", "thrust bearing"),
    ("kugelgelenk", "ball joint"), ("achsschenkel", "steering knuckle"),
    ("stützlager", "top mount"), ("membranlager", "diaphragm bearing"),
    # Vehicle details
    ("spezifikation", "specification"), ("spezifisch", "specific"),
    ("variante", "variant"), ("ausführung", "version"),
    ("modelljahr", "model year"), ("baujahr", "year of manufacture"),
    ("jahrgang", "model year"), ("kennung", "code"), ("typ", "type"),
    ("herstellungsjahr", "year of manufacture"),
    # Fuels
    ("kraftstoffart", "fuel type"), ("kraftstoff", "fuel"),
    ("diesel", "diesel"), ("benzin", "petrol"), ("biodiesel", "biodiesel"),
    ("elektro", "electric"), ("bereifung", "tyre fitment"),
    # Adjustability / type
    ("verstellbar", "adjustable"), ("einstellbar", "adjustable"),
    ("regelbar", "adjustable"), ("elektrisch", "electric"),
    ("elektronisch", "electronic"), ("mechanisch", "mechanical"),
    ("hydraulisch", "hydraulic"), ("pneumatisch", "pneumatic"),
    ("automatisch", "automatic"), ("manuell", "manual"),
    ("komplett", "complete"), ("vollständig", "complete"),
    ("universal", "universal"), ("universell", "universal"),
    ("umbau", "conversion"), ("nachrüstset", "retrofit kit"),
    ("retrofit", "retrofit"),
    # Selling terms
    ("sofort verfügbar", "in stock"), ("auf lager", "in stock"),
    ("versandkosten", "shipping cost"), ("kostenloser versand", "free shipping"),
    ("lieferung", "delivery"), ("versand", "shipping"),
    ("zahlung", "payment"), ("paypal", "PayPal"),
    ("1 stück", "1 piece"), ("stück", "pieces"), ("stk", "pcs"),
    ("set", "set"), ("satz", "set"),
    # Compound words that appear on Autodoc/eBay titles
    ("steuerkettensatz", "timing chain kit"), ("steuerkette", "timing chain"),
    ("verschlussschraube", "sealing screw"), ("verschlussschrauben", "sealing screws"),
    ("verzinkt", "zinc-plated"), ("verchromt", "chrome-plated"),
    ("kupferdichtung", "copper gasket"), ("kupferdichtungen", "copper gaskets"),
    ("dreiteilig", "three-piece"), ("zweiteilig", "two-piece"),
    ("einteilig", "one-piece"), ("mehrteilig", "multi-piece"),
    ("spezialwerkzeug", "special tool"), ("werkzeug", "tool"),
    ("zur montage", "for installation"), ("montage", "installation"),
    ("abgasrückführung", "EGR"), ("abgasrückfuhrung", "EGR"),
    ("einspritzpumpe", "injection pump"), ("hochdruckpumpe", "high-pressure pump"),
    ("zahnkranz", "ring gear"), ("kranz", "gear ring"),
    ("anlasser ritzel", "starter pinion"), ("lager", "bearing"),
    ("kugellager", "ball bearing"), ("nadellager", "needle bearing"),
    ("gleitlager", "plain bearing"), ("funkenstrecke", "spark gap"),
    ("schieber", "slider"), ("biegegelenk", "flex joint"),
    ("scheibenwischerblätter", "wiper blades"), ("wischerblätter", "wiper blades"),
    ("abdeckblende", "trim cover"), ("blende", "trim"),
    ("kabeldurchführung", "grommet"), ("durchführung", "grommet"),
    ("selbstsichernde murter", "self-locking nut"),
    ("tellerfeder", "disc spring"), ("druckfeder", "compression spring"),
    ("hosenträger", "braces"), ("spurstangenkopf komplett", "track rod end assembly"),
    ("befestigungsmaterial", "mounting kit"), ("anbauteile", "attachments"),
    ("anbauteilen", "attachments"), ("anbauteil", "attachment"),
    ("verschleißteile", "wear parts"), ("verschleissteile", "wear parts"),
    ("verschleiß", "wear"),
]

_CATALOG_DERIVED = _catalog_glossary()

_GLOSSARY = _GLOSSARY + _CATALOG_DERIVED + _EXTRA_GLOSSARY

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
    Unknown words are left as-is.

    Longer English phrases are matched first ('timing belt kit' before
    'timing belt'); when several German words share one English word the
    shortest German form wins so 'for' maps back to 'für'."""
    if not phrase:
        return ""
    out = str(phrase).strip()
    for item in _EN_TO_DE:
        out = item["rgx"].sub(item["de"], out)
    return out


# Reverse table: built once from the glossary so an English phrase can be
# turned back into a German search keyword. For words with several German
# translations the shortest German form wins ('for' -> 'für'), and longer
# English phrases are applied first ('timing belt kit' before 'timing belt').
_EN_TO_DE = []
_seen_en = set()
for de, en in sorted(_GLOSSARY, key=lambda pair: (pair[1].lower(), len(pair[0]))):
    key = en.lower() if en else ""
    if not key or not any(ch.isalnum() for ch in key) or key in _seen_en:
        continue
    _seen_en.add(key)
    _EN_TO_DE.append({
        "rgx": re.compile(r"\b" + re.escape(en) + r"\b", re.IGNORECASE),
        "de": de,
        "n": len(en),
    })
_EN_TO_DE.sort(key=lambda item: -item["n"])


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