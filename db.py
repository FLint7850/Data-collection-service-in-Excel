import json
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from models import Base


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
DEFAULT_BRAND_STATE = {
    "status": "idle",
    "stage": "",
    "percent": 0,
    "currenturl": "",
    "processed": 0,
    "found_products": 0,
    "candidate_products": 0,
    "compared_products": 0,
    "queue_size": 0,
    "active_tasks": 0,
    "active_urls": [],
    "in_memory_products": 0,
    "failed_pages": 0,
    "stall_seconds": 0,
    "last_event": "",
    "last_warning": "",
    "new_count": 0,
    "missing_by_feed": [],
    "skipped": 0,
    "last_scan_at": "",
    "last_csv": "",
    "error": "",
    "started_at": "",
    "finished_at": "",
    "elapsed_seconds": 0,
    "next_run_at": "",
}
DEFAULT_BRAND_STATE_JSON = json.dumps(DEFAULT_BRAND_STATE, ensure_ascii=False, separators=(",", ":"))

engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def configure_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    migrate_app_settings_table()
    Base.metadata.create_all(bind=engine)
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.commit()
        with connection.begin():
            connection.execute(text("PRAGMA journal_mode=WAL"))
            connection.execute(text("PRAGMA busy_timeout=5000"))
            migrate_schema(connection)
            connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
            current_revision = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            if not current_revision:
                connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260608_0001')"))
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.commit()


def table_columns(connection, table_name: str) -> dict[str, str]:
    return {
        str(row[1]): str(row[2] or "").upper()
        for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    }


def safe_json_expr(column_name: str, default_value: str) -> str:
    return (
        f"CASE WHEN json_valid({column_name}) THEN {column_name} "
        f"ELSE json('{default_value}') END"
    )


def datetime_expr(column_name: str) -> str:
    return (
        f"CASE WHEN {column_name} IS NULL OR trim(CAST({column_name} AS TEXT)) = '' "
        f"THEN NULL ELSE datetime({column_name}) END"
    )


def seed_connection_methods(connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS connection_methods ("
            "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            "code VARCHAR(64) NOT NULL UNIQUE, "
            "name VARCHAR(255) NOT NULL, "
            "is_browser_render BOOLEAN NOT NULL DEFAULT 0, "
            "is_debug_visible BOOLEAN NOT NULL DEFAULT 0, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
    )
    columns = table_columns(connection, "connection_methods")
    added_is_browser_render = bool(columns and "is_browser_render" not in columns)
    added_is_debug_visible = bool(columns and "is_debug_visible" not in columns)
    if added_is_browser_render:
        connection.execute(text("ALTER TABLE connection_methods ADD COLUMN is_browser_render BOOLEAN NOT NULL DEFAULT 0"))
    if added_is_debug_visible:
        connection.execute(text("ALTER TABLE connection_methods ADD COLUMN is_debug_visible BOOLEAN NOT NULL DEFAULT 0"))
    methods = [
        ("requests", "Requests", False, False),
        ("botasaurus-request", "Botasaurus Request", False, False),
        ("botasaurus-browser", "Botasaurus / Chrome Headless Shell", True, False),
        ("botasaurus-browser-direct", "Botasaurus Direct / Chrome Headless Shell", True, False),
        ("botasaurus-visible", "Botasaurus Legacy / Chrome Headless Shell", True, False),
        ("crawl4ai", "Crawl4AI / Chromium", True, False),
        ("firecrawl", "Firecrawl", False, False),
        ("scrapy", "Scrapy", False, False),
        ("crawlee", "Crawlee", False, False),
        ("playwright", "Playwright / Chrome Headless Shell", True, False),
        ("scrapegraphai", "ScrapeGraphAI / Chromium", True, False),
        ("botasaurus-debug-visible", "Debug Visible / Google Chrome for Testing", True, True),
    ]
    for code, name, is_browser_render, is_debug_visible in methods:
        connection.execute(
            text(
                "INSERT INTO connection_methods "
                "(code, name, is_browser_render, is_debug_visible, created_at) "
                "VALUES (:code, :name, :is_browser_render, :is_debug_visible, CURRENT_TIMESTAMP) "
                "ON CONFLICT(code) DO UPDATE SET "
                "name = excluded.name, "
                "is_browser_render = excluded.is_browser_render, "
                "is_debug_visible = excluded.is_debug_visible"
            ),
            {
                "code": code,
                "name": name,
                "is_browser_render": int(is_browser_render),
                "is_debug_visible": int(is_debug_visible),
            },
        )
    if added_is_browser_render:
        browser_codes = [code for code, _name, is_browser_render, _is_debug_visible in methods if is_browser_render]
        for code in browser_codes:
            connection.execute(
                text("UPDATE connection_methods SET is_browser_render = 1 WHERE code = :code"),
                {"code": code},
            )
    if added_is_debug_visible:
        debug_codes = [code for code, _name, _is_browser_render, is_debug_visible in methods if is_debug_visible]
        for code in debug_codes:
            connection.execute(
                text("UPDATE connection_methods SET is_debug_visible = 1 WHERE code = :code"),
                {"code": code},
            )


def migrate_schema(connection) -> None:
    seed_connection_methods(connection)

    own_site_columns = table_columns(connection, "own_sites")
    if own_site_columns and "name" not in own_site_columns:
        connection.execute(text("ALTER TABLE own_sites ADD COLUMN name VARCHAR(255) NOT NULL DEFAULT ''"))

    brand_columns = table_columns(connection, "brands")
    if brand_columns and "state" not in brand_columns:
        connection.exec_driver_sql(f"ALTER TABLE brands ADD COLUMN state JSON NOT NULL DEFAULT '{DEFAULT_BRAND_STATE_JSON}'")

    migrate_app_settings_current_table(connection)
    migrate_news_tables(connection)
    migrate_donor_start_urls(connection)
    migrate_donors_table(connection)
    migrate_projects_table(connection)
    migrate_file_import_table(connection)


def reset_brand_states(connection) -> None:
    columns = table_columns(connection, "brands")
    if not columns or "state" not in columns:
        return
    connection.execute(
        text("UPDATE brands SET state = json(:state)"),
        {"state": DEFAULT_BRAND_STATE_JSON},
    )


def migrate_app_settings_current_table(connection) -> None:
    columns = table_columns(connection, "app_settings")
    if not columns or "exclusions" not in columns or "key" in columns:
        return
    connection.execute(text("DROP TABLE IF EXISTS app_settings_migration_tmp"))
    connection.execute(
        text(
            "CREATE TABLE app_settings_migration_tmp ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "auto_cleanup BOOLEAN NOT NULL, "
            "smtp JSON NOT NULL, "
            "feed_storage JSON NOT NULL"
            ")"
        )
    )
    connection.execute(
        text(
            "INSERT INTO app_settings_migration_tmp (id, auto_cleanup, smtp, feed_storage) "
            "SELECT id, COALESCE(auto_cleanup, 0), "
            f"{safe_json_expr('smtp', '{}')}, "
            f"{safe_json_expr('feed_storage', '[]')} "
            "FROM app_settings"
        )
    )
    connection.execute(text("DROP TABLE app_settings"))
    connection.execute(text("ALTER TABLE app_settings_migration_tmp RENAME TO app_settings"))



def _json_or_default(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _string_array_from_lines(value) -> list[str]:
    parsed = _json_or_default(value, None)
    if isinstance(parsed, list):
        raw_items = []
        for item in parsed:
            raw_items.extend(str(item or "").splitlines())
    elif isinstance(value, str):
        raw_items = value.splitlines()
    else:
        raw_items = []

    result = []
    for item in raw_items:
        text_value = str(item or "").strip()
        if text_value and text_value not in result:
            result.append(text_value)
    return result


def migrate_file_import_table(connection) -> None:
    columns = table_columns(connection, "file_import")
    if not columns:
        return
    if "model_field" not in columns:
        connection.execute(text("ALTER TABLE file_import ADD COLUMN model_field VARCHAR(255) NOT NULL DEFAULT ''"))
        columns = table_columns(connection, "file_import")
    if "replace_rules" not in columns:
        connection.execute(text("ALTER TABLE file_import ADD COLUMN replace_rules TEXT NOT NULL DEFAULT ''"))
        columns = table_columns(connection, "file_import")
    if "export_path" not in columns:
        connection.execute(text("ALTER TABLE file_import ADD COLUMN export_path VARCHAR(500) NOT NULL DEFAULT ''"))
        columns = table_columns(connection, "file_import")

    rows = [dict(row) for row in connection.execute(text("SELECT * FROM file_import")).mappings().all()]
    if columns.get("exclusions") == "JSON":
        for row in rows:
            model_field = str(row.get("model_field") or "").strip()
            replace_rules = str(row.get("replace_rules") or row.get("model_replace_rules") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            export_path = str(row.get("export_path") or "").strip()
            connection.execute(
                text(
                    "UPDATE file_import SET exclusions = json(:exclusions), model_field = :model_field, "
                    "replace_rules = :replace_rules, export_path = :export_path WHERE id = :id"
                ),
                {
                    "id": row.get("id"),
                    "exclusions": json.dumps(_string_array_from_lines(row.get("exclusions")), ensure_ascii=False),
                    "model_field": model_field,
                    "replace_rules": replace_rules,
                    "export_path": export_path,
                },
            )
        return

    connection.execute(text("DROP TABLE IF EXISTS file_import_migration_tmp"))
    connection.execute(
        text(
            "CREATE TABLE file_import_migration_tmp ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "exclusions JSON NOT NULL DEFAULT '[]', "
            "model_field VARCHAR(255) NOT NULL DEFAULT '', "
            "replace_rules TEXT NOT NULL DEFAULT '', "
            "export_path VARCHAR(500) NOT NULL DEFAULT '', "
            "file JSON NOT NULL DEFAULT '{}', "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
    )
    for row in rows:
        connection.execute(
            text(
                "INSERT INTO file_import_migration_tmp "
                "(id, exclusions, model_field, replace_rules, export_path, file, created_at, updated_at) "
                "VALUES (:id, json(:exclusions), :model_field, :replace_rules, :export_path, json(:file), :created_at, :updated_at)"
            ),
            {
                "id": row.get("id"),
                "exclusions": json.dumps(_string_array_from_lines(row.get("exclusions")), ensure_ascii=False),
                "model_field": str(row.get("model_field") or "").strip(),
                "replace_rules": str(row.get("replace_rules") or row.get("model_replace_rules") or "").replace("\r\n", "\n").replace("\r", "\n").strip(),
                "export_path": str(row.get("export_path") or "").strip(),
                "file": json.dumps(_json_or_default(row.get("file"), {}), ensure_ascii=False),
                "created_at": row.get("created_at") or "CURRENT_TIMESTAMP",
                "updated_at": row.get("updated_at") or "CURRENT_TIMESTAMP",
            },
        )
    connection.execute(text("DROP TABLE file_import"))
    connection.execute(text("ALTER TABLE file_import_migration_tmp RENAME TO file_import"))


def _bool_value(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _datetime_value(value):
    return value if value not in (None, "") else None


def migrate_news_tables(connection) -> None:
    brand_columns = table_columns(connection, "brands")
    donor_columns = table_columns(connection, "donors")
    if not brand_columns and not donor_columns:
        return

    # Additive migration only: never drop/recreate brands or donors in production data.
    if brand_columns:
        brand_additions = {
            "group_name": "VARCHAR(255) NOT NULL DEFAULT ''",
            "enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "schedule_type": "VARCHAR(32) NOT NULL DEFAULT 'daily'",
            "scan_time": "VARCHAR(8) NOT NULL DEFAULT '01:00'",
            "weekday": "INTEGER NOT NULL DEFAULT 0",
            "next_run_at": "DATETIME",
            "primary_donor_id": "INTEGER",
            "created_at": "DATETIME",
            "updated_at": "DATETIME",
        }
        for column_name, definition in brand_additions.items():
            if column_name not in brand_columns:
                connection.execute(text(f"ALTER TABLE brands ADD COLUMN {column_name} {definition}"))
                brand_columns[column_name] = definition
        if "state" not in brand_columns:
            connection.exec_driver_sql(f"ALTER TABLE brands ADD COLUMN state JSON NOT NULL DEFAULT '{DEFAULT_BRAND_STATE_JSON}'")
            brand_columns["state"] = "JSON"
        if "group_type" in brand_columns:
            connection.execute(
                text(
                    "UPDATE brands SET group_name = group_type "
                    "WHERE (group_name IS NULL OR trim(group_name) = '') "
                    "AND group_type IS NOT NULL AND trim(group_type) != ''"
                )
            )
        connection.execute(text("UPDATE brands SET group_name = 'Маржа' WHERE group_name IS NULL OR trim(group_name) = ''"))
        connection.execute(text("UPDATE brands SET enabled = 1 WHERE enabled IS NULL"))
        connection.execute(text("UPDATE brands SET schedule_type = 'daily' WHERE schedule_type IS NULL OR trim(schedule_type) = ''"))
        connection.execute(text("UPDATE brands SET scan_time = '01:00' WHERE scan_time IS NULL OR trim(scan_time) = ''"))
        connection.execute(text("UPDATE brands SET weekday = 0 WHERE weekday IS NULL"))
        connection.execute(text("UPDATE brands SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        connection.execute(text("UPDATE brands SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_brands_name ON brands (name)"))

    if donor_columns:
        if "connections_method" in donor_columns and "connection_method" not in donor_columns:
            connection.execute(text("ALTER TABLE donors RENAME COLUMN connections_method TO connection_method"))
            donor_columns = table_columns(connection, "donors")

        donor_additions = {
            "legacy_id": "VARCHAR(32) NOT NULL DEFAULT ''",
            "site_url": "TEXT NOT NULL DEFAULT ''",
            "start_urls": "JSON NOT NULL DEFAULT '[]'",
            "thread_count": "INTEGER NOT NULL DEFAULT 4",
            "auto_connection_fallback": "BOOLEAN NOT NULL DEFAULT 1",
            "exclusions": "JSON NOT NULL DEFAULT '[]'",
            "product_url_filters": "JSON NOT NULL DEFAULT '[]'",
            "product_url_exclusions": "JSON NOT NULL DEFAULT '[]'",
            "extraction_rules": "JSON NOT NULL DEFAULT '{}'",
            "selector_settings": "JSON NOT NULL DEFAULT '{}'",
            "seen_models": "JSON NOT NULL DEFAULT '[]'",
            "known_new_products": "JSON NOT NULL DEFAULT '{}'",
            "created_at": "DATETIME",
            "updated_at": "DATETIME",
        }
        for column_name, definition in donor_additions.items():
            if column_name not in donor_columns:
                connection.execute(text(f"ALTER TABLE donors ADD COLUMN {column_name} {definition}"))
                donor_columns[column_name] = definition

        if "connection_id" not in donor_columns:
            if "connection_method_id" in donor_columns:
                connection.execute(text("ALTER TABLE donors RENAME COLUMN connection_method_id TO connection_id"))
            else:
                connection.execute(text("ALTER TABLE donors ADD COLUMN connection_id INTEGER"))
            donor_columns = table_columns(connection, "donors")

        connection.execute(text("UPDATE donors SET thread_count = 4 WHERE thread_count IS NULL OR thread_count < 1"))
        connection.execute(text("UPDATE donors SET auto_connection_fallback = 1 WHERE auto_connection_fallback IS NULL"))
        connection.execute(text("UPDATE donors SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        connection.execute(text("UPDATE donors SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        connection.execute(
            text(
                "UPDATE donors SET start_urls = json_array(site_url) "
                "WHERE (start_urls IS NULL OR start_urls = '' OR start_urls = '[]') "
                "AND site_url IS NOT NULL AND trim(site_url) != ''"
            )
        )
        connection.execute(
            text(
                "UPDATE donors SET site_url = json_extract(start_urls, '$[0]') "
                "WHERE (site_url IS NULL OR trim(site_url) = '') "
                "AND json_valid(start_urls) AND json_array_length(start_urls) > 0"
            )
        )
        if "connection_method" in donor_columns:
            connection.execute(
                text(
                    "UPDATE donors SET connection_id = "
                    "(SELECT id FROM connection_methods WHERE code = COALESCE(NULLIF(donors.connection_method, ''), 'requests') LIMIT 1) "
                    "WHERE connection_id IS NULL"
                )
            )
        connection.execute(
            text(
                "UPDATE donors SET connection_id = "
                "(SELECT id FROM connection_methods WHERE code = 'requests' LIMIT 1) "
                "WHERE connection_id IS NULL"
            )
        )
        if brand_columns and "state" in donor_columns:
            connection.execute(
                text(
                    "UPDATE brands SET state = ("
                    "SELECT donors.state FROM donors "
                    "WHERE donors.brand_id = brands.id AND donors.state IS NOT NULL "
                    "ORDER BY donors.id LIMIT 1"
                    ") WHERE EXISTS ("
                    "SELECT 1 FROM donors WHERE donors.brand_id = brands.id AND donors.state IS NOT NULL"
                    ")"
                )
            )
        if brand_columns and "primary_donor_id" in brand_columns:
            connection.execute(
                text(
                    "UPDATE brands SET primary_donor_id = ("
                    "SELECT donors.id FROM donors WHERE donors.brand_id = brands.id ORDER BY donors.id LIMIT 1"
                    ") WHERE primary_donor_id IS NULL "
                    "AND EXISTS (SELECT 1 FROM donors WHERE donors.brand_id = brands.id)"
                )
            )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_donors_brand_id ON donors (brand_id)"))
    return

    brand_needs_rebuild = bool(
        brand_columns
        and (
            "primary_donor_id" not in brand_columns
            or "enabled" not in brand_columns
            or "schedule_type" not in brand_columns
            or "scan_time" not in brand_columns
            or "weekday" not in brand_columns
            or "next_run_at" not in brand_columns
            or "exclusions" in brand_columns
            or "collapsed" in brand_columns
            or "group_type" in brand_columns
        )
    )
    donor_needs_rebuild = bool(
        donor_columns
        and (
            "connection_id" not in donor_columns
            or "enabled" in donor_columns
            or "schedule_type" in donor_columns
            or "scan_time" in donor_columns
            or "weekday" in donor_columns
            or "next_run_at" in donor_columns
            or "state" in donor_columns
            or "connection_method" in donor_columns
            or "connection_method_id" in donor_columns
        )
    )
    if not brand_needs_rebuild and not donor_needs_rebuild:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_brands_name ON brands (name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_donors_brand_id ON donors (brand_id)"))
        return

    brand_rows = []
    donor_rows = []
    if brand_columns:
        brand_rows = [dict(row) for row in connection.execute(text("SELECT * FROM brands")).mappings().all()]
    if donor_columns:
        donor_rows = [dict(row) for row in connection.execute(text("SELECT * FROM donors")).mappings().all()]

    connection.execute(text("DROP TABLE IF EXISTS donors_migration_tmp"))
    connection.execute(text("DROP TABLE IF EXISTS brands_migration_tmp"))
    connection.execute(text("DROP TABLE IF EXISTS donors"))
    connection.execute(text("DROP TABLE IF EXISTS brands"))

    connection.exec_driver_sql(
        "CREATE TABLE brands ("
        "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
        "name VARCHAR(255) NOT NULL, "
        "group_name VARCHAR(255) NOT NULL DEFAULT '', "
        f"state JSON NOT NULL DEFAULT '{DEFAULT_BRAND_STATE_JSON}', "
        "enabled BOOLEAN NOT NULL DEFAULT 1, "
        "schedule_type VARCHAR(32) NOT NULL DEFAULT 'daily', "
        "scan_time VARCHAR(8) NOT NULL DEFAULT '01:00', "
        "weekday INTEGER NOT NULL DEFAULT 0, "
        "next_run_at DATETIME, "
        "primary_donor_id INTEGER, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "CONSTRAINT uq_brands_name_group_name UNIQUE (name, group_name), "
        "FOREIGN KEY(primary_donor_id) REFERENCES donors(id) ON DELETE SET NULL"
        ")"
    )
    connection.execute(
        text(
            "CREATE TABLE donors ("
            "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            "legacy_id VARCHAR(32) NOT NULL DEFAULT '', "
            "brand_id INTEGER NOT NULL, "
            "site_url TEXT NOT NULL DEFAULT '', "
            "start_urls JSON NOT NULL DEFAULT '[]', "
            "thread_count INTEGER NOT NULL DEFAULT 4, "
            "connection_id INTEGER, "
            "auto_connection_fallback BOOLEAN NOT NULL DEFAULT 1, "
            "exclusions JSON NOT NULL DEFAULT '[]', "
            "product_url_filters JSON NOT NULL DEFAULT '[]', "
            "product_url_exclusions JSON NOT NULL DEFAULT '[]', "
            "extraction_rules JSON NOT NULL DEFAULT '{}', "
            "selector_settings JSON NOT NULL DEFAULT '{}', "
            "seen_models JSON NOT NULL DEFAULT '[]', "
            "known_new_products JSON NOT NULL DEFAULT '{}', "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(brand_id) REFERENCES brands(id) ON DELETE CASCADE, "
            "FOREIGN KEY(connection_id) REFERENCES connection_methods(id)"
            ")"
        )
    )
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_brands_name ON brands (name)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_donors_brand_id ON donors (brand_id)"))

    inserted_brand_ids = set()
    for row in brand_rows:
        brand_id = row.get("id")
        if brand_id in inserted_brand_ids:
            continue
        inserted_brand_ids.add(brand_id)
        connection.execute(
            text(
                "INSERT OR IGNORE INTO brands "
                "(id, name, group_name, state, enabled, schedule_type, scan_time, weekday, next_run_at, created_at, updated_at) "
                "VALUES (:id, :name, :group_name, json(:state), :enabled, :schedule_type, :scan_time, :weekday, :next_run_at, :created_at, :updated_at)"
            ),
            {
                "id": brand_id,
                "name": row.get("name") or "Донор",
                "group_name": row.get("group_name") or row.get("group_type") or "Маржа",
                "state": json.dumps(_json_or_default(row.get("state"), DEFAULT_BRAND_STATE), ensure_ascii=False),
                "enabled": _bool_value(row.get("enabled"), True),
                "schedule_type": row.get("schedule_type") or "daily",
                "scan_time": str(row.get("scan_time") or "01:00")[:5],
                "weekday": int(row.get("weekday") or 0),
                "next_run_at": _datetime_value(row.get("next_run_at")),
                "created_at": row.get("created_at") or "CURRENT_TIMESTAMP",
                "updated_at": row.get("updated_at") or "CURRENT_TIMESTAMP",
            },
        )

    default_connection_id = connection.execute(
        text("SELECT id FROM connection_methods WHERE code = 'requests' LIMIT 1")
    ).scalar()
    first_donor_by_brand = {}
    for row in donor_rows:
        brand_id = row.get("brand_id")
        if brand_id not in inserted_brand_ids:
            continue
        donor_id = row.get("id")
        legacy_id = row.get("legacy_id") or (str(donor_id) if isinstance(donor_id, str) and not str(donor_id).isdigit() else "")
        site_url = row.get("site_url") or ""
        start_urls = _json_or_default(row.get("start_urls"), [])
        if not isinstance(start_urls, list):
            start_urls = []
        if not site_url:
            if start_urls:
                site_url = str(start_urls[0] or "")
        if site_url and not start_urls:
            start_urls = [site_url]
        connection_id = row.get("connection_id") or row.get("connection_method_id")
        if not connection_id:
            method = row.get("connection_method") or "requests"
            connection_id = connection.execute(
                text("SELECT id FROM connection_methods WHERE code = :code LIMIT 1"),
                {"code": method},
            ).scalar() or default_connection_id
        donor_state = _json_or_default(row.get("state"), None)
        if donor_state and brand_id:
            connection.execute(
                text("UPDATE brands SET state = json(:state) WHERE id = :brand_id"),
                {"state": json.dumps(donor_state, ensure_ascii=False), "brand_id": brand_id},
            )
        connection.execute(
            text(
                "INSERT INTO donors "
                "(id, legacy_id, brand_id, site_url, start_urls, thread_count, connection_id, auto_connection_fallback, exclusions, "
                "product_url_filters, product_url_exclusions, extraction_rules, selector_settings, seen_models, known_new_products, created_at, updated_at) "
                "VALUES (:id, :legacy_id, :brand_id, :site_url, json(:start_urls), :thread_count, :connection_id, :auto_connection_fallback, json(:exclusions), "
                "json(:product_url_filters), json(:product_url_exclusions), json(:extraction_rules), json(:selector_settings), json(:seen_models), json(:known_new_products), :created_at, :updated_at)"
            ),
            {
                "id": donor_id if isinstance(donor_id, int) or str(donor_id).isdigit() else None,
                "legacy_id": legacy_id,
                "brand_id": brand_id,
                "site_url": site_url,
                "start_urls": json.dumps(start_urls, ensure_ascii=False),
                "thread_count": int(row.get("thread_count") or 4),
                "connection_id": connection_id,
                "auto_connection_fallback": _bool_value(row.get("auto_connection_fallback"), True),
                "exclusions": json.dumps(_json_or_default(row.get("exclusions"), []), ensure_ascii=False),
                "product_url_filters": json.dumps(_json_or_default(row.get("product_url_filters"), []), ensure_ascii=False),
                "product_url_exclusions": json.dumps(_json_or_default(row.get("product_url_exclusions"), []), ensure_ascii=False),
                "extraction_rules": json.dumps(_json_or_default(row.get("extraction_rules"), {}), ensure_ascii=False),
                "selector_settings": json.dumps(_json_or_default(row.get("selector_settings"), {}), ensure_ascii=False),
                "seen_models": json.dumps(_json_or_default(row.get("seen_models"), []), ensure_ascii=False),
                "known_new_products": json.dumps(_json_or_default(row.get("known_new_products"), {}), ensure_ascii=False),
                "created_at": row.get("created_at") or "CURRENT_TIMESTAMP",
                "updated_at": row.get("updated_at") or "CURRENT_TIMESTAMP",
            },
        )
        if brand_id not in first_donor_by_brand:
            first_donor_by_brand[brand_id] = donor_id if isinstance(donor_id, int) or str(donor_id).isdigit() else connection.execute(text("SELECT last_insert_rowid()")).scalar()

    for row in brand_rows:
        brand_id = row.get("id")
        primary_id = row.get("primary_donor_id") or first_donor_by_brand.get(brand_id)
        if primary_id:
            connection.execute(
                text(
                    "UPDATE brands SET primary_donor_id = :primary_id "
                    "WHERE id = :brand_id AND EXISTS (SELECT 1 FROM donors WHERE id = :primary_id AND brand_id = :brand_id)"
                ),
                {"primary_id": primary_id, "brand_id": brand_id},
            )

def migrate_projects_table(connection) -> None:
    columns = table_columns(connection, "projects")
    if not columns:
        return
    if "exclusions" not in columns:
        connection.execute(text("ALTER TABLE projects ADD COLUMN exclusions JSON NOT NULL DEFAULT '[]'"))
        columns = table_columns(connection, "projects")
    if "product_url_exclusions" not in columns:
        connection.execute(text("ALTER TABLE projects ADD COLUMN product_url_exclusions JSON NOT NULL DEFAULT '[]'"))
        columns = table_columns(connection, "projects")
    if "legacy_id" not in columns:
        connection.execute(text("ALTER TABLE projects ADD COLUMN legacy_id VARCHAR(32) NOT NULL DEFAULT ''"))
        columns = table_columns(connection, "projects")
    if "persist_profile" not in columns:
        connection.execute(text("ALTER TABLE projects ADD COLUMN persist_profile BOOLEAN NOT NULL DEFAULT 0"))


def migrate_donor_start_urls(connection) -> None:
    columns = table_columns(connection, "donors")
    if not columns:
        return
    if "start_urls" not in columns:
        connection.execute(text("ALTER TABLE donors ADD COLUMN start_urls JSON NOT NULL DEFAULT '[]'"))
    connection.execute(
        text(
            "UPDATE donors SET start_urls = json_array(site_url) "
            "WHERE (start_urls IS NULL OR start_urls = '' OR start_urls = '[]') "
            "AND site_url IS NOT NULL AND trim(site_url) != ''"
        )
    )


def migrate_donors_table(connection) -> None:
    columns = table_columns(connection, "donors")
    if not columns:
        return
    if "connections_method" in columns and "connection_method" not in columns:
        connection.execute(text("ALTER TABLE donors RENAME COLUMN connections_method TO connection_method"))
        columns = table_columns(connection, "donors")

    if "legacy_id" not in columns:
        connection.execute(text("ALTER TABLE donors ADD COLUMN legacy_id VARCHAR(32) NOT NULL DEFAULT ''"))
        columns = table_columns(connection, "donors")

    if "connection_id" not in columns:
        if "connection_method_id" in columns:
            connection.execute(text("ALTER TABLE donors RENAME COLUMN connection_method_id TO connection_id"))
        else:
            connection.execute(text("ALTER TABLE donors ADD COLUMN connection_id INTEGER"))
        columns = table_columns(connection, "donors")

    if "product_url_exclusions" not in columns:
        connection.execute(text("ALTER TABLE donors ADD COLUMN product_url_exclusions JSON NOT NULL DEFAULT '[]'"))
        columns = table_columns(connection, "donors")

    if "connection_method" in columns:
        connection.execute(
            text(
                "UPDATE donors SET connection_id = "
                "(SELECT id FROM connection_methods WHERE code = COALESCE(NULLIF(donors.connection_method, ''), 'requests') LIMIT 1) "
                "WHERE connection_id IS NULL"
            )
        )
    else:
        connection.execute(
            text(
                "UPDATE donors SET connection_id = "
                "(SELECT id FROM connection_methods WHERE code = 'requests' LIMIT 1) "
                "WHERE connection_id IS NULL"
            )
        )
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_donors_brand_id ON donors (brand_id)"))


def migrate_app_settings_table() -> None:
    inspector = inspect(engine)
    if "app_settings" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("app_settings")}
    if "key" not in columns or "value" not in columns:
        return
    with engine.begin() as connection:
        row = connection.execute(text("SELECT value FROM app_settings WHERE key = 'news' LIMIT 1")).fetchone()
        saved = row[0] if row else "{}"
        connection.execute(text("DROP TABLE app_settings"))
        connection.execute(
            text(
                "CREATE TABLE app_settings ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "auto_cleanup BOOLEAN NOT NULL, "
                "smtp JSON NOT NULL, "
                "feed_storage JSON NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO app_settings (id, auto_cleanup, smtp, feed_storage) "
                "VALUES (1, COALESCE(json_extract(:saved, '$.auto_cleanup'), 0), "
                "COALESCE(json_extract(:saved, '$.smtp'), json('{}')), "
                "COALESCE(json_extract(:saved, '$.feed_storage'), json('[]')))"
            ),
            {"saved": saved},
        )


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
