from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
from sqlalchemy import select, update
from app.common import *
from app.db import Session
from app import charging, benefits
from app.security import cache
from app.worker import maintenance_once
from app.telemetry import ingest, sign, consume_once
from conftest import login

A = "/api/v1/app"
B = "/api/v1/admin"


def call(c, method, path, h, b=None, code=0):
    r = c.request(method, path, headers=h, json=b)
    data = r.json()
    assert data["code"] == code, (path, r.status_code, data)
    return data["data"]


def start(c, h, pile=1, vehicle=1):
    return call(
        c,
        "POST",
        A + "/charging/sessions",
        h,
        {"vehicleId": vehicle, "pileId": pile, "targetSoc": 80},
    )


def finish(c, h, s):
    call(c, "POST", A + f"/charging/sessions/{s['id']}/stop", h)
    return call(c, "POST", A + f"/charging/sessions/{s['id']}/leave", h)


def seed_energy(sid, energy=25):
    with Session.begin() as db:
        s = get(db, m.session, sid, lock=True)
        at = now()
        change(db, m.session, sid, start_time=at - timedelta(hours=1))
        s = get(db, m.session, sid)
        charging.meter(db, s, energy, at, 1, Decimal(120))


def test_full_charging_payment_refund(client, user_headers, admin_headers):
    h = user_headers
    a = admin_headers
    stations = call(
        client, "GET", A + "/stations?longitude=116.51&latitude=39.92&sortBy=DISTANCE", h
    )
    assert stations["total"] == 3 and stations["list"][0]["distanceKm"] >= 0
    scan = call(client, "GET", A + "/piles/scan?qrCode=PILE:BJ-001-001", h)
    assert scan["canStartCharging"]
    s = start(client, h)
    seed_energy(s["id"])
    current = call(client, "GET", A + "/charging/sessions/current", h)
    assert current["energyKwh"] == 25
    call(
        client,
        "POST",
        A + "/charging/sessions",
        h,
        {"vehicleId": 1, "pileId": 2, "targetSoc": 80},
        41003,
    )
    left = finish(client, h, s)
    oid = left["orderId"]
    duplicate = call(client, "POST", A + f"/charging/sessions/{s['id']}/leave", h)
    assert duplicate["orderId"] == oid
    details = call(client, "GET", A + f"/orders/{oid}/fee-details", h)
    assert len(details) >= 2
    coupon = call(client, "POST", A + "/coupon-templates/1/exchange", h)["userCoupon"]
    q = call(client, "POST", A + f"/orders/{oid}/quote", h, {"userCouponId": coupon["id"]})
    assert q["couponDiscount"] == 5
    paid = call(
        client,
        "POST",
        A + f"/orders/{oid}/pay",
        h,
        {"userCouponId": coupon["id"], "payMethod": "MOCK"},
    )
    assert paid["order"]["paymentStatus"] == "PAID"
    call(client, "POST", A + f"/orders/{oid}/pay", h, {"payMethod": "MOCK"}, 44002)
    sale = call(
        client,
        "POST",
        A + "/after-sales",
        h,
        {"orderId": oid, "type": "AMOUNT_ERROR", "reason": "计费复核", "requestedAmount": 5},
    )
    result = call(
        client,
        "POST",
        B + f"/after-sales/{sale['id']}/handle",
        a,
        {
            "action": "REFUND",
            "handleResult": "核实后退款",
            "refundType": "PARTIAL",
            "refundAmount": 5,
        },
    )
    assert result["refund"]["couponReturned"] and result["refund"]["paymentId"]
    call(
        client,
        "POST",
        B + f"/after-sales/{sale['id']}/handle",
        a,
        {
            "action": "REFUND",
            "handleResult": "重复退款",
            "refundType": "PARTIAL",
            "refundAmount": 5,
        },
        45001,
    )
    assert call(client, "GET", A + "/coupons", h)["list"][0]["status"] == "UNUSED"
    summary = call(client, "GET", B + "/dashboard/summary", a)
    assert (
        summary["orderCount"] == 1
        and summary["platformRevenue"] == paid["payment"]["payAmount"] - 5
    )


def test_reservation_watch_expiration_idempotent(client, user_headers, admin_headers):
    h = user_headers
    call(client, "PUT", A + "/stations/1/availability-watch", h, {"pileType": "FAST"})
    r = call(
        client,
        "POST",
        A + "/reservations",
        h,
        {"vehicleId": 1, "stationId": 1, "pileId": 1, "reservationTime": now().isoformat()},
    )
    with Session.begin() as db:
        change(db, m.reservation, r["id"], expire_time=now() - timedelta(seconds=1))
    maintenance_once()
    maintenance_once()
    with Session() as db:
        assert get(db, m.reservation, r["id"])["status"] == "NO_SHOW"
        assert count(db, m.credit, m.credit.c.change_type == "RESERVATION_NO_SHOW") == 1
        assert count(db, m.message, m.message.c.message_type == "PILE_AVAILABLE") == 1
        assert get(db, m.pile, 1)["status"] == "IDLE"
    assert call(client, "GET", A + "/stations/1/availability-watch", h)["status"] == "NOTIFIED"
    call(client, "POST", A + "/stations/1/availability-watch/continue", h)
    call(client, "POST", A + "/stations/1/availability-watch/cancel", h)
    call(client, "POST", A + "/stations/1/availability-watch/continue", h, code=46002)


def test_ownership_roles_token_revocation(client, user_headers):
    other = login(client, second=True)
    call(client, "PUT", A + "/vehicles/1", other, {"currentSoc": 50}, 40400)
    s = start(client, user_headers)
    call(client, "GET", A + f"/charging/sessions/{s['id']}", other, code=40400)
    call(client, "GET", B + "/users", user_headers, code=40300)
    r = client.post(
        B + "/auth/login", json={"username": "maintainer", "password": "Maintainer123!"}
    )
    mh = {"Authorization": "Bearer " + r.json()["data"]["accessToken"]}
    call(client, "GET", B + "/users", mh, code=40300)
    call(client, "GET", B + "/piles", mh)
    call(
        client,
        "PUT",
        A + "/auth/password",
        user_headers,
        {"oldPassword": "User123!", "newPassword": "Changed123!"},
    )
    call(client, "GET", A + "/users/me", user_headers, code=40001)


def test_real_db_two_user_pile_race(client, user_headers):
    other = login(client, second=True)

    def attempt(pair):
        h, v = pair
        return client.post(
            A + "/charging/sessions", headers=h, json={"pileId": 1, "vehicleId": v, "targetSoc": 80}
        ).json()["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(attempt, [(user_headers, 1), (other, 2)]))
    assert sorted(codes) == [0, 41002]
    with Session() as db:
        assert count(db, m.session, m.session.c.leave_time.is_(None)) == 1


def test_duplicate_payment_and_coupon_stock_race(client, user_headers):
    s = start(client, user_headers)
    seed_energy(s["id"])
    oid = finish(client, user_headers, s)["orderId"]

    def pay(_):
        return client.post(
            A + f"/orders/{oid}/pay", headers=user_headers, json={"payMethod": "MOCK"}
        ).json()["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(pay, range(2)))
    assert sorted(codes) == [0, 44002]
    with Session() as db:
        assert count(db, m.payment) == 1
        assert count(db, m.points, m.points.c.change_type == "CHARGE_REWARD") == 1
    other = login(client, second=True)
    with Session.begin() as db:
        change(db, m.template, 1, total_quantity=1)

    def exchange(h):
        return client.post(A + "/coupon-templates/1/exchange", headers=h).json()["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(exchange, [user_headers, other]))
    assert sorted(codes) == [0, 43003]
    with Session() as db:
        assert count(db, m.coupon) == 1


def test_six_password_failures_and_unlock(client, admin_headers):
    for attempt in range(1, 7):
        r = client.post(
            A + "/auth/login",
            json={"phone": "13800138000", "password": "wrong", "loginMethod": "PASSWORD"},
        )
        assert r.json()["code"] == (40003 if attempt == 6 else 40002)
        if attempt < 6:
            with Session.begin() as db:
                change(db, m.user, 1, lock_until=now() - timedelta(seconds=1))
    with Session() as db:
        assert get(db, m.user, 1)["manual_locked"]
        assert count(db, m.login_log, m.login_log.c.result == "FAILED") == 6
    call(client, "POST", B + "/users/1/unlock", admin_headers, {"reason": "核实身份"})
    login(client)


def test_signed_telemetry_duplicate_and_target_stop(client, user_headers):
    s = start(client, user_headers)
    with Session.begin() as db:
        change(db, m.session, s["id"], start_time=now() - timedelta(hours=1))
    e = {
        "pileId": 1,
        "sessionId": s["id"],
        "sequence": 10,
        "energyKwh": "30",
        "powerKw": "120",
        "observedAt": now().isoformat(),
    }
    e["signature"] = sign(e)
    assert (
        client.post("/api/v1/device/telemetry", json={"events": [e, e]}).json()["data"]["accepted"]
        == 2
    )
    consume_once(1, "test-worker")
    with Session() as db:
        s = get(db, m.session, s["id"])
        assert s["status"] == "CHARGE_FINISHED" and s["stop_reason"] == "TARGET_REACHED"
        assert (
            s["energy_kwh"] == 30
            and count(db, m.message, m.message.c.message_type == "CHARGING_FINISHED") == 1
        )
    e["signature"] = "bad"
    assert client.post("/api/v1/device/telemetry", json={"events": [e]}).json()["code"] == 40300


def test_messages_and_readonly_contract(client, user_headers, admin_headers):
    with Session.begin() as db:
        notify(db, 1, "SYSTEM", "测试通知")
    assert call(client, "GET", A + "/messages/unread-count", user_headers)["unreadCount"] == 1
    call(client, "DELETE", A + "/messages/1", user_headers)
    assert call(client, "GET", A + "/messages/unread-count", user_headers)["unreadCount"] == 0
    assert call(client, "GET", A + "/messages", user_headers)["total"] == 0
    contract = json.loads((Path(__file__).parents[1] / "api-contract.json").read_text())
    for item in contract:
        if item["method"] != "GET" or "{" in item["path"] or item["path"].endswith("/piles/scan"):
            continue
        r = client.get(
            item["path"], headers=admin_headers if "/admin/" in item["path"] else user_headers
        )
        assert r.status_code == 200, (item["path"], r.text)


def test_price_validation_and_snapshot(client, user_headers, admin_headers):
    s = start(client, user_headers)
    with Session() as db:
        before = get(db, m.session, s["id"])["price_snapshot"]
    call(
        client,
        "PUT",
        B + "/price-plans/1/periods",
        admin_headers,
        {
            "periods": [
                {"startTime": "00:00", "endTime": "07:00", "electricityPrice": 1, "servicePrice": 1}
            ]
        },
        40000,
    )
    call(
        client,
        "PUT",
        B + "/price-plans/1/periods",
        admin_headers,
        {
            "periods": [
                {"startTime": "00:00", "endTime": "24:00", "electricityPrice": 9, "servicePrice": 1}
            ]
        },
    )
    with Session() as db:
        assert get(db, m.session, s["id"])["price_snapshot"] == before


def test_sms_once_and_default_vehicle_constraint(client, user_headers, monkeypatch):
    # Keep the test deterministic without making an authentication secret part
    # of the API response.
    monkeypatch.setattr("app.security.secrets.randbelow", lambda _: 23456)
    result = client.post(A + "/auth/sms-code", json={"phone": "13800138009"}).json()["data"]
    assert result == {"sent": True, "expiresIn": 300}
    body = {"phone": "13800138009", "loginMethod": "SMS_CODE", "smsCode": "123456"}
    assert client.post(A + "/auth/login", json=body).json()["code"] == 0
    assert client.post(A + "/auth/login", json=body).json()["code"] == 40004
    v = call(
        client,
        "POST",
        A + "/vehicles",
        user_headers,
        {"plateNumber": "京B123456", "batteryCapacity": 60, "currentSoc": 30, "isDefault": True},
    )
    assert call(client, "GET", A + "/vehicles/default", user_headers)["id"] == v["id"]
    with Session() as db:
        assert count(db, m.vehicle, m.vehicle.c.user_id == 1, m.vehicle.c.is_default.is_(True)) == 1
