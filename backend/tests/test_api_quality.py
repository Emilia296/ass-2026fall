from app.common import DATE_FILTER_COLUMNS
from app import models as m
from app.validation import query_for, schema_for
from test_workflows import A, call


def test_openapi_describes_queries_and_action_bodies(client):
    spec = client.get("/openapi.json").json()
    station = spec["paths"][A + "/stations"]["get"]
    names = {p["name"] for p in station["parameters"]}
    assert {"page", "pageSize", "longitude", "latitude", "pileType"} <= names
    scan = spec["paths"][A + "/piles/scan"]["get"]
    qr = next(p for p in scan["parameters"] if p["name"] == "qrCode")
    assert qr["required"] is True
    favorite = spec["paths"][A + "/stations/{stationId}/favorite"]["post"]
    assert "requestBody" not in favorite
    reservation = spec["paths"][A + "/reservations"]["post"]["requestBody"]
    assert reservation["required"] is True

    coupons = spec["paths"][A + "/coupons"]["get"]
    coupon_queries = {p["name"] for p in coupons["parameters"]}
    assert "status" in coupon_queries
    assert "couponStatus" not in coupon_queries

    telemetry = spec["paths"]["/api/v1/device/telemetry"]["post"]
    events = telemetry["requestBody"]["content"]["application/json"]["schema"]["properties"][
        "events"
    ]
    assert events["maxItems"] == 1000

    admin_fault = spec["paths"]["/api/v1/admin/faults"]["post"]
    assert admin_fault["security"] == [{"BearerAuth": []}]
    assert set(admin_fault["requestBody"]["content"]["application/json"]["schema"]["required"]) == {
        "pileId",
        "faultType",
        "faultDescription",
    }


def test_scan_missing_qr_code_is_parameter_error(client, user_headers):
    call(client, "GET", A + "/piles/scan", user_headers, code=40000)


def test_sms_response_does_not_echo_code(client):
    result = client.post(A + "/auth/sms-code", json={"phone": "13800138009"}).json()
    assert result["code"] == 0
    assert set(result["data"]) == {"sent", "expiresIn"}


def test_date_filters_use_business_timestamps():
    assert DATE_FILTER_COLUMNS[m.reservation.name] == "reservation_time"
    assert DATE_FILTER_COLUMNS[m.fault.name] == "fault_time"
    assert query_for("/api/v1/admin/faults")
    assert schema_for("/api/v1/app/stations/1/favorite", "POST")["properties"] == {}
