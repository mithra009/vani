"""Auth and ownership, offline: no Supabase calls."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import auth, store
from backend.app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_requests_without_a_valid_token_are_rejected(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_DISABLED", False)
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/jobs", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401
    assert client.get("/api/jobs?access_token=forged").status_code == 401
    assert client.get("/api/health").status_code == 200        # public


def test_other_users_projects_are_invisible(client):
    store.save_job({"id": "someoneelse1", "user_id": "another-user", "name": "x.mp4", "created_at": 1,
                    "mode": "dub", "status": "review", "segments": [], "_": {}})
    assert client.get("/api/jobs/someoneelse1").status_code == 404
    assert all(j["id"] != "someoneelse1" for j in client.get("/api/jobs").json())
    assert client.get("/api/jobs/someoneelse1/output.mp4").status_code == 404
    assert client.post("/api/jobs/someoneelse1/dub", json={}).status_code == 404


@pytest.mark.parametrize("username,ok", [
    ("mithra", True), ("mithra_009", True), ("a-b", True),
    ("ab", False), ("-mithra", False), ("mithra-", False), ("Mithra Vardhan", False), ("x" * 31, False),
])
def test_username_rules(username, ok):
    data = {"username": username, "first_name": "M", "last_name": "P", "email": "m@example.com", "password": "longenough"}
    if ok:
        assert auth.SignUp(**data).username == username.lower()
    else:
        with pytest.raises(ValidationError):
            auth.SignUp(**data)


def test_signup_validation():
    base = {"username": "mithra", "first_name": "M", "last_name": "P", "email": "m@example.com", "password": "longenough"}
    with pytest.raises(ValidationError):
        auth.SignUp(**{**base, "password": "short"})
    with pytest.raises(ValidationError):
        auth.SignUp(**{**base, "email": "not-an-email"})
    with pytest.raises(ValidationError):
        auth.SignUp(**{**base, "first_name": "   "})
    assert auth.SignUp(**{**base, "username": "  MiThRa  "}).username == "mithra"
