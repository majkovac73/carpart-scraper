import os

from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Table, text, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

SQLALCHEMY_DATABASE_URL = os.getenv("SQLALCHEMY_DATABASE_URL", "sqlite:///./deals.db")

# SQLite (local dev): needs check_same_thread for FastAPI's threadpool.
# Postgres (Render/Neon etc.): keep connections resilient on shared hosts.
_is_sqlite = SQLALCHEMY_DATABASE_URL.startswith("sqlite")
if _is_sqlite:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

deal_model_association = Table(
    "deal_model",
    Base.metadata,
    Column("deal_id", Integer, ForeignKey("deals.id"), primary_key=True),
    Column("model_id", Integer, ForeignKey("models.id"), primary_key=True)
)


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False) 
    
    models = relationship("VehicleModel", back_populates="brand")

class VehicleModel(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    brand_id = Column(Integer, ForeignKey("brands.id"))
    
    brand = relationship("Brand", back_populates="models")
    deals = relationship("Deal", secondary=deal_model_association, back_populates="compatible_models")

class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(String, unique=True, index=True, nullable=False) 
    title = Column(String, nullable=False)
    title_en = Column(String, nullable=True)
    retail_price = Column(Float, nullable=True)
    sale_price = Column(Float, nullable=False)
    discount_percentage = Column(Float, nullable=False)
    average_price = Column(Float, nullable=True)
    image_url = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    affiliate_link = Column(String, nullable=True)
    status = Column(String, default="pending")
    clicks = Column(Integer, default=0)

    # --- Catalog / fit metadata (added for the indexed-search + fit filter) ---
    brand_name = Column(String, nullable=True)          # part maker (e.g. "FEBI BILSTEIN")
    part_de = Column(String, nullable=True)             # catalog part keyword (German)
    part_en = Column(String, nullable=True)             # catalog part name (English)
    source = Column(String, nullable=True)              # "autodoc" | "ebay"
    vehicle_brand = Column(String, nullable=True)       # car makes mentioned in title (eBay generic)
    updated_at = Column(String, nullable=True)          # ISO timestamp of last sighting (freshness)

    # Links the deal to the specific car models it fits
    compatible_models = relationship("VehicleModel", secondary=deal_model_association, back_populates="deals")


class DealClick(Base):
    """One row per outbound click on the 'View deal' links, so clicks can be
    counted independently of the marketing network's (delayed) dashboard."""

    __tablename__ = "deal_clicks"

    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), index=True, nullable=False)
    clicked_at = Column(String, nullable=False)  # ISO timestamp
    referer = Column(String, nullable=True)


class SearchLog(Base):
    """Tracks which (part, brand, model) combos the pipeline already tried, so a
    rotation scheduler can spread searches across the whole catalog over time
    and re-visit older ones instead of repeating the same set every run."""

    __tablename__ = "search_log"

    id = Column(Integer, primary_key=True, index=True)
    part = Column(String, nullable=False)
    brand = Column(String, nullable=False)
    model = Column(String, nullable=False)
    searched_at = Column(String, nullable=True)  # ISO timestamp (string, sortable)
    status = Column(String, nullable=True)  # found / none / blocked / error
    found_count = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("part", "brand", "model", name="uq_search_log_combo"),
    )

class EbayKeywordLog(Base):
    """When each eBay keyword was last scanned, so the hourly sweep only hits
    keywords that are due instead of hammering the same ones every run."""

    __tablename__ = "ebay_keyword_log"

    keyword = Column(String, primary_key=True)
    scanned_at = Column(String, nullable=True)  # ISO timestamp (string, sortable)
    found_count = Column(Integer, default=0)


# Create all tables automatically
Base.metadata.create_all(bind=engine)


def _ensure_columns(engine, table, columns):
    """Lightweight migration: adds missing columns to an existing table.

    Works on SQLite (checked via PRAGMA) and Postgres (checked via
    information_schema), so adding a column to a model is safe on old local
    copies and on already-deployed Neon/Render databases."""
    if str(engine.url).startswith("sqlite"):
        with engine.connect() as conn:
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            for name, ddl in columns.items():
                if name not in existing:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                        conn.commit()
                    except Exception:
                        pass
    else:
        with engine.begin() as conn:
            existing = {
                row[0]
                for row in conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name = '{table}'"
                ))
            }
            for name, ddl in columns.items():
                if name not in existing:
                    try:
                        conn.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {ddl}"
                        ))
                    except Exception:
                        pass


_ensure_columns(engine, "deals", {
    "average_price": "average_price FLOAT",
    "source_url": "source_url VARCHAR(1000)",
    "title_en": "title_en VARCHAR(1000)",
    "clicks": "clicks INTEGER DEFAULT 0",
    "brand_name": "brand_name VARCHAR(200)",
    "part_de": "part_de VARCHAR(200)",
    "part_en": "part_en VARCHAR(200)",
    "source": "source VARCHAR(64)",
    "vehicle_brand": "vehicle_brand VARCHAR(500)",
    "updated_at": "updated_at VARCHAR(32)",
})