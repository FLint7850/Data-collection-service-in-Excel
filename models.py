from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    legacy_id: Mapped[str] = mapped_column(String(32), default="", nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    thread_count: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    exclusions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    product_url_filters: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    product_url_exclusions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    extraction_rules: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    auto_cleanup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    connection_method: Mapped[str] = mapped_column(String(64), default="requests", nullable=False)
    auto_connection_fallback: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_users_username", "username"),)


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(32), default="daily", nullable=False)
    scan_time: Mapped[str] = mapped_column(String(8), default="01:00", nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    primary_donor_id: Mapped[int | None] = mapped_column(ForeignKey("donors.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    donors: Mapped[list["Donor"]] = relationship(
        "Donor",
        back_populates="brand",
        cascade="all, delete-orphan",
        foreign_keys="Donor.brand_id",
    )
    primary_donor: Mapped["Donor | None"] = relationship(
        "Donor",
        foreign_keys=[primary_donor_id],
        post_update=True,
    )

    __table_args__ = (
        Index("ix_brands_name", "name"),
        UniqueConstraint("name", "group_name", name="uq_brands_name_group_name"),
    )


class Donor(Base):
    __tablename__ = "donors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    legacy_id: Mapped[str] = mapped_column(String(32), default="", nullable=False, unique=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    site_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    start_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    thread_count: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("connection_methods.id"), nullable=True)
    auto_connection_fallback: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    exclusions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    product_url_filters: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    product_url_exclusions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    extraction_rules: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    selector_settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    seen_models: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    known_new_products: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    brand: Mapped[Brand] = relationship("Brand", back_populates="donors", foreign_keys=[brand_id])
    connection_method_row: Mapped["ConnectionMethod | None"] = relationship("ConnectionMethod")

    __table_args__ = (Index("ix_donors_brand_id", "brand_id"),)


class ConnectionMethod(Base):
    __tablename__ = "connection_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class OwnSite(Base):
    __tablename__ = "own_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    feed_url: Mapped[str] = mapped_column(Text, nullable=False)
    feed_generate_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("feed_url", name="uq_own_sites_feed_url"),)


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    auto_cleanup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    smtp: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    feed_storage: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class FileImport(Base):
    __tablename__ = "file_import"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    exclusions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    model_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    replace_rules: Mapped[str] = mapped_column(Text, default="", nullable=False)
    export_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    file: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
