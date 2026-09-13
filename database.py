import os

from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Table, text
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
    
    # Links the deal to the specific car models it fits
    compatible_models = relationship("VehicleModel", secondary=deal_model_association, back_populates="deals")

# Create all tables automatically
Base.metadata.create_all(bind=engine)


def _ensure_columns(engine, table, columns):
    """Lightweight migration: adds missing columns to an existing table.
    SQLite-only helper (uses PRAGMA); Postgres/other hosts get full schemas
    via create_all above, so nothing to do there."""
    if not str(engine.url).startswith("sqlite"):
        return
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


_ensure_columns(engine, "deals", {
    "average_price": "average_price FLOAT",
    "source_url": "source_url VARCHAR(1000)",
    "title_en": "title_en VARCHAR(1000)",
})