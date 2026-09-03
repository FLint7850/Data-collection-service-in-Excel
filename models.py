from datetime import datetime

from datetime import UTC, date

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    """Keep current naive DB columns while deriving time from UTC explicitly."""
    return datetime.now(UTC).replace(tzinfo=None)


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
    persist_profile: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (Index("ix_users_username", "username"),)


class ApplicationLog(Base):
    __tablename__ = "application_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    brand: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    __table_args__ = (
        Index("ix_application_logs_created_at", "created_at"),
        Index("ix_application_logs_level", "level"),
    )


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    search_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(32), default="daily", nullable=False)
    scan_time: Mapped[str] = mapped_column(String(8), default="01:00", nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    primary_donor_id: Mapped[int | None] = mapped_column(ForeignKey("donors.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

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
        Index("ix_brands_search_name", "search_name"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    brand: Mapped[Brand] = relationship("Brand", back_populates="donors", foreign_keys=[brand_id])
    connection_method_row: Mapped["ConnectionMethod | None"] = relationship("ConnectionMethod")

    __table_args__ = (Index("ix_donors_brand_id", "brand_id"),)


class ConnectionMethod(Base):
    __tablename__ = "connection_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_browser_render: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_debug_visible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class OwnSite(Base):
    __tablename__ = "own_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    feed_url: Mapped[str] = mapped_column(Text, nullable=False)
    feed_generate_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

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
    price_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    replace_rules: Mapped[str] = mapped_column(Text, default="", nullable=False)
    export_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    file: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class PriceConverter(Base):
    __tablename__ = "price_converter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    model_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    price_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    promo_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    promo_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sheet_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    export_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    file: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class FeedComparison(Base):
    __tablename__ = "feed_comparisons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    export_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class SupplierFeed(Base):
    __tablename__ = "supplier_feeds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    feed_url: Mapped[str] = mapped_column(Text, nullable=False)
    model_field: Mapped[str] = mapped_column(String(255), nullable=False)
    name_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    price_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    brand_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    url_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    exclusions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    replace_rules: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("feed_url", name="uq_supplier_feeds_feed_url"),)


class AttributeCategory(Base):
    __tablename__ = "attribute_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_path: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    templates: Mapped[list["AttributeTemplate"]] = relationship(
        "AttributeTemplate", back_populates="category", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("full_path", name="uq_attribute_categories_full_path"),)


class AttributeTemplate(Base):
    __tablename__ = "attribute_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("attribute_categories.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_type: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    category: Mapped[AttributeCategory] = relationship("AttributeCategory", back_populates="templates")
    fields: Mapped[list["AttributeTemplateField"]] = relationship(
        "AttributeTemplateField", back_populates="template", cascade="all, delete-orphan",
        order_by="AttributeTemplateField.sort_order",
    )
    revisions: Mapped[list["AttributeTemplateRevision"]] = relationship(
        "AttributeTemplateRevision", back_populates="template", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("category_id", "name", name="uq_attribute_templates_category_name"),)


class AttributeTemplateField(Base):
    __tablename__ = "attribute_template_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("attribute_templates.id", ondelete="CASCADE"), nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), default="select", nullable=False)
    is_composite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    separator: Mapped[str] = mapped_column(String(8), default="/", nullable=False)
    synonyms: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    conversion_rules: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    use_dash_if_empty: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    template: Mapped[AttributeTemplate] = relationship("AttributeTemplate", back_populates="fields")
    allowed_values: Mapped[list["AttributeAllowedValue"]] = relationship(
        "AttributeAllowedValue", back_populates="field", cascade="all, delete-orphan",
        order_by="AttributeAllowedValue.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("template_id", "group_name", "name", name="uq_attribute_template_fields_name"),
        Index("ix_attribute_template_fields_template_sort", "template_id", "sort_order"),
    )


class AttributeAllowedValue(Base):
    __tablename__ = "attribute_allowed_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("attribute_template_fields.id", ondelete="CASCADE"), nullable=False)
    value: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_combination: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="template_import", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    field: Mapped[AttributeTemplateField] = relationship("AttributeTemplateField", back_populates="allowed_values")
    synonyms: Mapped[list["AttributeValueSynonym"]] = relationship(
        "AttributeValueSynonym", back_populates="allowed_value", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("field_id", "normalized_value", name="uq_attribute_allowed_values_normalized"),
        Index("ix_attribute_allowed_values_field_active", "field_id", "is_active"),
    )


class AttributeValueSynonym(Base):
    __tablename__ = "attribute_value_synonyms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    allowed_value_id: Mapped[int] = mapped_column(ForeignKey("attribute_allowed_values.id", ondelete="CASCADE"), nullable=False)
    synonym: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_synonym: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    allowed_value: Mapped[AttributeAllowedValue] = relationship("AttributeAllowedValue", back_populates="synonyms")

    __table_args__ = (UniqueConstraint("allowed_value_id", "normalized_synonym", name="uq_attribute_value_synonyms_normalized"),)


class AttributeTemplateRevision(Base):
    __tablename__ = "attribute_template_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("attribute_templates.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    action: Mapped[str] = mapped_column(String(64), default="import", nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    report: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    template: Mapped[AttributeTemplate] = relationship("AttributeTemplate", back_populates="revisions")


class AttributeBatch(Base):
    __tablename__ = "attribute_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("attribute_templates.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    input_mode: Mapped[str] = mapped_column(String(16), default="csv", nullable=False)
    processing_mode: Mapped[str] = mapped_column(String(32), default="suggest", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="review", nullable=False)
    source_filename: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    original_path: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    export_path: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    export_filename: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    report_filename: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    products_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attributes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    template: Mapped[AttributeTemplate] = relationship("AttributeTemplate")
    products: Mapped[list["AttributeProduct"]] = relationship(
        "AttributeProduct", back_populates="batch", cascade="all, delete-orphan"
    )


class AttributeProduct(Base):
    __tablename__ = "attribute_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("attribute_batches.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("attribute_templates.id", ondelete="RESTRICT"), nullable=True)
    external_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    brand: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    category_name: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    source_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    donor_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    selected_donor_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    donor_url_overrides: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    processing_state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="needs_review", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    batch: Mapped[AttributeBatch] = relationship("AttributeBatch", back_populates="products")
    template: Mapped[AttributeTemplate | None] = relationship("AttributeTemplate")
    values: Mapped[list["AttributeProductValue"]] = relationship(
        "AttributeProductValue", back_populates="product", cascade="all, delete-orphan",
        order_by="AttributeProductValue.sort_order",
    )
    sources: Mapped[list["AttributeProductSource"]] = relationship(
        "AttributeProductSource", back_populates="product", cascade="all, delete-orphan",
        order_by="AttributeProductSource.priority",
    )

    __table_args__ = (Index("ix_attribute_products_batch_model", "batch_id", "model"),)


class AttributeProductValue(Base):
    __tablename__ = "attribute_product_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("attribute_products.id", ondelete="CASCADE"), nullable=False)
    template_field_id: Mapped[int | None] = mapped_column(ForeignKey("attribute_template_fields.id", ondelete="SET NULL"), nullable=True)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    attribute_name: Mapped[str] = mapped_column(String(500), nullable=False)
    current_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    proposed_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    final_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="missing", nullable=False)
    is_in_template: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_extra_attribute: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    dash_reason: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source_details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    product: Mapped[AttributeProduct] = relationship("AttributeProduct", back_populates="values")
    template_field: Mapped[AttributeTemplateField | None] = relationship("AttributeTemplateField")


class AttributeProductSource(Base):
    __tablename__ = "attribute_product_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("attribute_products.id", ondelete="CASCADE"), nullable=False)
    donor_id: Mapped[int | None] = mapped_column(ForeignKey("donors.id", ondelete="SET NULL"), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="primary", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="resolved", nullable=False)
    raw_html_path: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    parsed_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    product: Mapped[AttributeProduct] = relationship("AttributeProduct", back_populates="sources")
    donor: Mapped[Donor | None] = relationship("Donor")

    __table_args__ = (UniqueConstraint("product_id", "donor_id", "url", name="uq_attribute_product_sources_url"),)


class AttributeProductRevision(Base):
    __tablename__ = "attribute_product_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("attribute_products.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    product: Mapped[AttributeProduct] = relationship("AttributeProduct")

    __table_args__ = (Index("ix_attribute_product_revisions_product", "product_id", "created_at"),)


class AttributeMappingRule(Base):
    __tablename__ = "attribute_mapping_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(ForeignKey("attribute_templates.id", ondelete="CASCADE"), nullable=False)
    template_field_id: Mapped[int] = mapped_column(ForeignKey("attribute_template_fields.id", ondelete="CASCADE"), nullable=False)
    donor_attribute_name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_donor_attribute: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    donor: Mapped[Donor] = relationship("Donor")
    template: Mapped[AttributeTemplate] = relationship("AttributeTemplate")
    template_field: Mapped[AttributeTemplateField] = relationship("AttributeTemplateField")

    __table_args__ = (UniqueConstraint("donor_id", "template_id", "normalized_donor_attribute", name="uq_attribute_mapping_rules_source"),)



class AttributeValueMappingRule(Base):
    __tablename__ = "attribute_value_mapping_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id", ondelete="CASCADE"), nullable=False)
    template_field_id: Mapped[int] = mapped_column(ForeignKey("attribute_template_fields.id", ondelete="CASCADE"), nullable=False)
    allowed_value_id: Mapped[int] = mapped_column(ForeignKey("attribute_allowed_values.id", ondelete="CASCADE"), nullable=False)
    raw_value: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_raw_value: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    donor: Mapped[Donor] = relationship("Donor")
    template_field: Mapped[AttributeTemplateField] = relationship("AttributeTemplateField")
    allowed_value: Mapped[AttributeAllowedValue] = relationship("AttributeAllowedValue")

    __table_args__ = (
        UniqueConstraint(
            "donor_id", "template_field_id", "normalized_raw_value",
            name="uq_attribute_value_mapping_rules_source",
        ),
        Index(
            "ix_attribute_value_mapping_rules_lookup",
            "donor_id", "template_field_id", "normalized_raw_value",
        ),
    )
