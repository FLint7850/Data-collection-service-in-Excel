import pytest

import run_production


def test_production_rejects_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "FLASK_SECRET_KEY": "change-this-secret-key",
        "ALLOW_INSECURE_DEFAULTS": "0",
    }
    monkeypatch.setattr(run_production, "env_str", lambda name, default="": values.get(name, default))
    with pytest.raises(RuntimeError, match="FLASK_SECRET_KEY"):
        run_production.validate_production_settings()


def test_production_allows_configured_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "FLASK_SECRET_KEY": "a-strong-random-secret",
        "ALLOW_INSECURE_DEFAULTS": "0",
    }
    monkeypatch.setattr(run_production, "env_str", lambda name, default="": values.get(name, default))
    run_production.validate_production_settings()
