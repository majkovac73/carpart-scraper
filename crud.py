import os

from sqlalchemy import or_, literal
from sqlalchemy.orm import Session
from database import Deal, Brand, VehicleModel

# Catalog rows ("every scraped product, tagged with a part") are searchable on
# the website but must never appear on the deal lists / broadcasts.
NON_DEAL_STATUSES = ["search", "catalog"]

# Alternate names for the same car maker. The scrapers / deal data may use
# "VW" while the catalog uses "Volkswagen", and people type "Mercedes".
# Matching any name of the pair counts as a hit for the same brand.
BRAND_ALIASES = {
    "VW": "Volkswagen",
    "Mercedes": "Mercedes-Benz",
}


def brand_aliases(name: str) -> list:
    """Term plus any known synonym of the same car maker (bidirectional)."""
    up = (name or "").strip()
    if not up:
        return []
    names = {up}
    for a, b in BRAND_ALIASES.items():
        if up.upper() == a.upper() or up.upper() == b.upper():
            names.add(a)
            names.add(b)
    return list(names)

# -------------------------------------------------------------------
# BRAND HELPERS
# -------------------------------------------------------------------
def get_or_create_brand(db: Session, brand_name: str) -> Brand:
    """Gets an existing Brand or creates a new one (case-insensitive)."""
    normalized_name = brand_name.strip()
    brand = db.query(Brand).filter(Brand.name.ilike(normalized_name)).first()
    
    if not brand:
        brand = Brand(name=normalized_name)
        db.add(brand)
        db.commit()
        db.refresh(brand)
        
    return brand

# -------------------------------------------------------------------
# VEHICLE MODEL HELPERS
# -------------------------------------------------------------------
def get_or_create_vehicle_model(db: Session, brand_name: str, model_name: str) -> VehicleModel:
    """
    Gets or creates a specific vehicle variant linked to its parent brand.
    Distinguishes precise trims/engines (e.g., 'Cruze 2.0 Diesel' vs 'Cruze 1.4 Turbo').
    """
    brand = get_or_create_brand(db, brand_name)
    normalized_model = model_name.strip()
    model = (
        db.query(VehicleModel)
        .filter(
            VehicleModel.brand_id == brand.id,
            VehicleModel.name.ilike(normalized_model)
        )
        .first()
    )
    
    if not model:
        model = VehicleModel(name=normalized_model, brand_id=brand.id)
        db.add(model)
        db.commit()
        db.refresh(model)
        
    return model

# -------------------------------------------------------------------
# READ OPERATIONS
# -------------------------------------------------------------------
def get_deal_by_product_id(db: Session, product_id: str):
    """Checks if a deal already exists to prevent duplicate posts."""
    return db.query(Deal).filter(Deal.product_id == product_id).first()

def get_deal_by_id(db: Session, deal_id: int):
    """Fetches a single deal by its internal primary key."""
    return db.query(Deal).filter(Deal.id == deal_id).first()

def get_pending_deals(db: Session, limit: int = 10):
    """Fetches unsent deals for the Telegram/X bot to process."""
    return db.query(Deal).filter(Deal.status == "pending").limit(limit).all()

def get_published_deals(db: Session, skip: int = 0, limit: int = 20):
    """Fetches published deals to display on the Next.js static site."""
    return db.query(Deal).filter(Deal.status == "published").offset(skip).limit(limit).all()

def get_all_deals(db: Session, skip: int = 0, limit: int = 50):
    """Newest deals first, regardless of status."""
    return (
        db.query(Deal)
        .order_by(Deal.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_good_deals(
    db: Session,
    skip: int = 0,
    limit: int = 20,
    min_discount: float = None,
    source: str = None,
):
    """Real deals only: cached 'search' snapshots and tagged 'catalog' products
    are excluded and only offers at least `min_discount`% below the market
    average are shown (default from the MIN_DISCOUNT env / 15). Best discount
    first; pass source="ebay"/"autodoc" to restrict to one marketplace."""
    if min_discount is None:
        min_discount = float(os.getenv("MIN_DISCOUNT", "15"))
    q = (
        db.query(Deal)
        .filter(
            Deal.status.notin_(NON_DEAL_STATUSES),
            Deal.discount_percentage >= min_discount,
        )
    )
    if source:
        q = q.filter(Deal.source == source)
    return (
        q.order_by(
            Deal.source.desc(),              # eBay first (revenue source)
            Deal.discount_percentage.desc(),
            Deal.id.desc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


def deal_worth_showing(deal, min_discount: float = None) -> bool:
    """True when a deal is a 'real' deal (not a cached search snapshot or a
    plain catalog product)."""
    if min_discount is None:
        min_discount = float(os.getenv("MIN_DISCOUNT", "15"))
    if getattr(deal, "status", None) in NON_DEAL_STATUSES:
        return False
    try:
        return float(getattr(deal, "discount_percentage", 0) or 0) >= min_discount
    except (TypeError, ValueError):
        return False

def get_site_stats(db: Session) -> dict:
    """Quick stats for the homepage: total indexed, total deals, last updated."""
    from sqlalchemy import func
    total = db.query(Deal).count()
    deals = db.query(Deal).filter(Deal.status.notin_(NON_DEAL_STATUSES)).count()
    last = db.query(Deal.updated_at).filter(Deal.updated_at.isnot(None)).order_by(Deal.updated_at.desc()).first()
    return {
        "total_indexed": total,
        "total_deals": deals,
        "last_updated": (last[0] or "")[:10] if last else "",
    }


def get_models_by_brand(db: Session, brand_name: str = None):
    """All vehicle models, optionally filtered by brand (for the search form)."""
    query = db.query(VehicleModel).join(VehicleModel.brand)
    if brand_name and brand_name.strip():
        query = query.filter(Brand.name.ilike(brand_name.strip()))
    return query.order_by(Brand.name, VehicleModel.name).all()

def search_deals(db: Session, brand: str = None, model: str = None,
                 q: str = None, part: str = None, mbrand: str = None,
                 skip: int = 0, limit: int = 60):
    """Finds offers across the indexed catalog by car, part and/or keyword.

    - brand/model: exact-fit Autodoc deals via their model links, PLUS eBay
      parts whose title mentions the selected car make (the ``vehicle_brand``
      column stores every car name seen in the listing title).
    - part: matches the catalog part tags (English or German keyword).
    - mbrand: filters by part maker (brand_name column).
    - q: free text over the stored titles (English + German).

    Real deals are returned before plain catalog rows, each group best
    discount first.
    """
    query = db.query(Deal)
    if brand or model or q or part or mbrand:
        query = query.outerjoin(Deal.compatible_models).outerjoin(VehicleModel.brand).distinct()
        if brand and brand.strip():
            term = brand.strip()
            query = query.filter(or_(
                Brand.name.in_(brand_aliases(term)),
                Brand.name.ilike(f"%{term}%"),
                literal(term).contains(Brand.name),
                Deal.vehicle_brand.ilike(f"%{term}%"),
            ))
        if model and model.strip():
            term = model.strip()
            query = query.filter(or_(
                VehicleModel.name.ilike(f"%{term}%"),
                literal(term).contains(VehicleModel.name),
            ))
        if part and part.strip():
            term = part.strip()
            query = query.filter(or_(
                Deal.part_de.ilike(term),
                Deal.part_en.ilike(term),
            ))
        if mbrand and mbrand.strip():
            term = mbrand.strip()
            query = query.filter(Deal.brand_name.ilike(f"%{term}%"))
        if q and q.strip():
            term = q.strip()
            query = query.filter(
                or_(
                    Deal.title.ilike(f"%{term}%"),
                    Deal.title_en.ilike(f"%{term}%"),
                    Deal.part_en.ilike(f"%{term}%"),
                    Deal.part_de.ilike(f"%{term}%"),
                    Deal.product_id.ilike(f"%{term}%"),
                    VehicleModel.name.ilike(f"%{term}%"),
                )
            )

    rows = query.order_by(Deal.discount_percentage.desc()).all()
    deals = [d for d in rows if d.status not in NON_DEAL_STATUSES]
    catalog = [d for d in rows if d.status in NON_DEAL_STATUSES]
    deals.sort(key=lambda d: (0 if d.source == "ebay" else 1, -(d.discount_percentage or 0)))
    catalog.sort(key=lambda d: ((d.sale_price or 0)))
    merged = deals + catalog
    return merged[skip:skip + limit]

# -------------------------------------------------------------------
# CREATE OPERATIONS
# -------------------------------------------------------------------
def create_deal(
    db: Session, 
    product_id: str, 
    title: str, 
    sale_price: float, 
    discount_percentage: float, 
    retail_price: float = None, 
    average_price: float = None,
    title_en: str = None,
    image_url: str = None,
    source_url: str = None,
    affiliate_link: str = None,
    compatible_vehicles: list[dict] = None,
    status: str = "pending",
    brand_name: str = None,
    part_de: str = None,
    part_en: str = None,
    source: str = None,
    vehicle_brand: str = None,
    updated_at: str = None,
):
    """Saves a newly scraped deal as 'pending' and links compatible car models."""
    db_deal = Deal(
        product_id=product_id,
        title=title,
        title_en=title_en,
        retail_price=retail_price,
        sale_price=sale_price,
        discount_percentage=discount_percentage,
        average_price=average_price,
        image_url=image_url,
        source_url=source_url,
        affiliate_link=affiliate_link,
        status=status,
        brand_name=brand_name,
        part_de=part_de,
        part_en=part_en,
        source=source,
        vehicle_brand=vehicle_brand,
        updated_at=updated_at,
    )
    
    if compatible_vehicles:
        for vehicle in compatible_vehicles:
            brand_name_v = vehicle.get("brand")
            model_name = vehicle.get("model")
            
            if brand_name_v and model_name:
                model_obj = get_or_create_vehicle_model(db, brand_name_v, model_name)
                if model_obj not in db_deal.compatible_models:
                    db_deal.compatible_models.append(model_obj)
    
    db.add(db_deal)
    db.commit()
    db.refresh(db_deal)
    return db_deal


def upsert_deal(
    db: Session,
    product_id: str,
    title: str,
    sale_price: float,
    discount_percentage: float,
    retail_price: float = None,
    average_price: float = None,
    title_en: str = None,
    image_url: str = None,
    source_url: str = None,
    affiliate_link: str = None,
    compatible_vehicles: list[dict] = None,
    status: str = "catalog",
    brand_name: str = None,
    part_de: str = None,
    part_en: str = None,
    source: str = None,
    vehicle_brand: str = None,
    updated_at: str = None,
):
    """Adds the product to the indexed catalog; creates the row if missing,
    refreshes prices/freshness if present. Once a product has been promoted to
    a real deal (pending/published) its status is never downgraded."""
    row = get_deal_by_product_id(db, product_id)
    if row is None:
        return create_deal(
            db, product_id=product_id, title=title, sale_price=sale_price,
            discount_percentage=discount_percentage, retail_price=retail_price,
            average_price=average_price, title_en=title_en,
            image_url=image_url, source_url=source_url,
            affiliate_link=affiliate_link, compatible_vehicles=compatible_vehicles,
            status=status, brand_name=brand_name, part_de=part_de, part_en=part_en,
            source=source, vehicle_brand=vehicle_brand, updated_at=updated_at,
        )

    row.title = title
    row.title_en = title_en
    row.retail_price = retail_price
    row.sale_price = sale_price
    row.discount_percentage = discount_percentage
    row.average_price = average_price or row.average_price
    row.image_url = image_url or row.image_url
    row.source_url = source_url
    row.affiliate_link = affiliate_link or row.affiliate_link
    row.brand_name = brand_name or row.brand_name
    row.part_de = part_de or row.part_de
    row.part_en = part_en or row.part_en
    row.source = source or row.source
    row.vehicle_brand = vehicle_brand or row.vehicle_brand
    row.updated_at = updated_at

    if row.status in NON_DEAL_STATUSES and status not in NON_DEAL_STATUSES:
        row.status = status

    if compatible_vehicles:
        for vehicle in compatible_vehicles:
            b, m = vehicle.get("brand"), vehicle.get("model")
            if b and m:
                model_obj = get_or_create_vehicle_model(db, b, m)
                if model_obj not in row.compatible_models:
                    row.compatible_models.append(model_obj)

    db.add(row)
    db.commit()
    db.refresh(row)
    return row

# -------------------------------------------------------------------
# UPDATE OPERATIONS
# -------------------------------------------------------------------
def update_deal_status(db: Session, deal_id: int, new_status: str = "published"):
    """Flips status from 'pending' to 'published' once broadcasted."""
    db_deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if db_deal:
        db_deal.status = new_status
        db.commit()
        db.refresh(db_deal)
    return db_deal