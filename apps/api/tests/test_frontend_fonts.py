from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app


@pytest.mark.parametrize("name", ["geist-400.ttf", "geist-500.ttf", "geist-600.ttf", "jetbrains-mono-400.ttf"])
def test_bundled_fonts_are_served_at_css_urls(monkeypatch, name):
    fonts = Path(__file__).resolve().parents[2] / "frontend" / "public" / "fonts"
    mount = next((route for route in app.routes if getattr(route, "path", None) == "/fonts"), None)
    assert mount is not None, "Production app must expose the /fonts URLs used by Vite CSS"
    monkeypatch.setattr(mount.app, "directory", str(fonts))
    monkeypatch.setattr(mount.app, "all_directories", [str(fonts)])
    response = TestClient(app).get(f"/fonts/{name}")
    assert response.status_code == 200
    assert response.content == (fonts / name).read_bytes()


def test_font_mount_does_not_expose_parent_files(monkeypatch, tmp_path):
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    (tmp_path / "private.txt").write_text("not public")
    mount = next(route for route in app.routes if getattr(route, "path", None) == "/fonts")
    monkeypatch.setattr(mount.app, "directory", str(fonts))
    monkeypatch.setattr(mount.app, "all_directories", [str(fonts)])
    response = TestClient(app).get("/fonts/%2e%2e/private.txt")
    assert response.status_code == 404
