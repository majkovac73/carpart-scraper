#!/usr/bin/env python3
"""Copy the local SQLite database into the hosted Postgres DB that Render uses.

Render's free plan has no persistent disk, so the live site must read from a
hosted Postgres (e.g. Neon). Run this once after wiring up the remote DB, and
again any time you want to push newly collected deals to the live site. It is
idempotent: brands/models/deals are upserted, deal-model links are added only
when missing.

Usage (set the remote URL first; note the +psycopg scheme):
    $env:SQLALCHEMY_DATABASE_URL = "postgresql+psycopg://USER:PASS@ep-xxx.region.aws.neon.tech/neondb?sslmode=require"
    python sync_to_remote.py
"""
import os
import sys

REMOTE_URL = os.getenv("SQLALCHEMY_DATABASE_URL")
if not REMOTE_URL:
    sys.exit(
        "Set SQLALCHEMY_DATABASE_URL to your hosted Postgres URL first, e.g.\n"
        '  $env:SQLALCHEMY_DATABASE_URL = "postgresql+psycopg://USER:PASS@ep-xxx.region.aws.neon.tech/neondb?sslmode=require"'
    )

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database import Base, Brand, VehicleModel, Deal, deal_model_association

LOCAL_URL = os.getenv("LOCAL_DB_URL", "sqlite:///./deals.db")


def _sess(engine):
    return sessionmaker(bind=engine)()


def main():
    local_engine = create_engine(LOCAL_URL)
    remote_engine = create_engine(REMOTE_URL)
    Base.metadata.create_all(bind=remote_engine)

    l = _sess(local_engine)
    r = _sess(remote_engine)

    brand_id_map = {}
    for b in l.execute(select(Brand)).scalars():
        existing = r.execute(select(Brand).where(Brand.name == b.name)).scalar_one_or_none()
        if existing is None:
            existing = Brand(name=b.name)
            r.add(existing)
            r.flush()
        brand_id_map[b.id] = existing.id

    model_id_map = {}
    for m in l.execute(select(VehicleModel)).scalars():
        rb_id = brand_id_map.get(m.brand_id)
        if rb_id is None:
            continue
        existing = r.execute(
            select(VehicleModel).where(
                VehicleModel.name == m.name, VehicleModel.brand_id == rb_id
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = VehicleModel(name=m.name, brand_id=rb_id)
            r.add(existing)
            r.flush()
        model_id_map[m.id] = existing.id

    fields = [
        "title", "title_en", "retail_price", "sale_price", "discount_percentage",
        "average_price", "image_url", "source_url", "affiliate_link", "status",
    ]
    deal_id_map = {}
    inserted = updated = 0
    for d in l.execute(select(Deal)).scalars():
        existing = r.execute(
            select(Deal).where(Deal.product_id == d.product_id)
        ).scalar_one_or_none()
        if existing is None:
            existing = Deal(product_id=d.product_id, title=d.title)
            r.add(existing)
            inserted += 1
        else:
            updated += 1
        for f in fields:
            setattr(existing, f, getattr(d, f))
        r.flush()
        deal_id_map[d.id] = existing.id

    added_assoc = 0
    for row in l.execute(select(deal_model_association)).all():
        r_deal_id = deal_id_map.get(row.deal_id)
        r_model_id = model_id_map.get(row.model_id)
        if r_deal_id is None or r_model_id is None:
            continue
        already = r.execute(
            select(deal_model_association).where(
                deal_model_association.c.deal_id == r_deal_id,
                deal_model_association.c.model_id == r_model_id,
            )
        ).first()
        if already is None:
            r.execute(
                deal_model_association.insert().values(
                    deal_id=r_deal_id, model_id=r_model_id
                )
            )
            added_assoc += 1

    r.commit()

    n_brands = r.execute(select(Brand)).all().__len__()
    n_models = r.execute(select(VehicleModel)).all().__len__()
    n_deals = r.execute(select(Deal)).all().__len__()
    n_assoc = r.execute(select(deal_model_association)).all().__len__()
    print("Sync complete:")
    print(f"  brands: {n_brands} | models: {n_models}")
    print(f"  deals: {n_deals} ({inserted} inserted, {updated} updated)")
    print(f"  deal-model links: {n_assoc} ({added_assoc} added)")


if __name__ == "__main__":
    main()