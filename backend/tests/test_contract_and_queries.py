import json
from pathlib import Path
from datetime import timedelta
from app.common import *
from app.db import Session
from app.telemetry import sign, ingest, consume_once
from test_workflows import call, start, finish, seed_energy, A, B


def test_contract_paths_and_time_phone_filters(client, user_headers, admin_headers):
    source = Path(__file__).parents[1] / "api-contract.json"
    expected = {
        (item["method"], item["path"])
        for item in json.loads(source.read_text(encoding="utf-8"))
    }
    assert len(expected) == 113
    schema = client.get("/openapi.json").json()
    actual = {(method.upper(), path) for path, ops in schema["paths"].items() for method in ops}
    assert expected <= actual
    assert client.get("/api/v1/app/no-such-resource").json()["code"] == 40400
    assert client.get(A + "/stations/not-an-id", headers=user_headers).json()["code"] == 40000
    s = start(client, user_headers)
    seed_energy(s["id"], 3)
    finish(client, user_headers, s)
    before = (now() - timedelta(days=1)).isoformat()
    after = (now() + timedelta(days=1)).isoformat()
    r = client.get(
        B + "/orders",
        headers=admin_headers,
        params={"keyword": "13800138000", "startTime": before, "endTime": after},
    )
    assert r.json()["data"]["total"] == 1, r.text
    r = client.get(B + "/orders", headers=admin_headers, params={"startTime": after})
    assert r.json()["data"]["total"] == 0


def test_signed_device_fault_and_no_normal_reward(client, user_headers):
    s = start(client, user_headers)
    with Session.begin() as db:
        change(db, m.session, s["id"], start_time=now() - timedelta(minutes=10))
    e = {
        "pileId": 1,
        "sessionId": s["id"],
        "sequence": 1,
        "energyKwh": "2",
        "powerKw": "0",
        "observedAt": now().isoformat(),
        "faultReason": "设备过温保护",
    }
    e["signature"] = sign(e)
    ingest([e])
    consume_once(1, "fault-test")
    current = call(client, "GET", A + "/charging/sessions/current", user_headers)
    assert current["status"] == "ABNORMAL" and current["abnormalReason"] == "设备过温保护"
    left = call(client, "POST", A + f"/charging/sessions/{s['id']}/leave", user_headers)
    call(client, "POST", A + f"/orders/{left['orderId']}/pay", user_headers, {"payMethod": "MOCK"})
    with Session() as db:
        assert get(db, m.pile, 1)["status"] == "FAULT"
        assert count(db, m.points, m.points.c.change_type == "CHARGE_REWARD") == 0
        assert count(db, m.credit, m.credit.c.change_type == "NORMAL_CHARGE") == 0
