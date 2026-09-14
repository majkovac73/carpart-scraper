"""Steady-cadence helpers: which eBay keywords are due for a rescan, and
cleaning up stale catalog entries so the index does not rot.

The pipeline no longer rewrites the same keywords every run: each keyword is
rescanned at most once per `interval_hours`, so the eBay sweep stays cheap
(there are 119 keywords) and a schedule can loop forever.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete

from database import EbayKeywordLog, Deal, deal_model_association
from parts_catalog import EBAY_KEYWORDS

# Catalog/search rows that are safe to drop when they go stale.
_STALE_DELETABLE = ("search", "catalog")


def due_ebay_keywords(db, interval_hours: float = 6.0) -> list:
    """List of part keywords not scanned within the interval (all on first
    run)."""
    rows = {r.keyword: r for r in db.query(EbayKeywordLog).all()}
    now = datetime.now()
    due = []
    for kw in EBAY_KEYWORDS:
        r = rows.get(kw)
        if r is None or not r.scanned_at:
            due.append(kw)
            continue
        try:
            when = datetime.fromisoformat(r.scanned_at)
        except (TypeError, ValueError):
            due.append(kw)
            continue
        if now - when >= timedelta(hours=interval_hours):
            due.append(kw)
    return due


def mark_ebay_scanned(db, keyword: str, found_count: int):
    row = db.query(EbayKeywordLog).filter(EbayKeywordLog.keyword == keyword).first()
    if row is None:
        row = EbayKeywordLog(keyword=keyword)
        db.add(row)
    row.scanned_at = datetime.now().isoformat(timespec="seconds")
    row.found_count = found_count
    db.commit()


def purge_stale_ebay(db, days: int = 14):
    """Drops stale non-deal eBay rows (catalog/search snapshots) that have not
    been re-sighted. Real (pending/published) deals are kept on purpose."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    stale = (
        db.query(Deal)
        .filter(Deal.source == "ebay")
        .filter(Deal.status.in_(_STALE_DELETABLE))
        .filter(Deal.updated_at < cutoff)
        .all()
    )
    ids = [d.id for d in stale]
    if not ids:
        return 0
    db.execute(delete(deal_model_association).where(deal_model_association.c.deal_id.in_(ids)))
    for d in stale:
        db.delete(d)
    db.commit()
    return len(ids)