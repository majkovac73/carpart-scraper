import os

from sqlalchemy import or_, literal
from sqlalchemy.orm import Session
from database import Deal, Brand, VehicleModel

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
):
    """Real deals only: cached 'search' snapshots are excluded and only offers
    at least `min_discount`% below the market average are shown (default from
    the MIN_DISCOUNT env / 15). Best discount first."""
    if min_discount is None:
        min_discount = float(os.getenv("MIN_DISCOUNT", "15"))
    return (
        db.query(Deal)
        .filter(
            Deal.status != "search",
            Deal.discount_percentage >= min_discount,
        )
        .order_by(Deal.discount_percentage.desc(), Deal.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def deal_worth_showing(deal, min_discount: float = None) -> bool:
    """True when a deal is a 'real' deal (not a cached search snapshot)."""
    if min_discount is None:
        min_discount = float(os.getenv("MIN_DISCOUNT", "15"))
    if getattr(deal, "status", None) == "search":
        return False
    try:
        return float(getattr(deal, "discount_percentage", 0) or 0) >= min_discount
    except (TypeError, ValueError):
        return False

def get_models_by_brand(db: Session, brand_name: str = None):
    """All vehicle models, optionally filtered by brand (for the search form)."""
    query = db.query(VehicleModel).join(VehicleModel.brand)
    if brand_name and brand_name.strip():
        query = query.filter(Brand.name.ilike(brand_name.strip()))
    return query.order_by(Brand.name, VehicleModel.name).all()

def search_deals(db: Session, brand: str = None, model: str = None,
                 q: str = None, skip: int = 0, limit: int = 60):
    """Finds deals by compatible car (brand + model) and/or free-text keyword.

    Brand/model matching is bidirectional: catalog name "3er (E46)" matches
    stored model "E46", and catalog "Volkswagen" matches stored brand "VW".
    """
    query = db.query(Deal)
    if brand or model or q:
        query = query.outerjoin(Deal.compatible_models).outerjoin(VehicleModel.brand).distinct()
        if brand and brand.strip():
            term = brand.strip()
            query = query.filter(or_(
                Brand.name.in_(brand_aliases(term)),
                Brand.name.ilike(f"%{term}%"),
                literal(term).contains(Brand.name),
            ))
        if model and model.strip():
            term = model.strip()
            query = query.filter(or_(
                VehicleModel.name.ilike(f"%{term}%"),
                literal(term).contains(VehicleModel.name),
            ))
        if q and q.strip():
            term = q.strip()
            query = query.filter(
                or_(
                    Deal.title.ilike(f"%{term}%"),
                    Deal.title_en.ilike(f"%{term}%"),
                    Deal.product_id.ilike(f"%{term}%"),
                    VehicleModel.name.ilike(f"%{term}%"),
                )
            )
    return (
        query.order_by(Deal.discount_percentage.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

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
        status=status
    )
    
    if compatible_vehicles:
        for vehicle in compatible_vehicles:
            brand_name = vehicle.get("brand")
            model_name = vehicle.get("model")
            
            if brand_name and model_name:
                model_obj = get_or_create_vehicle_model(db, brand_name, model_name)
                if model_obj not in db_deal.compatible_models:
                    db_deal.compatible_models.append(model_obj)
    
    db.add(db_deal)
    db.commit()
    db.refresh(db_deal)
    return db_deal

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