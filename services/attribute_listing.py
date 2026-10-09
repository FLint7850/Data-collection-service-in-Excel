"""Bounded attribute product lists and SQL counters; never load value payloads."""

from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from models import AttributeProduct, AttributeProductValue
from query_utils import normalize_search_text


PRODUCT_PAGE_SIZE = 80


def _sum(condition):
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def batch_summary(db: Session, batch_id: int) -> dict[str, int]:
    products = db.execute(select(
        func.count(AttributeProduct.id).label("products"),
        _sum(AttributeProduct.status == "ready").label("ready"),
        _sum(AttributeProduct.status != "ready").label("needs_review"),
    ).where(AttributeProduct.batch_id == batch_id)).mappings().one()
    value = AttributeProductValue
    values = db.execute(select(
        _sum(and_(value.is_in_template.is_(True), value.final_value != "", value.final_value != "-")).label("filled"),
        _sum(and_(value.is_in_template.is_(True), value.final_value == "")).label("missing"),
        _sum(value.status == "conflict").label("conflicts"),
        _sum(value.status == "suggested").label("suggestions"),
    ).join(AttributeProduct, AttributeProduct.id == value.product_id)
      .where(AttributeProduct.batch_id == batch_id)).mappings().one()
    return {key: int(count) for key, count in {**products, **values}.items()}


def product_page(
    db: Session, batch_id: int, *, query: str = "", status: str = "all",
    offset: int = 0, limit: int = PRODUCT_PAGE_SIZE,
) -> dict[str, Any]:
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    value, product = AttributeProductValue, AttributeProduct
    counters = select(
        value.product_id,
        _sum(and_(value.is_in_template.is_(True), value.final_value == "")).label("missing"),
        _sum(value.status == "conflict").label("conflicts"),
        _sum(value.status == "suggested").label("suggestions"),
        _sum(value.is_in_template.is_(False)).label("outside_template"),
    ).join(product, product.id == value.product_id).where(product.batch_id == batch_id)
    counters = counters.group_by(value.product_id).cte("attribute_product_counts")
    statement = select(
        product.id, product.model, product.name, product.brand, product.status,
        *(func.coalesce(counters.c[key], 0).label(key)
          for key in ("missing", "conflicts", "suggestions", "outside_template")),
    ).outerjoin(counters, counters.c.product_id == product.id).where(product.batch_id == batch_id)
    rows = statement.subquery()
    conditions = {
        "ready": rows.c.status == "ready",
        "needs_review": rows.c.status == "needs_review",
        "conflict": or_(rows.c.status == "conflict", rows.c.conflicts > 0),
        "missing": or_(rows.c.status == "missing", rows.c.missing > 0),
        "outside_template": rows.c.outside_template > 0,
    }
    if status != "all" and status not in conditions:
        raise ValueError("Неизвестный фильтр товаров")
    counts = dict(db.execute(select(
        func.count().label("all"),
        *(_sum(condition).label(key) for key, condition in conditions.items()),
    ).select_from(rows)).mappings().one())
    filtered = select(rows)
    if status != "all":
        filtered = filtered.where(conditions[status])
    query = normalize_search_text(query)
    if query:
        # SQLite lower() folds only ASCII. A per-connection Unicode function
        # also works with isolated test sessions and existing databases.
        if db.bind.dialect.name == "sqlite":
            db.connection().connection.driver_connection.create_function(
                "attribute_search_key", 1, normalize_search_text, deterministic=True,
            )
            search_key = func.attribute_search_key
        else:
            search_key = func.lower
        filtered = filtered.where(or_(
            *(search_key(rows.c[key]).contains(query, autoescape=True) for key in ("model", "name", "brand")),
        ))
        matched = int(db.scalar(select(func.count()).select_from(filtered.subquery())) or 0)
    else:
        matched = int(counts[status])
    if offset >= matched:
        offset = ((matched - 1) // limit) * limit if matched else 0
    # IDs preserve CSV order in historical batches whose sort_order was zero.
    # Keep ordering in the same query rather than loading product ORM objects.
    filtered = filtered.join(product, product.id == rows.c.id).order_by(product.sort_order, product.id)
    items = []
    for row in db.execute(filtered.offset(offset).limit(limit)).mappings():
        items.append({
            **{key: row[key] for key in ("id", "model", "name", "brand", "status")},
            "counts": {key: int(row[key]) for key in ("missing", "conflicts", "suggestions", "outside_template")},
        })
    return {
        "items": items, "total": int(counts["all"]), "matched": matched,
        "offset": offset, "limit": limit, "has_more": offset + len(items) < matched,
        "counts": {key: int(count) for key, count in counts.items()},
    }
