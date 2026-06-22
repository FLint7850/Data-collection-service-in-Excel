from parser_app.services import common


def test_storage_initialization_runs_once(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(common, "_storage_initialized", False)
    monkeypatch.setattr(common, "init_db", lambda: calls.append("db"))
    monkeypatch.setattr(common, "ensure_default_user", lambda: calls.append("user"))
    monkeypatch.setattr(common, "load_projects", lambda: calls.append("projects"))
    monkeypatch.setattr(common, "load_news_settings", lambda: calls.append("news"))
    monkeypatch.setattr(common, "start_news_scheduler", lambda: calls.append("scheduler"))

    common.ensure_storage()
    common.ensure_storage()

    assert calls == ["db", "user", "projects", "news", "scheduler"]


def test_storage_force_reload_is_explicit(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(common, "_storage_initialized", False)
    monkeypatch.setattr(common, "init_db", lambda: calls.append("db"))
    monkeypatch.setattr(common, "ensure_default_user", lambda: None)
    monkeypatch.setattr(common, "load_projects", lambda: None)
    monkeypatch.setattr(common, "load_news_settings", lambda: None)
    monkeypatch.setattr(common, "start_news_scheduler", lambda: None)

    common.ensure_storage()
    common.ensure_storage(force_reload=True)

    assert calls == ["db", "db"]
