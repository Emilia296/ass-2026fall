import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from redis.exceptions import ConnectionError
from app.hot_cache import remember, RELEASE, PUBLISH
from app.security import cache
from app.common import BizError
from app import observability


def test_cache_single_flight_and_owner_fencing():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return {"answer": 42}

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(remember, "test:cache", loader)
        assert entered.wait(2)
        second = pool.submit(remember, "test:cache", loader)
        release.set()
        assert first.result() == second.result() == {"answer": 42}
    assert len(calls) == 1
    cache.set("test:lease", "new-owner")
    assert cache.eval(RELEASE, 1, "test:lease", "old-owner") == 0
    assert cache.eval(PUBLISH, 2, "test:lease", "test:value", "old-owner", "stale", 2) == 0
    assert cache.get("test:lease") == "new-owner" and cache.get("test:value") is None


def test_cache_backpressure_and_failure_release():
    cache.set("busy:fill", "other", ex=35)
    with pytest.raises(BizError) as error:
        remember("busy", lambda: pytest.fail("must not bypass lock"), wait_seconds=0)
    assert error.value.code == 50300

    def fail():
        raise ValueError("database failed")

    with pytest.raises(ValueError):
        remember("failed", fail)
    assert cache.get("failed:fill") is None


def test_public_test_observations_are_guarded_and_bounded(client, user_headers, admin_headers):
    assert client.post("/api/v1/device/telemetry", json=[]).json()["code"] == 40000
    client.request("CUSTOM", "/unmatched-endpoint")
    client.get("/api/v1/app/stations/1", headers=user_headers)
    assert client.get("/api/v1/admin/observability", headers=user_headers).status_code == 403
    result = client.get("/api/v1/admin/observability", headers=admin_headers).json()["data"]
    assert result["capacityValidated"] is False
    assert len(result["deviceQueues"]) == 16
    paths = [r["path"] for r in result["endpoints"]]
    assert "/api/v1/app/stations/{stationId}" in paths
    assert "/api/v1/app/stations/1" not in paths
    assert any(r["method"] == "OTHER" for r in result["endpoints"])


def test_observability_failure_does_not_break_business(client, user_headers, monkeypatch):
    def unavailable():
        raise ConnectionError("metrics unavailable")

    monkeypatch.setattr(observability.metrics, "pipeline", unavailable)
    result = client.get("/api/v1/app/users/me", headers=user_headers)
    assert result.status_code == 200 and result.json()["code"] == 0
