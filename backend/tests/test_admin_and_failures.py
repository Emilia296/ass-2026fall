from datetime import timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from app.common import *
from app.db import Session
from app.security import cache
from app.telemetry import sign, ingest, consume_once
from app.worker import maintenance_once
from test_workflows import call, start, finish, seed_energy, A, B
from conftest import login


def test_admin_crud_permissions_and_audit(client, admin_headers, user_headers):
    h = admin_headers
    s = call(
        client,
        "POST",
        B + "/stations",
        h,
        {
            "stationName": "验收站",
            "city": "北京",
            "address": "验收路1号",
            "longitude": 116.4,
            "latitude": 39.9,
        },
    )
    sid = s["id"]
    call(client, "PUT", B + f"/stations/{sid}", h, {"stationName": "验收站更新"})
    call(client, "PUT", B + f"/stations/{sid}/status", h, {"status": "PAUSED", "reason": "检修"})
    p = call(
        client,
        "POST",
        B + "/piles",
        h,
        {
            "stationId": sid,
            "pileNo": "CHECK-001",
            "pileType": "FAST",
            "powerKw": 60,
            "qrCode": "PILE:CHECK-001",
        },
    )
    call(client, "PUT", B + f"/piles/{p['id']}", h, {"powerKw": 80})
    call(client, "PUT", B + f"/piles/{p['id']}/status", h, {"status": "MAINTAIN", "reason": "检修"})
    price = call(
        client,
        "POST",
        B + "/price-plans",
        h,
        {
            "planName": "验收电价",
            "stationId": sid,
            "effectiveFrom": now().isoformat(),
            "periods": [
                {
                    "startTime": "00:00",
                    "endTime": "24:00",
                    "electricityPrice": 0.8,
                    "servicePrice": 0.2,
                }
            ],
        },
    )
    call(client, "PUT", B + f"/price-plans/{price['id']}", h, {"planName": "价格更新"})
    call(client, "PUT", B + "/occupancy-fee-rules/1", h, {"freeMinutes": 30, "maxAmount": 25})
    call(client, "PUT", B + "/occupancy-fee-rules/1", h, {"freeMinutes": 29}, 40000)
    role = call(client, "POST", B + "/roles", h, {"roleCode": "REVIEW", "roleName": "只读验收"})
    tree = call(client, "GET", B + "/permissions/tree", h)
    perm = next(
        c["id"] for x in tree for c in x["children"] if c["permissionCode"] == "station:view"
    )
    call(client, "PUT", B + f"/roles/{role['id']}/permissions", h, {"permissionIds": [perm]})
    admin = call(
        client,
        "POST",
        B + "/admin-users",
        h,
        {
            "username": "review",
            "password": "Review123!",
            "realName": "验收员",
            "roleIds": [role["id"]],
        },
    )
    result = client.post(
        B + "/auth/login", json={"username": "review", "password": "Review123!"}
    ).json()["data"]
    rh = {"Authorization": "Bearer " + result["accessToken"]}
    call(client, "GET", B + "/stations", rh)
    call(client, "GET", B + "/users", rh, code=40300)
    call(client, "PUT", B + f"/roles/{role['id']}/permissions", h, {"permissionIds": []})
    call(client, "GET", B + "/stations", rh, code=40300)
    call(client, "PUT", B + f"/admin-users/{admin['id']}/status", h, {"status": "DISABLED"})
    call(client, "GET", B + "/stations", rh, code=40001)
    call(
        client,
        "PUT",
        B + "/system-configs/PAYMENT_OVERDUE_HOURS",
        h,
        {"configValue": "48", "reason": "验收"},
    )
    with Session() as db:
        assert count(db, m.audit, m.audit.c.result == "SUCCESS") >= 12
        logs = rows(db, m.audit)
        assert not any("passwordHash" in str(x["after_data"]) for x in logs)


def test_fault_flow_user_adjustments_and_coupon_rules(client, user_headers, admin_headers):
    f = call(
        client,
        "POST",
        A + "/faults",
        user_headers,
        {"pileId": 6, "faultType": "CANNOT_START", "faultDescription": "无法启动"},
    )
    call(client, "POST", B + f"/faults/{f['id']}/process", admin_headers, {"handleNote": "已接单"})
    call(
        client,
        "POST",
        B + f"/faults/{f['id']}/resolve",
        admin_headers,
        {"handleNote": "已修复", "pileStatus": "IDLE"},
    )
    assert call(client, "GET", A + "/messages?messageType=FAULT_RESULT", user_headers)["total"] == 1
    call(
        client,
        "POST",
        B + "/users/1/points/adjust",
        admin_headers,
        {"changePoints": -100, "reason": "验收"},
    )
    call(
        client,
        "POST",
        B + "/users/1/credit/adjust",
        admin_headers,
        {"changeScore": -25, "reason": "验收"},
    )
    call(
        client,
        "POST",
        A + "/reservations",
        user_headers,
        {"vehicleId": 1, "pileId": 1, "stationId": 1, "reservationTime": now().isoformat()},
        42002,
    )
    rule = call(
        client,
        "POST",
        B + "/coupon-event-rules",
        admin_headers,
        {"eventType": "DAILY_LOGIN", "couponTemplateId": 1, "probability": 1, "dailyLimit": 1},
    )
    call(client, "PUT", B + "/coupon-event-rules/1", admin_headers, {"status": "DISABLED"})
    assert call(client, "POST", A + "/coupon-events/daily-login", user_headers)["triggered"]
    assert not call(client, "POST", A + "/coupon-events/daily-login", user_headers)["triggered"]
    t = call(
        client,
        "POST",
        B + "/coupon-templates",
        admin_headers,
        {
            "couponName": "八折券",
            "couponType": "DISCOUNT",
            "discountRate": 0.8,
            "totalQuantity": 10,
            "validDays": 7,
        },
    )
    call(
        client,
        "POST",
        B + f"/coupon-templates/{t['id']}/grant",
        admin_headers,
        {"userIds": [1, 2], "reason": "验收"},
    )
    call(
        client,
        "PUT",
        B + f"/coupon-templates/{t['id']}/status",
        admin_headers,
        {"status": "STOPPED"},
    )


def test_reservation_arrive_start_and_same_user_race(client, user_headers):
    r = call(
        client,
        "POST",
        A + "/reservations",
        user_headers,
        {"vehicleId": 1, "pileId": 1, "stationId": 1, "reservationTime": now().isoformat()},
    )
    call(client, "POST", A + f"/reservations/{r['id']}/arrive", user_headers)
    s = call(
        client,
        "POST",
        A + "/charging/sessions",
        user_headers,
        {"vehicleId": 1, "pileId": 1, "targetSoc": 80, "reservationId": r["id"]},
    )
    finish(client, user_headers, s)
    with Session() as db:
        assert get(db, m.reservation, r["id"])["status"] == "COMPLETED"

    def attempt(pid):
        return client.post(
            A + "/charging/sessions",
            headers=user_headers,
            json={"vehicleId": 1, "pileId": pid, "targetSoc": 90},
        ).json()["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(attempt, [2, 3]))
    assert sorted(codes) == [0, 41003]


def test_overdue_once_and_admin_stop(client, user_headers, admin_headers):
    s = start(client, user_headers)
    seed_energy(s["id"], 5)
    result = call(
        client,
        "POST",
        B + f"/charging/sessions/{s['id']}/stop",
        admin_headers,
        {"reason": "运维停机"},
    )
    assert result["stopReason"] == "ADMIN_STOP"
    left = call(client, "POST", A + f"/charging/sessions/{s['id']}/leave", user_headers)
    with Session.begin() as db:
        change(db, m.order, left["orderId"], overdue_at=now() - timedelta(hours=1))
    maintenance_once()
    maintenance_once()
    with Session() as db:
        assert count(db, m.credit, m.credit.c.change_type == "PAYMENT_OVERDUE") == 1
    call(client, "POST", A + f"/orders/{left['orderId']}/pay", user_headers, {"payMethod": "MOCK"})


def test_malformed_inputs_are_client_errors(client, user_headers, admin_headers):
    call(client, "PUT", A + "/users/me", user_headers, {"nickname": "x" * 256}, 40000)
    cases = [
        ("POST", A + "/vehicles", {"plateNumber": "BAD", "batteryCapacity": -1}),
        ("POST", A + "/charging/sessions", {"vehicleId": True, "pileId": 1, "targetSoc": 80}),
        ("POST", A + "/charging/sessions", {"vehicleId": 1, "pileId": 1, "targetSoc": 81}),
        ("PUT", A + "/users/me", {"nickname": {"injection": "bad"}}),
        ("POST", B + "/stations", {}),
        ("PUT", B + "/system-configs/PAYMENT_OVERDUE_HOURS", {"configValue": "-1"}),
    ]
    for method, path, body in cases:
        r = client.request(
            method, path, headers=admin_headers if "/admin/" in path else user_headers, json=body
        )
        assert 400 <= r.status_code < 500, (path, r.text)
    r = client.post(A + "/auth/login", content="[", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    schema = client.get("/openapi.json").json()
    assert "BearerAuth" in schema["components"]["securitySchemes"]
    assert (
        "targetSoc"
        in schema["paths"][A + "/charging/sessions"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]["properties"]
    )


def test_pending_stream_reclaim_and_invalid_message_dlq(client, user_headers):
    s = start(client, user_headers)
    with Session.begin() as db:
        change(db, m.session, s["id"], start_time=now() - timedelta(minutes=10))
    e = {
        "pileId": 1,
        "sessionId": s["id"],
        "sequence": 1,
        "energyKwh": "1",
        "powerKw": "120",
        "observedAt": now().isoformat(),
    }
    e["signature"] = sign(e)
    ingest([e])
    cache.xgroup_create("telemetry:1", "billing", id="0")
    mid = cache.xreadgroup("billing", "crashed", {"telemetry:1": ">"})[0][1][0][0]
    cache.xclaim("telemetry:1", "billing", "crashed", 0, [mid], idle=31000)
    consume_once(1, "recovery")
    with Session() as db:
        assert get(db, m.session, s["id"])["energy_kwh"] == 1
    assert cache.xpending("telemetry:1", "billing")["pending"] == 0
    cache.xadd("telemetry:1", {"event": "{bad json"})
    consume_once(1, "recovery")
    assert cache.xlen("telemetry:dead-letter") == 1
