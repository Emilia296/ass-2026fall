"""One real HTTP charging flow. Uses the explicitly seeded second demo account."""

import json, time
import httpx

base = "http://127.0.0.1:8080"
with httpx.Client(base_url=base, timeout=15) as c:
    assert c.get("/health").json()["code"] == 0
    auth = c.post(
        "/api/v1/app/auth/login",
        json={"phone": "13800138001", "loginMethod": "PASSWORD", "password": "User123!"},
    ).json()
    assert auth["code"] == 0, auth
    c.headers["Authorization"] = "Bearer " + auth["data"]["accessToken"]

    def request(method, path, body=None):
        r = c.request(method, "/api/v1/app/" + path, json=body)
        result = r.json()
        assert result["code"] == 0, (path, result)
        return result["data"]

    assert request("GET", "charging/sessions/current") is None, (
        "Demo user already has a session; leave it untouched"
    )
    vehicles = request("GET", "vehicles")
    piles = request("GET", "stations/1/piles?status=IDLE")
    s = request(
        "POST",
        "charging/sessions",
        {"vehicleId": vehicles[0]["id"], "pileId": piles[0]["id"], "targetSoc": 90},
    )
    time.sleep(5)
    current = request("GET", "charging/sessions/current")
    assert current["energyKwh"] > 0, "Simulator/stream/worker did not advance the meter"
    request("POST", f"charging/sessions/{s['id']}/stop")
    left = request("POST", f"charging/sessions/{s['id']}/leave")
    paid = request("POST", f"orders/{left['orderId']}/pay", {"payMethod": "MOCK"})
    assert paid["order"]["paymentStatus"] == "PAID"
    print(
        json.dumps(
            {
                "health": "ok",
                "telemetryEnergyKwh": current["energyKwh"],
                "orderId": left["orderId"],
                "payment": "PAID",
                "openapi": c.get("/openapi.json").status_code,
            },
            ensure_ascii=False,
        )
    )
