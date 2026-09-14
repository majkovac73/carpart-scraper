"""Search planner - covers every model x every part over time.

The pipeline used to hammer the same 9 hardcoded combos on every run. Instead,
this module builds the full (part x brand x model) cross product from the local
catalog and hands out a random, never-searched-first sample per run. Each combo
is recorded in `search_log`; once the whole catalog has been tried once, older
searches get re-visited (oldest first), so the site keeps finding new price
drops everywhere over time.
"""

import random
from datetime import datetime

from sqlalchemy import select

from database import Brand, VehicleModel, SearchLog
from parts_catalog import PARTS, EBAY_KEYWORDS


def _clean_model_name(name: str) -> str:
    """Drops generation notes like '(5F) CC(5F)' from catalog model names so the
    Autodoc keyword search stays readable ('Golf 6', 'Passat', 'A4 B8'...)."""
    return " ".join(((name or "").split("(")[0]).split())


def iter_combos(db):
    """All (part, brand, model) combos from the catalog, one combo per model."""
    rows = db.execute(
        select(VehicleModel, Brand).join(Brand, VehicleModel.brand_id == Brand.id)
    ).all()
    for vm, brand in rows:
        model = _clean_model_name(vm.name)
        if not model:
            continue
        for part in PARTS:
            yield {
                "part": part["de"],
                "part_en": part["en"],
                "brand": brand.name,
                "model": model,
            }


def build_plan(db, budget: int = 8, rng: random.Random = None):
    """Picks `budget` combos to search this run.

    Never-searched combos always come first (shuffled), then already-searched
    ones oldest-first. With a small budget per run this slowly walks the whole
    catalog and keeps sweeping it afterwards."""
    budget = max(1, int(budget))
    rng = rng or random

    logged = {
        (r.part, r.brand, r.model): r
        for r in db.scalars(select(SearchLog))
    }

    fresh, seen = [], []
    for combo in iter_combos(db):
        key = (combo["part"], combo["brand"], combo["model"])
        (seen if key in logged else fresh).append((key, combo))

    rng.shuffle(fresh)
    seen.sort(key=lambda kc: (logged[kc[0]].searched_at is None, logged[kc[0]].searched_at or ""))

    return [combo for _key, combo in (fresh + seen)[:budget]]


def record_result(db, combo, status: str, found_count: int = 0):
    """Upserts a (part, brand, model) row in search_log after a search attempt."""
    row = db.scalars(
        select(SearchLog).where(
            SearchLog.part == combo["part"],
            SearchLog.brand == combo["brand"],
            SearchLog.model == combo["model"],
        )
    ).first()
    if row is None:
        row = SearchLog(part=combo["part"], brand=combo["brand"], model=combo["model"])
        db.add(row)
    row.searched_at = datetime.now().isoformat(timespec="seconds")
    row.status = status
    row.found_count = found_count
    db.commit()


def coverage_stats(db):
    """Counts of fresh vs searched combos, for the run summary."""
    logged = db.scalars(select(SearchLog)).all()
    total = 0
    for _ in iter_combos(db):
        total += 1
    return {
        "total_combos": total,
        "searched": len(logged),
        "remaining": total - len(logged),
        "found": sum(1 for r in logged if r.status == "found"),
        "none": sum(1 for r in logged if r.status == "none"),
        "blocked": sum(1 for r in logged if r.status == "blocked"),
        "errors": sum(1 for r in logged if r.status == "error"),
    }