from sqlalchemy.orm import Session
from database import Deal, Brand, VehicleModel

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
    image_url: str = None, 
    affiliate_link: str = None,
    compatible_vehicles: list[dict] = None
):
    """Saves a newly scraped deal as 'pending' and links compatible car models."""
    db_deal = Deal(
        product_id=product_id,
        title=title,
        retail_price=retail_price,
        sale_price=sale_price,
        discount_percentage=discount_percentage,
        image_url=image_url,
        affiliate_link=affiliate_link,
        status="pending"
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