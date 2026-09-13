from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Table
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

SQLALCHEMY_DATABASE_URL = "sqlite:///./deals.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

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
    retail_price = Column(Float, nullable=True)
    sale_price = Column(Float, nullable=False)
    discount_percentage = Column(Float, nullable=False)
    image_url = Column(String, nullable=True)
    affiliate_link = Column(String, nullable=True)
    status = Column(String, default="pending") 
    
    # Links the deal to the specific car models it fits
    compatible_models = relationship("VehicleModel", secondary=deal_model_association, back_populates="deals")

# Create all tables automatically
Base.metadata.create_all(bind=engine)