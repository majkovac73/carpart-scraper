#!/usr/bin/env python3
"""Copy the local SQLite database into the hosted Postgres DB that Render uses.

Render's free plan has no persistent disk, so the live site must read from a
hosted Postgres (e.g. Neon). Run this once after wiring up the remote DB, and
again any time you want to push newly collected deals to the live site. It is
idempotent and batched (2 roundtrips per table) so it is fast even over a
remote connection.

Usage (set the remote URL first; note the +psycopg scheme):
    $env:SQLALCHEMY_DATABASE_URL = "postgresql+psycopg://USER:PASS@ep-xxx.region.aws.neon.tech/neondb?sslmode=require"
    python sync_to_remote.py

The script also reads SQLALCHEMY_DATABASE_URL from the local .env file
automatically, so plain `python sync_to_remote.py` works once .env has it.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

REMOTE_URL = os.getenv("SQLALCHEMY_DATABASE_URL")
if not REMOTE_URL:
    sys.exit(
        "Set SQLALCHEMY_DATABASE_URL to your hosted Postgres URL first, e.g.\n"
        '  $env:SQLALCHEMY_DATABASE_URL = "postgresql+psycopg://USER:PASS@ep-xxx.region.aws.neon.tech/neondb?sslmode=require"'
    )

from sqlalchemy import create_engine, select, insert, delete
from sqlalchemy.orm import sessionmaker

from database import (Base, Brand, VehicleModel, Deal, DealClick,
                      deal_model_association, _ensure_columns)

LOCAL_URL = os.getenv("LOCAL_DB_URL", "sqlite:///./deals.db")
FIELDS = [
    "title", "title_en", "retail_price", "sale_price", "discount_percentage",
    "average_price", "image_url", "source_url", "affiliate_link", "status",
    "clicks", "brand_name", "part_de", "part_en", "source", "vehicle_brand",
    "updated_at",
]


def _sess(engine):
    return sessionmaker(bind=engine)()


def main():
    local_engine = create_engine(LOCAL_URL)
    remote_engine = create_engine(REMOTE_URL)
    Base.metadata.create_all(bind=remote_engine)
    _ensure_columns(remote_engine, "deals", {
        "clicks": "clicks INTEGER DEFAULT 0",
        "brand_name": "brand_name VARCHAR(200)",
        "part_de": "part_de VARCHAR(200)",
        "part_en": "part_en VARCHAR(200)",
        "source": "source VARCHAR(64)",
        "vehicle_brand": "vehicle_brand VARCHAR(500)",
        "updated_at": "updated_at VARCHAR(32)",
    })

    l = _sess(local_engine)
    r = _sess(remote_engine)

    # Brands
    l_brands = list(l.scalars(select(Brand)))
    r_brands = {b.name: b.id for b in r.scalars(select(Brand))}
    missing = [{"name": b.name} for b in l_brands if b.name not in r_brands]
    if missing:
        r.execute(insert(Brand), missing)
        r.flush()
    r_brands = {b.name: b.id for b in r.scalars(select(Brand))}
    brand_id_map = {b.id: r_brands[b.name] for b in l_brands}

    # Models
    l_models = list(l.scalars(select(VehicleModel)))
    r_models = {(m.brand_id, m.name) for m in r.scalars(select(VehicleModel))}
    missing = [
        {"name": m.name, "brand_id": brand_id_map[m.brand_id]}
        for m in l_models
        if m.brand_id in brand_id_map
        and (brand_id_map[m.brand_id], m.name) not in r_models
    ]
    if missing:
        r.execute(insert(VehicleModel), missing)
        r.flush()
    r_models = {(m.brand_id, m.name): m.id for m in r.scalars(select(VehicleModel))}
    model_id_map = {
        m.id: r_models[(brand_id_map[m.brand_id], m.name)]
        for m in l_models
        if m.brand_id in brand_id_map
    }

    # Deals
    l_deals = list(l.scalars(select(Deal)))
    r_deals = {d.product_id: d for d in r.scalars(select(Deal))}
    inserted = updated = 0
    to_insert = []
    for d in l_deals:
        existing = r_deals.get(d.product_id)
        if existing is None:
            to_insert.append({"product_id": d.product_id, **{f: getattr(d, f) for f in FIELDS}})
            inserted += 1
        else:
            for f in FIELDS:
                setattr(existing, f, getattr(d, f))
            updated += 1
    if to_insert:
        r.execute(insert(Deal), to_insert)
        r.flush()

    # Deals purged locally are removed remotely too (full mirror), so junk or
    # withdrawn items never stay live. Their deal-model links go first because
    # the association table has no cascade.
    local_pids = {d.product_id for d in l_deals}
    stale = [d for pid, d in r_deals.items() if pid not in local_pids]
    deleted = 0
    if stale:
        stale_ids = [d.id for d in stale]
        r.execute(delete(deal_model_association).where(deal_model_association.c.deal_id.in_(stale_ids)))
        r.execute(delete(DealClick).where(DealClick.deal_id.in_(stale_ids)))
        r.execute(delete(Deal).where(Deal.id.in_(stale_ids)))
        r.flush()
        deleted = len(stale_ids)

    r_deals = {d.product_id: d.id for d in r.scalars(select(Deal))}
    deal_id_map = {d.id: r_deals[d.product_id] for d in l_deals}

    # Deal-model links
    r_assoc = {tuple(row) for row in r.execute(select(deal_model_association))}
    assoc_rows = list(l.execute(select(deal_model_association)))
    to_add = []
    for deal_id, model_id in assoc_rows:
        r_deal = deal_id_map.get(deal_id)
        r_model = model_id_map.get(model_id)
        if r_deal is None or r_model is None:
            continue
        if (r_deal, r_model) not in r_assoc:
            to_add.append({"deal_id": r_deal, "model_id": r_model})
    if to_add:
        r.execute(deal_model_association.insert(), to_add)

    r.commit()

    n_brands = len(r_brands)
    n_models = len(r_models)
    n_deals = len(r_deals)
    n_assoc = len(r_assoc) + len(to_add)
    print("Sync complete:")
    print(f"  brands: {n_brands} | models: {n_models}")
    print(f"  deals: {n_deals} ({inserted} inserted, {updated} updated, {deleted} deleted)")
    print(f"  deal-model links: {n_assoc} ({len(to_add)} added)")


if __name__ == "__main__":
    main()