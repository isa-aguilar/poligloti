"""Creating a learner from the app, without touching files by hand."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import config, memory


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return TestClient(app_module.app)


def test_create_profile_then_list_it(client, tmp_path):
    r = client.post(
        "/profiles",
        json={"name": "Alex Doe", "target_language": "fr", "goals": "Travel to Lyon."},
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"user": "alex_doe", "name": "Alex Doe", "primary_language": "fr"}

    profiles = client.get("/profiles").json()["profiles"]
    assert [(p["user"], p["name"], p["primary_language"]) for p in profiles] == [
        ("alex_doe", "Alex Doe", "fr")
    ]
    user_md = (tmp_path / "alex_doe" / "fr" / "USER.md").read_text(encoding="utf-8")
    assert "Travel to Lyon." in user_md
    # No level is invented: the assessment measures it.
    assert memory.read_user_cefr_declared("alex_doe", "fr") is None


def test_duplicate_and_invalid_profiles_are_rejected(client):
    assert (
        client.post("/profiles", json={"name": "Sam", "target_language": "de"}).status_code == 201
    )
    assert (
        client.post("/profiles", json={"name": "sam", "target_language": "en"}).status_code == 409
    )
    assert client.post("/profiles", json={"name": "  ", "target_language": "de"}).status_code == 400
    assert (
        client.post("/profiles", json={"name": "Kim", "target_language": "xx"}).status_code == 400
    )
