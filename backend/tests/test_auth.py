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


def test_generated_username_is_valid_and_unique_per_user():
    user_id = "01234567-89ab-cdef-0123-456789abcdef"
    username = auth._generated_username("a.user+test@example.com", user_id)
    assert auth.USERNAME_RE.fullmatch(username)
    assert username.startswith("a_user_test_")
    assert auth._generated_username("a.user+test@example.com", user_id, 1) != username


def test_google_profile_is_created_from_authenticated_user(client, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_DISABLED", False)
    monkeypatch.setattr(auth, "verify", lambda token: {
        "id": "01234567-89ab-cdef-0123-456789abcdef", "email": "google.user@example.com",
    })
    profiles = {}

    class Query:
        def __init__(self, table):
            self.table = table
            self.filters = {}

        def select(self, _columns):
            return self

        def eq(self, key, value):
            self.filters[key] = value
            return self

        def limit(self, _count):
            return self

        def execute(self):
            rows = [row for row in profiles.values()
                    if all(row.get(key) == value for key, value in self.filters.items())]
            return type("Result", (), {"data": rows})()

        def insert(self, row):
            profiles[row["id"]] = row
            return self

    class Database:
        def table(self, _name):
            return Query("users")

    monkeypatch.setattr(auth.supa, "admin", lambda: Database())

    response = client.post(
        "/api/auth/profile",
        headers={"Authorization": "Bearer valid"},
        json={"first_name": "Google", "last_name": "User"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "google.user@example.com"
    assert response.json()["first_name"] == "Google"
    assert auth.USERNAME_RE.fullmatch(response.json()["username"])
