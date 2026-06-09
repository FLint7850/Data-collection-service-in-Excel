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
        connection.execute(text("DROP TABLE IF EXISTS feed_products"))
        connection.execute(text("DROP TABLE IF EXISTS logs"))
        connection.execute(text("DROP TABLE IF EXISTS scan_runs"))
        own_site_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(own_sites)")).fetchall()}
        if own_site_columns and "name" not in own_site_columns:
            connection.execute(text("ALTER TABLE own_sites ADD COLUMN name VARCHAR(255) NOT NULL DEFAULT ''"))
        brand_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(brands)")).fetchall()}
        if brand_columns and "exclusions" not in brand_columns:
            connection.execute(text("ALTER TABLE brands ADD COLUMN exclusions JSON NOT NULL DEFAULT '[]'"))
        if brand_columns and "state" not in brand_columns:
            connection.execute(text("ALTER TABLE brands ADD COLUMN state JSON NOT NULL DEFAULT '{\"status\":\"idle\"}'"))
        connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        current_revision = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        if not current_revision:
            connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260608_0001')"))


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
