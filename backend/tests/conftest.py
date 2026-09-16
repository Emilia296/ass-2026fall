import os

os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://charge:charge@localhost:5432/charge_test"
)
os.environ["REDIS_URL"] = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ["DEMO_MODE"] = "true"
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient
from app.db import engine, metadata, Session
from app.seed import seed
from app.security import cache
from app.main import app


@pytest.fixture(autouse=True)
def reset_database():
    assert engine.url.database.endswith("_test"), "Refuse to reset non-test database"
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE "
                + ",".join('"' + t.name + '"' for t in metadata.sorted_tables)
                + " RESTART IDENTITY CASCADE"
            )
        )
    assert cache.connection_pool.connection_kwargs["db"] == 15, "Refuse to reset non-test Redis"
    cache.flushdb()
    seed()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(client, admin=False, second=False):
    path = "/api/v1/admin/auth/login" if admin else "/api/v1/app/auth/login"
    body = (
        {"username": "admin", "password": "Admin123!"}
        if admin
        else {
            "phone": "13800138001" if second else "13800138000",
            "password": "User123!",
            "loginMethod": "PASSWORD",
        }
    )
    res = client.post(path, json=body)
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["data"]["accessToken"]}


@pytest.fixture
def user_headers(client):
    return login(client)


@pytest.fixture
def admin_headers(client):
    return login(client, True)
