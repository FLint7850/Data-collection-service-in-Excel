"""Background operations for processing every product in one attribute batch."""

from __future__ import annotations

import copy
import threading
import uuid
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from config import env_int
from database import SessionLocal
from models import AttributeProduct, Donor
from services.attribute_assistant import (
    DonorPageFetcher,
    capture_product_snapshot,
    process_product_donors,
    save_product_snapshot,
    snapshot_product,
)
from services.attribute_ai import (
    apply_analysis,
    build_product_prompt,
    parsed_attribute_facts,
    prepare_product_source,
    validate_analysis,
)
from services.attribute_chatgpt_control import analyze_with_chatgpt


_LOCK = threading.RLock()
_JOBS: dict[int, dict[str, Any]] = {}
_THREADS: dict[int, threading.Thread] = {}
_ACTIVE_STATUSES = {"queued", "running"}
CHATGPT_CONCURRENCY = env_int("ATTRIBUTE_CHATGPT_CONCURRENCY", 3, minimum=1, maximum=8)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(state)


def _update(batch_id: int, **changes: Any) -> None:
    with _LOCK:
        state = _JOBS.get(batch_id)
        if state is None:
            return
        state.update(changes)
        total = max(0, int(state.get("total") or 0))
        processed = max(0, int(state.get("processed") or 0))
        state["percent"] = round(processed * 100 / total) if total else 0


def _append_error(batch_id: int, product: AttributeProduct | None, error: object) -> None:
    with _LOCK:
        state = _JOBS.get(batch_id)
        if state is None:
            return
        errors = list(state.get("errors") or [])
        errors.append({
            "product_id": product.id if product is not None else None,
            "product": (product.model or product.name) if product is not None else "",
            "error": str(error),
        })
        state["errors"] = errors[-50:]


def get_attribute_batch_operation(batch_id: int) -> dict[str, Any]:
    with _LOCK:
        state = _JOBS.get(batch_id)
        if state is None:
            return {
                "id": "",
                "batch_id": batch_id,
                "kind": "",
                "status": "idle",
                "stage": "",
                "total": 0,
                "prepared": 0,
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "percent": 0,
                "changed": 0,
                "attributes_found": 0,
                "current_product_id": None,
                "current_product": "",
                "errors": [],
                "started_at": "",
                "finished_at": "",
                "error": "",
            }
        return _public_state(state)


def is_attribute_batch_operation_active(batch_id: int) -> bool:
    return get_attribute_batch_operation(batch_id)["status"] in _ACTIVE_STATUSES


def start_attribute_batch_operation(
    batch_id: int,
    kind: str,
    product_ids: list[int],
    donor_ids: list[int],
    *,
    url_overrides_by_product: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    if kind not in {"donors", "chatgpt"}:
        raise ValueError("Неизвестный тип массовой операции")
    if not product_ids:
        raise ValueError("В обработке нет товаров")
    with _LOCK:
        current = _JOBS.get(batch_id)
        if current and current.get("status") in _ACTIVE_STATUSES:
            raise RuntimeError("Для этой обработки уже выполняется массовая операция")
        state = {
            "id": uuid.uuid4().hex,
            "batch_id": batch_id,
            "kind": kind,
            "status": "queued",
            "stage": "queued",
            "total": len(product_ids),
            "prepared": 0,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "percent": 0,
            "changed": 0,
            "attributes_found": 0,
            "current_product_id": None,
            "current_product": "",
            "errors": [],
            "started_at": "",
            "finished_at": "",
            "error": "",
        }
        _JOBS[batch_id] = state
        thread = threading.Thread(
            target=_run_operation,
            args=(
                batch_id,
                kind,
                list(product_ids),
                list(donor_ids),
                copy.deepcopy(url_overrides_by_product or {}),
            ),
            name=f"attribute-{kind}-{batch_id}",
            daemon=True,
        )
        _THREADS[batch_id] = thread
        thread.start()
        return _public_state(state)


def _mark_product_result(
    batch_id: int,
    *,
    failed: bool,
    changed: int = 0,
    attributes_found: int = 0,
) -> None:
    with _LOCK:
        state = _JOBS[batch_id]
        state["processed"] += 1
        state["failed" if failed else "succeeded"] += 1
        state["changed"] += changed
        state["attributes_found"] += attributes_found
        total = max(1, int(state["total"]))
        state["percent"] = round(int(state["processed"]) * 100 / total)


def _run_donor_products(
    batch_id: int,
    product_ids: list[int],
    donor_ids: list[int],
    url_overrides_by_product: dict[str, dict[str, str]],
    fetcher: DonorPageFetcher,
) -> None:
    _update(batch_id, stage="donors")
    for product_id in product_ids:
        db = SessionLocal()
        product: AttributeProduct | None = None
        product_failed = False
        attributes_found = 0
        try:
            product = db.get(AttributeProduct, product_id)
            if product is None or product.batch_id != batch_id:
                raise ValueError("Товар обработки не найден")
            _update(
                batch_id,
                current_product_id=product.id,
                current_product=product.model or product.name,
            )
            overrides = url_overrides_by_product.get(
                str(product.id),
                dict(product.donor_url_overrides or {}),
            )
            snapshot_product(db, product, "Перед обработкой доноров")
            report = process_product_donors(
                db,
                product,
                donor_ids,
                url_overrides=overrides,
                fetcher=fetcher,
            )
            reports = list(report.get("reports") or [])
            attributes_found = sum(int(item.get("attributes_found") or 0) for item in reports)
            opened = any(item.get("status") in {"parsed", "no_attributes"} for item in reports)
            if not opened:
                messages = [str(item.get("message") or "") for item in reports if item.get("message")]
                raise ValueError("; ".join(messages) or "Ни один донор не был обработан")
            db.commit()
        except Exception as error:
            product_failed = True
            db.rollback()
            _append_error(batch_id, product, error)
        finally:
            db.close()
            _mark_product_result(
                batch_id,
                failed=product_failed,
                attributes_found=attributes_found if not product_failed else 0,
            )


def _prepare_chatgpt_product(
    batch_id: int,
    product_id: int,
    donor_ids: list[int],
    url_overrides_by_product: dict[str, dict[str, str]],
    fetcher: DonorPageFetcher,
) -> dict[str, Any] | None:
    """Prepare on the coordinator thread; never share a browser or ORM objects with AI workers."""
    db = SessionLocal()
    product: AttributeProduct | None = None
    try:
        product = db.get(AttributeProduct, product_id)
        if product is None or product.batch_id != batch_id:
            raise ValueError("Товар обработки не найден")
        overrides = url_overrides_by_product.get(str(product.id), dict(product.donor_url_overrides or {}))
        initial_snapshot = capture_product_snapshot(product)
        source_url, html, parsed, _resolved_by = prepare_product_source(
            db, product, donor_ids or None, url_overrides=overrides, fetcher=fetcher,
        )
        prompt, evidence = build_product_prompt(product, source_url=source_url, html=html, parsed=parsed)
        template_id = product.template_id or product.batch.template_id
        db.commit()
        return {
            "product_id": product_id,
            "template_id": template_id,
            "source_url": source_url,
            "prompt": prompt,
            "evidence": evidence,
            "source_facts": parsed_attribute_facts(parsed),
            "initial_snapshot": initial_snapshot,
        }
    except Exception as error:
        db.rollback()
        _append_error(batch_id, product, error)
        _mark_product_result(batch_id, failed=True)
        return None
    finally:
        db.close()


def _apply_chatgpt_result(batch_id: int, prepared: dict[str, Any], future: Future) -> None:
    """Save each completed response serially, in its own short transaction."""
    db = SessionLocal()
    product: AttributeProduct | None = None
    failed = False
    changed = 0
    attributes_found = 0
    try:
        product = db.get(AttributeProduct, prepared["product_id"])
        if product is None or product.batch_id != batch_id:
            raise ValueError("Товар обработки не найден")
        if (product.template_id or product.batch.template_id) != prepared["template_id"]:
            raise ValueError("Шаблон товара изменился во время анализа ChatGPT. Повторите анализ")
        response = future.result()  # Already completed: no network wait inside the transaction.
        analysis = validate_analysis(
            product,
            response.get("text", ""),
            page_evidence=prepared["evidence"],
            source_facts=prepared["source_facts"],
        )
        save_product_snapshot(
            db,
            product,
            "Перед анализом ChatGPT",
            prepared["initial_snapshot"],
        )
        changed = apply_analysis(db, product, analysis, source_url=prepared["source_url"])
        attributes_found = len(analysis["observed_attributes"])
        db.commit()
    except Exception as error:
        failed = True
        db.rollback()
        _append_error(batch_id, product, error)
    finally:
        db.close()
        _mark_product_result(
            batch_id,
            failed=failed,
            changed=changed if not failed else 0,
            attributes_found=attributes_found if not failed else 0,
        )


def _run_chatgpt_products(
    batch_id: int,
    product_ids: list[int],
    donor_ids: list[int],
    url_overrides_by_product: dict[str, dict[str, str]],
    fetcher: DonorPageFetcher,
) -> None:
    _update(batch_id, stage="chatgpt", current_product_id=None, current_product="")
    source_workers = max(1, min(CHATGPT_CONCURRENCY, int(getattr(fetcher, "max_pages", CHATGPT_CONCURRENCY))))
    preparation_pending: dict[Future, int] = {}
    analysis_pending: dict[Future, dict[str, Any]] = {}
    prepared_ready: deque[dict[str, Any]] = deque()
    product_iterator = iter(product_ids)
    products_exhausted = False
    prepared_count = 0

    def submit_preparations(pool: ThreadPoolExecutor) -> None:
        nonlocal products_exhausted
        while not products_exhausted and len(preparation_pending) < source_workers:
            try:
                product_id = next(product_iterator)
            except StopIteration:
                products_exhausted = True
                break
            future = pool.submit(
                _prepare_chatgpt_product,
                batch_id,
                product_id,
                donor_ids,
                url_overrides_by_product,
                fetcher,
            )
            preparation_pending[future] = product_id

    def collect_completed(done: set[Future]) -> None:
        nonlocal prepared_count
        for future in done:
            if future in preparation_pending:
                preparation_pending.pop(future)
                prepared = future.result()
                if prepared is not None:
                    prepared_ready.append(prepared)
                    prepared_count += 1
                    _update(batch_id, prepared=prepared_count)
            elif future in analysis_pending:
                _apply_chatgpt_result(batch_id, analysis_pending.pop(future), future)

    with ThreadPoolExecutor(max_workers=source_workers, thread_name_prefix="attribute-source") as source_pool, \
            ThreadPoolExecutor(max_workers=CHATGPT_CONCURRENCY, thread_name_prefix="attribute-chatgpt") as ai_pool:
        submit_preparations(source_pool)
        while preparation_pending or prepared_ready or analysis_pending or not products_exhausted:
            collect_completed({
                future for future in (*preparation_pending, *analysis_pending)
                if future.done()
            })
            while prepared_ready and len(analysis_pending) < CHATGPT_CONCURRENCY:
                prepared = prepared_ready.popleft()
                prompt = prepared.pop("prompt")
                analysis_pending[ai_pool.submit(analyze_with_chatgpt, prompt)] = prepared
            submit_preparations(source_pool)
            if not (preparation_pending or prepared_ready or analysis_pending):
                continue
            if any(future.done() for future in (*preparation_pending, *analysis_pending)):
                continue
            wait_for = (
                list(analysis_pending)
                if prepared_ready and len(analysis_pending) >= CHATGPT_CONCURRENCY
                else [*preparation_pending, *analysis_pending]
            )
            done, _ = wait(wait_for, return_when=FIRST_COMPLETED)
            collect_completed(done)


def _run_operation(
    batch_id: int,
    kind: str,
    product_ids: list[int],
    donor_ids: list[int],
    url_overrides_by_product: dict[str, dict[str, str]],
) -> None:
    _update(batch_id, status="running", stage="preparing", started_at=_now())
    try:
        bootstrap = SessionLocal()
        try:
            effective_donor_ids = set(donor_ids)
            if not effective_donor_ids:
                products = bootstrap.scalars(
                    select(AttributeProduct).where(AttributeProduct.id.in_(product_ids))
                )
                for product in products:
                    effective_donor_ids.update(int(item) for item in (product.selected_donor_ids or []))
            donors = list(
                bootstrap.scalars(select(Donor).where(Donor.id.in_(effective_donor_ids)))
            ) if effective_donor_ids else []
            max_pages = max((donor.thread_count for donor in donors), default=1)
        finally:
            bootstrap.close()
        with DonorPageFetcher(max_pages=max_pages) as fetcher:
            if kind == "chatgpt":
                _run_chatgpt_products(
                    batch_id,
                    product_ids,
                    donor_ids,
                    url_overrides_by_product,
                    fetcher,
                )
            else:
                _run_donor_products(
                    batch_id,
                    product_ids,
                    donor_ids,
                    url_overrides_by_product,
                    fetcher,
                )
        _update(
            batch_id,
            status="completed",
            stage="completed",
            current_product_id=None,
            current_product="",
            finished_at=_now(),
        )
    except Exception as error:
        _update(
            batch_id,
            status="failed",
            stage="failed",
            current_product_id=None,
            current_product="",
            error=str(error),
            finished_at=_now(),
        )
    finally:
        with _LOCK:
            _THREADS.pop(batch_id, None)
