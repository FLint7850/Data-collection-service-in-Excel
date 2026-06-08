from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    thread_count: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    exclusions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    product_url_filters: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    extraction_rules: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    auto_cleanup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    connection_method: Mapped[str] = mapped_column(String(64), default="requests", nullable=False)
    auto_connection_fallback: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    group_type: Mapped[str] = mapped_column(String(32), default="non_margin", nullable=False)
    collapsed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    donors: Mapped[list["Donor"]] = relationship("Donor", back_populates="brand", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_brands_name", "name"),
        UniqueConstraint("name", "group_type", name="uq_brands_name_group_type"),
    )


class Donor(Base):
    __tablename__ = "donors"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    site_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    start_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(32), default="daily", nullable=False)
    scan_time: Mapped[str] = mapped_column(String(8), default="01:00", nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_run_at: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    thread_count: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    connection_method: Mapped[str] = mapped_column(String(64), default="requests", nullable=False)
    auto_connection_fallback: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    exclusions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    product_url_filters: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    extraction_rules: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    selector_settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    seen_models: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    known_new_products: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    brand: Mapped[Brand] = relationship("Brand", back_populates="donors")

    __table_args__ = (Index("ix_donors_brand_id", "brand_id"),)


class OwnSite(Base):
    __tablename__ = "own_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feed_url: Mapped[str] = mapped_column(Text, nullable=False)
    feed_generate_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    products: Mapped[list["FeedProduct"]] = relationship("FeedProduct", back_populates="own_site", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("feed_url", name="uq_own_sites_feed_url"),)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    found_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class FeedProduct(Base):
    __tablename__ = "feed_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    own_site_id: Mapped[int] = mapped_column(ForeignKey("own_sites.id", ondelete="CASCADE"), nullable=False)
    model_key: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    vendor_code: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    name: Mapped[str] = mapped_column(Text, default="", nullable=False)
    url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    own_site: Mapped[OwnSite] = relationship("OwnSite", back_populates="products")

    __table_args__ = (
        Index("ix_feed_products_model_key", "model_key"),
        Index("ix_feed_products_vendor_code", "vendor_code"),
    )


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    time: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    level: Mapped[str] = mapped_column(String(32), default="info", nullable=False)
    message: Mapped[Text] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
