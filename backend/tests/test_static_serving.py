"""Single-origin static SPA serving (PLAN.md §2, Stage 15 deployment).

`STATIC_DIR` is optional: unset keeps the API-only behavior, and a set
directory is mounted at `/` behind the versioned API routes, with startup
failing loudly when the directory does not exist.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.main import create_app


def make_static_dir(tmp_path: Path) -> Path:
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text(
        '<!doctype html><html class="light"><body><div id="app"></div></body></html>',
        encoding="utf-8",
    )
    (static_dir / "assets" / "app.css").write_text("body { margin: 0; }", encoding="utf-8")
    return static_dir


def make_settings(static_dir: str, database_path: str) -> Settings:
    return Settings(
        database_path=database_path,
        session_ttl_seconds=3600,
        app_origin="http://testserver",
        cookie_secure=False,
        app_env="development",
        static_dir=static_dir,
    )


def test_static_dir_defaults_to_disabled() -> None:
    assert load_settings(env={}).static_dir == ""
    assert load_settings(env={"STATIC_DIR": "/srv/basefit/static"}).static_dir == (
        "/srv/basefit/static"
    )
    # Blank falls back to the disabled default like every other variable.
    assert load_settings(env={"STATIC_DIR": "  "}).static_dir == ""


def test_serves_index_and_assets_next_to_the_api(tmp_path: Path, migrated_db: Path) -> None:
    static_dir = make_static_dir(tmp_path)
    app = create_app(make_settings(str(static_dir), str(migrated_db)))
    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert 'id="app"' in index.text

        asset = client.get("/assets/app.css")
        assert asset.status_code == 200
        assert asset.text == "body { margin: 0; }"

        # The API keeps priority over the catch-all mount.
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        # Hash routing needs no SPA rewrite rule; unknown paths stay 404.
        missing = client.get("/no-such-file.txt")
        assert missing.status_code == 404


def test_unknown_api_route_still_returns_problem_404(tmp_path: Path, migrated_db: Path) -> None:
    static_dir = make_static_dir(tmp_path)
    app = create_app(make_settings(str(static_dir), str(migrated_db)))
    with TestClient(app) as client:
        response = client.get("/api/v1/does-not-exist")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


def test_static_catch_all_preserves_known_api_method_errors(
    tmp_path: Path, migrated_db: Path
) -> None:
    static_dir = make_static_dir(tmp_path)
    app = create_app(make_settings(str(static_dir), str(migrated_db)))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/health",
            headers={"Origin": "http://testserver", "Content-Type": "application/json"},
        )
        assert response.status_code == 405
        assert response.headers["allow"] == "GET"
        assert response.json()["code"] == "http_error"

        unknown = client.post(
            "/api/v1/does-not-exist",
            headers={"Origin": "http://testserver", "Content-Type": "application/json"},
        )
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "not_found"


def test_without_static_dir_the_root_is_not_served(migrated_db: Path) -> None:
    app = create_app(make_settings("", str(migrated_db)))
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/v1/health").status_code == 200


def test_missing_static_dir_fails_startup(migrated_db: Path) -> None:
    with pytest.raises(ValueError, match="STATIC_DIR does not exist"):
        create_app(make_settings("/nonexistent/static-dir", str(migrated_db)))
