from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from models import Base


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

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
    with engine.begin() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
        connection.execute(text("PRAGMA busy_timeout=5000"))
        migrate_schema(connection)
        connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        current_revision = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        if not current_revision:
            connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260608_0001')"))


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
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
    )
    methods = [
        ("requests", "Requests"),
        ("botasaurus-request", "Botasaurus Request"),
        ("botasaurus-browser", "Botasaurus Browser"),
        ("botasaurus-browser-direct", "Botasaurus Browser Direct"),
        ("botasaurus-visible", "Botasaurus Visible Browser"),
        ("crawl4ai", "Crawl4AI"),
        ("firecrawl", "Firecrawl"),
        ("scrapy", "Scrapy"),
        ("crawlee", "Crawlee"),
    ]
    for code, name in methods:
        connection.execute(
            text(
                "INSERT INTO connection_methods (code, name, created_at) VALUES (:code, :name, CURRENT_TIMESTAMP) "
                "ON CONFLICT(code) DO UPDATE SET name = excluded.name"
            ),
            {"code": code, "name": name},
        )


def migrate_schema(connection) -> None:
    seed_connection_methods(connection)

    own_site_columns = table_columns(connection, "own_sites")
    if own_site_columns and "name" not in own_site_columns:
        connection.execute(text("ALTER TABLE own_sites ADD COLUMN name VARCHAR(255) NOT NULL DEFAULT ''"))

    brand_columns = table_columns(connection, "brands")
    if brand_columns and "exclusions" not in brand_columns:
        connection.execute(text("ALTER TABLE brands ADD COLUMN exclusions JSON NOT NULL DEFAULT '[]'"))
    if brand_columns and "state" not in brand_columns:
        connection.execute(text("ALTER TABLE brands ADD COLUMN state JSON NOT NULL DEFAULT '{\"status\":\"idle\"}'"))

    migrate_projects_table(connection)
    migrate_donors_table(connection)


def migrate_projects_table(connection) -> None:
    columns = table_columns(connection, "projects")
    if not columns:
        return
    needs_rebuild = columns.get("id") != "INTEGER" or "legacy_id" not in columns
    if not needs_rebuild:
        return

    connection.execute(text("DROP TABLE IF EXISTS projects_migration_tmp"))
    connection.execute(
        text(
            "CREATE TABLE projects_migration_tmp ("
            "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            "legacy_id VARCHAR(32) NOT NULL UNIQUE DEFAULT '', "
            "name VARCHAR(255) NOT NULL, "
            "start_urls JSON NOT NULL, "
            "thread_count INTEGER NOT NULL, "
            "exclusions JSON NOT NULL, "
            "product_url_filters JSON NOT NULL, "
            "extraction_rules JSON NOT NULL, "
            "state JSON NOT NULL, "
            "auto_cleanup BOOLEAN NOT NULL, "
            "connection_method VARCHAR(64) NOT NULL, "
            "auto_connection_fallback BOOLEAN NOT NULL, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL"
            ")"
        )
    )
    id_expr = "CAST(id AS TEXT)" if columns.get("id") != "INTEGER" else "COALESCE(legacy_id, CAST(id AS TEXT))"
    connection.execute(
        text(
            "INSERT INTO projects_migration_tmp (legacy_id, name, start_urls, thread_count, exclusions, "
            "product_url_filters, extraction_rules, state, auto_cleanup, connection_method, "
            "auto_connection_fallback, created_at, updated_at) "
            f"SELECT {id_expr}, name, {safe_json_expr('start_urls', '[]')}, "
            "CAST(COALESCE(NULLIF(thread_count, ''), 4) AS INTEGER), "
            f"{safe_json_expr('exclusions', '[]')}, "
            f"{safe_json_expr('product_url_filters', '[]')}, "
            f"{safe_json_expr('extraction_rules', '{}')}, "
            f"{safe_json_expr('state', '{}')}, "
            "COALESCE(auto_cleanup, 0), COALESCE(NULLIF(connection_method, ''), 'requests'), "
            "COALESCE(auto_connection_fallback, 1), "
            "COALESCE(created_at, CURRENT_TIMESTAMP), COALESCE(updated_at, CURRENT_TIMESTAMP) "
            "FROM projects ORDER BY created_at, rowid"
        )
    )
    connection.execute(text("DROP TABLE projects"))
    connection.execute(text("ALTER TABLE projects_migration_tmp RENAME TO projects"))


def migrate_donors_table(connection) -> None:
    columns = table_columns(connection, "donors")
    if not columns:
        return
    if "connections_method" in columns and "connection_method" not in columns:
        connection.execute(text("ALTER TABLE donors RENAME COLUMN connections_method TO connection_method"))
        columns = table_columns(connection, "donors")

    needs_rebuild = (
        columns.get("id") != "INTEGER"
        or columns.get("next_run_at") != "DATETIME"
        or "legacy_id" not in columns
        or "connection_method_id" not in columns
        or "state" in columns
    )
    if not needs_rebuild:
        return

    connection.execute(text("DROP TABLE IF EXISTS donors_migration_tmp"))
    connection.execute(
        text(
            "CREATE TABLE donors_migration_tmp ("
            "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            "legacy_id VARCHAR(32) NOT NULL UNIQUE DEFAULT '', "
            "brand_id INTEGER NOT NULL, "
            "site_url TEXT NOT NULL, "
            "start_urls JSON NOT NULL, "
            "enabled BOOLEAN NOT NULL, "
            "schedule_type VARCHAR(32) NOT NULL, "
            "scan_time VARCHAR(8) NOT NULL, "
            "weekday INTEGER NOT NULL, "
            "next_run_at DATETIME, "
            "thread_count INTEGER NOT NULL, "
            "connection_method VARCHAR(64) NOT NULL, "
            "connection_method_id INTEGER, "
            "auto_connection_fallback BOOLEAN NOT NULL, "
            "exclusions JSON NOT NULL, "
            "product_url_filters JSON NOT NULL, "
            "extraction_rules JSON NOT NULL, "
            "selector_settings JSON NOT NULL, "
            "seen_models JSON NOT NULL, "
            "known_new_products JSON NOT NULL, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL, "
            "FOREIGN KEY(brand_id) REFERENCES brands (id) ON DELETE CASCADE, "
            "FOREIGN KEY(connection_method_id) REFERENCES connection_methods (id)"
            ")"
        )
    )
    id_expr = "CAST(id AS TEXT)" if columns.get("id") != "INTEGER" else "COALESCE(legacy_id, CAST(id AS TEXT))"
    connection.execute(
        text(
            "INSERT INTO donors_migration_tmp (legacy_id, brand_id, site_url, start_urls, enabled, "
            "schedule_type, scan_time, weekday, next_run_at, thread_count, connection_method, "
            "connection_method_id, auto_connection_fallback, exclusions, product_url_filters, "
            "extraction_rules, selector_settings, seen_models, known_new_products, created_at, updated_at) "
            f"SELECT {id_expr}, brand_id, COALESCE(site_url, ''), {safe_json_expr('start_urls', '[]')}, "
            "COALESCE(enabled, 1), COALESCE(NULLIF(schedule_type, ''), 'daily'), "
            "COALESCE(NULLIF(scan_time, ''), '01:00'), CAST(COALESCE(NULLIF(weekday, ''), 0) AS INTEGER), "
            f"{datetime_expr('next_run_at')}, "
            "CAST(COALESCE(NULLIF(thread_count, ''), 4) AS INTEGER), "
            "COALESCE(NULLIF(connection_method, ''), 'requests'), "
            "(SELECT id FROM connection_methods WHERE code = COALESCE(NULLIF(donors.connection_method, ''), 'requests') LIMIT 1), "
            "COALESCE(auto_connection_fallback, 1), "
            f"{safe_json_expr('exclusions', '[]')}, "
            f"{safe_json_expr('product_url_filters', '[]')}, "
            f"{safe_json_expr('extraction_rules', '{}')}, "
            f"{safe_json_expr('selector_settings', '{}')}, "
            f"{safe_json_expr('seen_models', '[]')}, "
            f"{safe_json_expr('known_new_products', '{}')}, "
            "COALESCE(created_at, CURRENT_TIMESTAMP), COALESCE(updated_at, CURRENT_TIMESTAMP) "
            "FROM donors ORDER BY brand_id, created_at, rowid"
        )
    )
    connection.execute(text("DROP TABLE donors"))
    connection.execute(text("ALTER TABLE donors_migration_tmp RENAME TO donors"))
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
