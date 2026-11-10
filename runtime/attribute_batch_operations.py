"""Background operations for processing every product in one attribute batch."""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from config import env_int
from services.attribute_settings import (
    BULK_CONFIDENCE,
    DONOR_PRODUCT_CONCURRENCY,
    OPERATION_ERROR_LIMIT,
    StaleProductError,
)
from database import SessionLocal
from models import AttributeBatch, AttributeBatchOperation, AttributeProduct, AttributeTemplate, Donor
from services.attribute_assistant import (
    DonorPageFetcher,
    bulk_action,
    capture_product_snapshot,
    create_batch_from_urls,
    process_product_donors,
    product_template,
    refresh_batch_summary,
    save_product_snapshot,
    snapshot_product as _snapshot_product,
    touch_product,
)
from services.attribute_ai import (
    apply_analysis,
    build_product_analysis_request,
    page_snapshot,
    prepare_product_source,
    record_analysis_metrics,
    validate_analysis,
)
from services.attribute_chatgpt_control import ChatGptRateLimitError, analyze_with_chatgpt


_LOCK = threading.RLock()
_DB_WRITE_LOCK = threading.RLock()
_JOBS: dict[int, dict[str, Any]] = {}
_THREADS: dict[int, threading.Thread] = {}
_LAST_PERSIST: dict[int, float] = {}
_ACTIVE_STATUSES = {"queued", "running", "cancelling"}
CHATGPT_CONCURRENCY = env_int("ATTRIBUTE_CHATGPT_CONCURRENCY", 2, minimum=1, maximum=8)
# Kept as a public patch point for existing integrations/tests even though the
# worker now stores a captured snapshot across its network boundary.
snapshot_product = _snapshot_product


class OperationPaused(RuntimeError):
    """Cooperative pause requested between bounded product operations."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    public = copy.deepcopy(state)
    public.pop("completed_product_ids", None)
    public.pop("failed_product_ids", None)
    public.pop("cancel_requested", None)
    return public


def _persist_operation(state: dict[str, Any], *, payload: dict[str, Any] | None = None, force: bool = False) -> None:
    """Persist a bounded checkpoint without turning every UI update into I/O."""

    # Small unit tests and compatibility callers may exercise worker helpers
    # with an intentionally minimal in-memory state.
    if not state.get("id") or not state.get("batch_id"):
        return
    batch_id = int(state["batch_id"])
    now = time.monotonic()
    if not force and now - _LAST_PERSIST.get(batch_id, 0.0) < 1.0:
        return
    _LAST_PERSIST[batch_id] = now
    db = SessionLocal()
    try:
        row = db.get(AttributeBatchOperation, state["id"])
        if row is None:
            row = AttributeBatchOperation(
                id=state["id"],
                batch_id=batch_id,
                kind=state["kind"],
                payload=copy.deepcopy(payload or {}),
            )
            db.add(row)
        elif payload is not None:
            row.payload = copy.deepcopy(payload)
        row.kind = state["kind"]
        row.status = state["status"]
        row.stage = state.get("stage", "")
        row.state = copy.deepcopy(state)
        row.cancel_requested = bool(state.get("cancel_requested"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _latest_persisted_operation(batch_id: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    db = SessionLocal()
    try:
        row = db.scalar(
            select(AttributeBatchOperation)
            .where(AttributeBatchOperation.batch_id == batch_id)
            .order_by(AttributeBatchOperation.updated_at.desc())
            .limit(1)
        )
        if row is None:
            return None, {}
        state = dict(row.state or {})
        if row.status in _ACTIVE_STATUSES:
            state.update({
                "status": "paused",
                "stage": "paused",
                "cancel_requested": False,
                "error": "Операция была приостановлена перезапуском сервиса и может быть продолжена",
            })
            row.status = "paused"
            row.stage = "paused"
            row.cancel_requested = False
            row.state = state
            db.commit()
        return state, dict(row.payload or {})
    finally:
        db.close()


def _update(batch_id: int, **changes: Any) -> None:
    with _LOCK:
        state = _JOBS.get(batch_id)
        if state is None:
            return
        state.update(changes)
        total = max(0, int(state.get("total") or 0))
        processed = max(0, int(state.get("processed") or 0))
        state["percent"] = round(processed * 100 / total) if total else 0
        snapshot = copy.deepcopy(state)
    _persist_operation(
        snapshot,
        force=bool({"status", "finished_at", "error"} & changes.keys()),
    )


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
        state["errors"] = errors[-OPERATION_ERROR_LIMIT:]
        product_id = product.id if product is not None else None
        if product_id is not None:
            failed_ids = list(state.get("failed_product_ids") or [])
            if product_id not in failed_ids:
                failed_ids.append(product_id)
            state["failed_product_ids"] = failed_ids
        snapshot = copy.deepcopy(state)
    _persist_operation(snapshot, force=True)


def get_attribute_batch_operation(batch_id: int) -> dict[str, Any]:
    with _LOCK:
        state = _JOBS.get(batch_id)
    if state is None:
        state, _payload = _latest_persisted_operation(batch_id)
        if state is not None:
            with _LOCK:
                _JOBS[batch_id] = state
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
    if kind not in {"donors", "chatgpt", "auto"}:
        raise ValueError("Неизвестный тип массовой операции")
    if not product_ids:
        raise ValueError("В обработке нет товаров")
    with _LOCK:
        current = _JOBS.get(batch_id)
        if current and current.get("status") in _ACTIVE_STATUSES:
            raise RuntimeError("Для этой обработки уже выполняется массовая операция")
        payload = {
            "product_ids": list(product_ids),
            "donor_ids": list(donor_ids),
            "url_overrides_by_product": copy.deepcopy(url_overrides_by_product or {}),
        }
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
            "completed_product_ids": [],
            "failed_product_ids": [],
            "cancel_requested": False,
            "started_at": "",
            "finished_at": "",
            "error": "",
        }
        _JOBS[batch_id] = state
        _persist_operation(state, payload=payload, force=True)
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


def start_attribute_url_import(
    batch_id: int,
    urls: list[str],
    *,
    template_id: int | None,
    name: str,
    processing_mode: str,
    purpose: str,
    shop_id: int | None,
    auto_run: bool,
) -> dict[str, Any]:
    if not urls:
        raise ValueError("Добавьте хотя бы одну ссылку")
    with _LOCK:
        current = _JOBS.get(batch_id)
        if current and current.get("status") in _ACTIVE_STATUSES:
            raise RuntimeError("Для этой обработки уже выполняется массовая операция")
        payload = {
            "urls": list(urls),
            "template_id": template_id,
            "name": name,
            "processing_mode": processing_mode,
            "purpose": purpose,
            "shop_id": shop_id,
            "auto_run": auto_run,
        }
        state = {
            "id": uuid.uuid4().hex,
            "batch_id": batch_id,
            "kind": "url_import",
            "status": "queued",
            "stage": "queued",
            "total": len(urls),
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
            "completed_product_ids": [],
            "failed_product_ids": [],
            "cancel_requested": False,
            "started_at": "",
            "finished_at": "",
            "error": "",
        }
        _JOBS[batch_id] = state
        _persist_operation(state, payload=payload, force=True)
        thread = threading.Thread(
            target=_run_url_import,
            args=(batch_id, copy.deepcopy(payload)),
            name=f"attribute-url-import-{batch_id}",
            daemon=True,
        )
        _THREADS[batch_id] = thread
        thread.start()
        return _public_state(state)


def pause_attribute_batch_operation(batch_id: int) -> dict[str, Any]:
    with _LOCK:
        state = _JOBS.get(batch_id)
        if state is None or state.get("status") not in _ACTIVE_STATUSES:
            raise ValueError("Активная массовая операция не найдена")
        state["cancel_requested"] = True
        state["status"] = "cancelling"
        state["stage"] = "cancelling"
        snapshot = copy.deepcopy(state)
    _persist_operation(snapshot, force=True)
    return _public_state(snapshot)


def _raise_if_paused(batch_id: int) -> None:
    with _LOCK:
        state = _JOBS.get(batch_id)
        if state and state.get("cancel_requested"):
            raise OperationPaused("Операция приостановлена пользователем")


def resume_attribute_batch_operation(batch_id: int, *, failed_only: bool = False) -> dict[str, Any]:
    with _LOCK:
        current = _JOBS.get(batch_id)
        if current and current.get("status") in _ACTIVE_STATUSES:
            raise RuntimeError("Для этой обработки уже выполняется массовая операция")
    state, payload = _latest_persisted_operation(batch_id)
    if state is None or not payload:
        raise ValueError("Сохранённая массовая операция не найдена")
    if state.get("kind") == "url_import":
        if failed_only:
            raise ValueError("Для импорта ссылок используйте продолжение всей операции")
        return start_attribute_url_import(
            batch_id,
            [str(item) for item in payload.get("urls") or []],
            template_id=int(payload["template_id"]) if payload.get("template_id") else None,
            name=str(payload.get("name") or ""),
            processing_mode=str(payload.get("processing_mode") or "suggest"),
            purpose=str(payload.get("purpose") or "enrich"),
            shop_id=int(payload["shop_id"]) if payload.get("shop_id") else None,
            auto_run=bool(payload.get("auto_run")),
        )
    original_ids = [int(item) for item in payload.get("product_ids") or []]
    if failed_only:
        wanted = {int(item) for item in state.get("failed_product_ids") or []}
        product_ids = [item for item in original_ids if item in wanted]
    elif state.get("kind") == "auto":
        product_ids = original_ids
    else:
        completed = {int(item) for item in state.get("completed_product_ids") or []}
        product_ids = [item for item in original_ids if item not in completed]
    if not product_ids:
        raise ValueError("Нет товаров для повторной обработки")
    overrides = dict(payload.get("url_overrides_by_product") or {})
    return start_attribute_batch_operation(
        batch_id,
        str(state.get("kind") or "donors"),
        product_ids,
        [int(item) for item in payload.get("donor_ids") or []],
        url_overrides_by_product={str(item): dict(overrides.get(str(item)) or {}) for item in product_ids},
    )


def _run_url_import(batch_id: int, payload: dict[str, Any]) -> None:
    _update(batch_id, status="running", stage="url_import", started_at=_now())
    try:
        db = SessionLocal()
        try:
            batch = db.get(AttributeBatch, batch_id)
            if batch is None:
                raise ValueError("Обработка ссылок не найдена")
            template = db.get(AttributeTemplate, int(payload["template_id"])) if payload.get("template_id") else None

            def progress(processed: int, total: int, url: str) -> None:
                _raise_if_paused(batch_id)
                _update(
                    batch_id,
                    processed=processed,
                    succeeded=processed,
                    total=total,
                    current_product=url,
                )

            create_batch_from_urls(
                db,
                [str(item) for item in payload.get("urls") or []],
                template=template,
                name=str(payload.get("name") or ""),
                processing_mode=str(payload.get("processing_mode") or "suggest"),
                purpose=str(payload.get("purpose") or "enrich"),
                shop_id=int(payload["shop_id"]) if payload.get("shop_id") else None,
                existing_batch=batch,
                progress_callback=progress,
            )
            source_urls = list(batch.source_urls or [])
            failures = sum(item.get("status") == "error" for item in source_urls)
            _update(
                batch_id,
                processed=len(source_urls),
                succeeded=len(source_urls) - failures,
                failed=failures,
                total=len(source_urls),
            )
            db.commit()
            product_ids = list(db.scalars(
                select(AttributeProduct.id)
                .where(AttributeProduct.batch_id == batch_id)
                .order_by(AttributeProduct.sort_order, AttributeProduct.id)
            ))
        except OperationPaused:
            db.rollback()
            paused_batch = db.get(AttributeBatch, batch_id)
            if paused_batch is not None:
                paused_batch.status = "paused"
                db.commit()
            raise
        except Exception:
            db.rollback()
            failed_batch = db.get(AttributeBatch, batch_id)
            if failed_batch is not None:
                failed_batch.status = "failed"
                db.commit()
            raise
        finally:
            db.close()

        if payload.get("auto_run") and product_ids:
            with _LOCK:
                state = _JOBS[batch_id]
                state.update({
                    "kind": "auto",
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
                    "current_product": "",
                    "errors": [],
                    "cancel_requested": False,
                })
                snapshot = copy.deepcopy(state)
            operation_payload = {
                "product_ids": product_ids,
                "donor_ids": [],
                "url_overrides_by_product": {},
            }
            _persist_operation(snapshot, payload=operation_payload, force=True)
            _run_operation(batch_id, "auto", product_ids, [], {})
            return
        _update(
            batch_id,
            status="completed",
            stage="completed",
            current_product="",
            finished_at=_now(),
        )
    except OperationPaused as error:
        _update(
            batch_id,
            status="paused",
            stage="paused",
            cancel_requested=False,
            current_product="",
            error=str(error),
            finished_at=_now(),
        )
    except Exception as error:
        _update(
            batch_id,
            status="failed",
            stage="failed",
            current_product="",
            error=str(error),
            finished_at=_now(),
        )
    finally:
        with _LOCK:
            if _THREADS.get(batch_id) is threading.current_thread():
                _THREADS.pop(batch_id, None)


def _mark_product_result(
    batch_id: int,
    *,
    product_id: int | None = None,
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
        if product_id is not None and state.get("kind") != "auto":
            completed = list(state.get("completed_product_ids") or [])
            if product_id not in completed:
                completed.append(product_id)
            state["completed_product_ids"] = completed
        if product_id is not None and failed:
            failed_ids = list(state.get("failed_product_ids") or [])
            if product_id not in failed_ids:
                failed_ids.append(product_id)
            state["failed_product_ids"] = failed_ids
        total = max(1, int(state["total"]))
        state["percent"] = round(int(state["processed"]) * 100 / total)
        snapshot = copy.deepcopy(state)
    _persist_operation(snapshot, force=True)


def _run_donor_products(
    batch_id: int,
    product_ids: list[int],
    donor_ids: list[int],
    url_overrides_by_product: dict[str, dict[str, str]],
    fetcher: DonorPageFetcher,
) -> None:
    _update(batch_id, stage="donors")
    workers = max(
        1,
        min(
            DONOR_PRODUCT_CONCURRENCY,
            int(getattr(fetcher, "max_pages", DONOR_PRODUCT_CONCURRENCY)),
            len(product_ids),
        ),
    )

    def process_one(product_id: int) -> None:
        db = SessionLocal()
        product: AttributeProduct | None = None
        product_failed = False
        paused = False
        attributes_found = 0
        try:
            _raise_if_paused(batch_id)
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
            report = process_product_donors(
                db,
                product,
                donor_ids,
                url_overrides=overrides,
                fetcher=fetcher,
                refresh_summary=False,
                write_lock=_DB_WRITE_LOCK,
                commit_result=True,
                require_opened=True,
                release_transaction=True,
            )
            reports = list(report.get("reports") or [])
            attributes_found = sum(int(item.get("attributes_found") or 0) for item in reports)
        except OperationPaused:
            paused = True
            db.rollback()
            raise
        except Exception as error:
            product_failed = True
            db.rollback()
            _append_error(batch_id, product, error)
        finally:
            db.close()
            if not paused:
                _mark_product_result(
                    batch_id,
                    product_id=product_id,
                    failed=product_failed,
                    attributes_found=attributes_found if not product_failed else 0,
                )

    if workers == 1:
        for product_id in product_ids:
            _raise_if_paused(batch_id)
            process_one(product_id)
        return

    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="attribute-donor",
    ) as pool:
        product_iterator = iter(product_ids)
        pending: set[Future] = set()
        for _ in range(workers):
            _raise_if_paused(batch_id)
            try:
                product_id = next(product_iterator)
            except StopIteration:
                break
            pending.add(pool.submit(process_one, product_id))
        while pending:
            _raise_if_paused(batch_id)
            completed, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                # process_one records expected per-product failures itself.
                # result() still surfaces coordinator/programming failures.
                future.result()
                try:
                    _raise_if_paused(batch_id)
                    product_id = next(product_iterator)
                except StopIteration:
                    continue
                pending.add(pool.submit(process_one, product_id))


def _prepare_chatgpt_product(
    batch_id: int,
    product_id: int,
    donor_ids: list[int],
    url_overrides_by_product: dict[str, dict[str, str]],
    fetcher: DonorPageFetcher,
) -> dict[str, Any] | None:
    """Prepare on the coordinator thread; never share a browser or ORM objects with AI workers."""
    _raise_if_paused(batch_id)
    db = SessionLocal()
    started = time.perf_counter()
    product: AttributeProduct | None = None
    try:
        product = db.get(AttributeProduct, product_id)
        if product is None or product.batch_id != batch_id:
            raise ValueError("Товар обработки не найден")
        overrides = url_overrides_by_product.get(str(product.id), dict(product.donor_url_overrides or {}))
        initial_snapshot = capture_product_snapshot(product)
        expected_version = product.version
        template = product_template(product)
        template_id = template.id if template else None
        template_version = template.version if template else None
        selected_donor_ids = list(donor_ids or product.selected_donor_ids or [])
        source_url, html, parsed, _resolved_by = prepare_product_source(
            db,
            product,
            donor_ids or None,
            url_overrides=overrides,
            fetcher=fetcher,
            persist=False,
        )
        analysis_request, evidence = build_product_analysis_request(
            product,
            source_url=source_url,
            html=html,
            parsed=parsed,
        )
        request_chars = len(analysis_request["instructions"]) + len(analysis_request["input"])
        db.rollback()
        return {
            "product_id": product_id,
            "product_version": expected_version,
            "template_id": template_id,
            "template_version": template_version,
            "selected_donor_ids": selected_donor_ids,
            "url_overrides": overrides,
            "source_url": source_url,
            "analysis_request": analysis_request,
            "prompt_chars": request_chars,
            "evidence": evidence,
            "source_facts": list(analysis_request.get("_source_facts") or []),
            "page_snapshot": page_snapshot(parsed),
            "identity_source_name": str(product.name or parsed.get("name") or ""),
            "initial_snapshot": initial_snapshot,
            "preparation_seconds": time.perf_counter() - started,
        }
    except Exception as error:
        db.rollback()
        _append_error(batch_id, product, error)
        _mark_product_result(batch_id, product_id=product_id, failed=True)
        return None
    finally:
        db.close()


def _analyze_prepared_product(analysis_request: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    response = analyze_with_chatgpt(analysis_request)
    return {**response, "request_seconds": time.perf_counter() - started}


def _apply_chatgpt_result(
    batch_id: int,
    prepared: dict[str, Any],
    future: Future,
) -> BaseException | None:
    with _DB_WRITE_LOCK:
        return _apply_chatgpt_result_locked(batch_id, prepared, future)


def _apply_chatgpt_result_locked(
    batch_id: int,
    prepared: dict[str, Any],
    future: Future,
) -> BaseException | None:
    """Save each completed response serially, in its own short transaction."""
    db = SessionLocal()
    product: AttributeProduct | None = None
    failed = False
    failure: BaseException | None = None
    changed = 0
    attributes_found = 0
    try:
        product = db.get(AttributeProduct, prepared["product_id"])
        if product is None or product.batch_id != batch_id:
            raise ValueError("Товар обработки не найден")
        template = product_template(product)
        if product.version != prepared["product_version"]:
            raise StaleProductError("Товар изменился во время анализа ChatGPT. Результат не применён")
        if (
            (template.id if template else None) != prepared["template_id"]
            or (template.version if template else None) != prepared["template_version"]
        ):
            raise ValueError("Шаблон товара изменился во время анализа ChatGPT. Повторите анализ")
        response = future.result()  # Already completed: no network wait inside the transaction.
        validation_started = time.perf_counter()
        analysis = validate_analysis(
            product,
            response.get("text", ""),
            page_evidence=prepared["evidence"],
            source_facts=prepared["source_facts"],
            identity_source_name=prepared.get("identity_source_name", ""),
        )
        analysis["page_snapshot"] = dict(prepared.get("page_snapshot") or {})
        record_analysis_metrics(
            analysis, prepared["prompt_chars"], response,
            preparation_seconds=prepared.get("preparation_seconds", 0),
            request_seconds=response.get("request_seconds", 0),
            validation_seconds=time.perf_counter() - validation_started,
        )
        save_product_snapshot(
            db,
            product,
            "Перед анализом ChatGPT",
            prepared["initial_snapshot"],
        )
        product.selected_donor_ids = list(prepared["selected_donor_ids"])
        product.donor_url_overrides = dict(prepared["url_overrides"])
        changed = apply_analysis(
            db,
            product,
            analysis,
            source_url=prepared["source_url"],
            refresh_summary=False,
        )
        touch_product(product)
        attributes_found = len(analysis["observed_attributes"])
        db.commit()
    except Exception as error:
        failed = True
        failure = error
        db.rollback()
        _append_error(batch_id, product, error)
    finally:
        db.close()
        _mark_product_result(
            batch_id,
            product_id=int(prepared["product_id"]),
            failed=failed,
            changed=changed if not failed else 0,
            attributes_found=attributes_found if not failed else 0,
        )
    return failure


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
            _raise_if_paused(batch_id)
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
                failure = _apply_chatgpt_result(batch_id, analysis_pending.pop(future), future)
                if isinstance(failure, ChatGptRateLimitError):
                    raise failure

    with ThreadPoolExecutor(max_workers=source_workers, thread_name_prefix="attribute-source") as source_pool, \
            ThreadPoolExecutor(max_workers=CHATGPT_CONCURRENCY, thread_name_prefix="attribute-chatgpt") as ai_pool:
        submit_preparations(source_pool)
        while preparation_pending or prepared_ready or analysis_pending or not products_exhausted:
            collect_completed({
                future for future in (*preparation_pending, *analysis_pending)
                if future.done()
            })
            while prepared_ready and len(analysis_pending) < CHATGPT_CONCURRENCY:
                _raise_if_paused(batch_id)
                prepared = prepared_ready.popleft()
                analysis_request = prepared.pop("analysis_request")
                analysis_pending[ai_pool.submit(_analyze_prepared_product, analysis_request)] = prepared
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
            elif kind == "donors":
                _run_donor_products(
                    batch_id,
                    product_ids,
                    donor_ids,
                    url_overrides_by_product,
                    fetcher,
                )
            else:
                if donor_ids:
                    _run_donor_products(
                        batch_id,
                        product_ids,
                        donor_ids,
                        url_overrides_by_product,
                        fetcher,
                    )
                _raise_if_paused(batch_id)
                unresolved_db = SessionLocal()
                try:
                    unresolved_ids = list(unresolved_db.scalars(
                        select(AttributeProduct.id).where(
                            AttributeProduct.batch_id == batch_id,
                            AttributeProduct.id.in_(product_ids),
                            AttributeProduct.status != "ready",
                        ).order_by(AttributeProduct.sort_order, AttributeProduct.id)
                    ))
                finally:
                    unresolved_db.close()
                with _LOCK:
                    state = _JOBS[batch_id]
                    state["total"] = int(state["processed"]) + len(unresolved_ids)
                    state["percent"] = round(
                        int(state["processed"]) * 100 / max(1, int(state["total"]))
                    )
                    snapshot = copy.deepcopy(state)
                _persist_operation(snapshot, force=True)
                if unresolved_ids:
                    _run_chatgpt_products(
                        batch_id,
                        unresolved_ids,
                        donor_ids,
                        url_overrides_by_product,
                        fetcher,
                    )
                _raise_if_paused(batch_id)
                with _DB_WRITE_LOCK:
                    auto_db = SessionLocal()
                    try:
                        batch = auto_db.get(AttributeBatch, batch_id)
                        if batch is not None:
                            accepted = bulk_action(
                                auto_db,
                                batch,
                                "accept_high",
                                BULK_CONFIDENCE,
                                "",
                            )
                            auto_db.commit()
                            with _LOCK:
                                state = _JOBS[batch_id]
                                state["changed"] += int(accepted)
                                snapshot = copy.deepcopy(state)
                            _persist_operation(snapshot, force=True)
                    except Exception:
                        auto_db.rollback()
                        raise
                    finally:
                        auto_db.close()
        with _DB_WRITE_LOCK:
            summary_db = SessionLocal()
            try:
                batch = summary_db.get(AttributeBatch, batch_id)
                if batch is not None:
                    refresh_batch_summary(batch)
                    summary_db.commit()
            except Exception:
                summary_db.rollback()
                raise
            finally:
                summary_db.close()
        _update(
            batch_id,
            status="completed",
            stage="completed",
            current_product_id=None,
            current_product="",
            finished_at=_now(),
        )
    except OperationPaused as error:
        _update(
            batch_id,
            status="paused",
            stage="paused",
            current_product_id=None,
            current_product="",
            cancel_requested=False,
            error=str(error),
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
