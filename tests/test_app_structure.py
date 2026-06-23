from pathlib import Path
import shutil
import subprocess

import pytest

from parser_app import app
from parser_app import runtime
from parser_app.routes import core
from parser_app.services import lifecycle


EXPECTED_ROUTES = {
    "/",
    "/login",
    "/logout",
    "/api/health",
    "/api/state",
    "/api/connection-methods",
    "/api/news",
    "/api/file-import",
    "/api/projects",
    "/api/logs",
    "/progress",
}


class FakeSession:
    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_all_original_routes_are_registered() -> None:
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert len(list(app.url_map.iter_rules())) == 51
    assert EXPECTED_ROUTES <= rules


def test_templates_and_static_paths_point_to_project_root() -> None:
    assert Path(app.template_folder) == runtime.BASE_DIR / "templates"
    assert Path(app.static_folder) == runtime.BASE_DIR / "static"
    assert (runtime.BASE_DIR / "templates" / "index.html").is_file()
    assert (runtime.BASE_DIR / "static" / "js" / "app" / "core.js").is_file()


def test_public_endpoints_and_frontend_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "SessionLocal", FakeSession)
    monkeypatch.setattr(core, "ensure_storage", lambda: None)
    monkeypatch.setattr(core, "ensure_default_user", lambda: None)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")

    with app.test_client() as client:
        assert client.get("/api/health").get_json() == {"ok": True}
        assert client.get("/login").status_code == 200
        assert client.get("/static/js/app/core.js").status_code == 200
        with client.session_transaction() as session:
            session["user_id"] = 1
            session["username"] = "test"
        response = client.get("/")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        for filename in ("core.js", "settings.js", "news.js", "workspace.js", "events.js"):
            assert f"/static/js/app/{filename}" in html


def test_frontend_files_have_valid_javascript_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    for script in sorted((runtime.BASE_DIR / "static" / "js" / "app").glob("*.js")):
        subprocess.run([node, "--check", str(script)], check=True, capture_output=True, text=True)
