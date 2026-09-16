"""Shared request validation and OpenAPI schemas; keep the wire contract in one place."""

import re
from .common import require

REQUIRED = {
    ("POST", "app/auth/sms-code"): "phone",
    ("POST", "app/auth/login"): "phone loginMethod",
    ("POST", "admin/auth/login"): "username password",
    ("PUT", "app/auth/password"): "oldPassword newPassword",
    ("POST", "app/vehicles"): "plateNumber batteryCapacity",
    ("PUT", "app/stations/{id}/availability-watch"): "pileType",
    ("POST", "app/reservations"): "vehicleId stationId pileId reservationTime",
    ("POST", "app/charging/sessions"): "vehicleId pileId targetSoc",
    ("POST", "app/orders/{id}/pay"): "payMethod",
    ("POST", "app/after-sales"): "orderId type reason requestedAmount",
    ("POST", "app/faults"): "pileId faultType faultDescription",
    ("POST", "admin/stations"): "stationName city address longitude latitude",
    ("POST", "admin/piles"): "stationId pileNo pileType powerKw qrCode",
    ("POST", "admin/charging/sessions/{id}/stop"): "reason",
    ("POST", "admin/price-plans"): "planName stationId effectiveFrom periods",
    ("PUT", "admin/price-plans/{id}/periods"): "periods",
    ("PUT", "admin/users/{id}/status"): "status reason",
    ("POST", "admin/users/{id}/unlock"): "reason",
    ("POST", "admin/users/{id}/points/adjust"): "changePoints reason",
    ("POST", "admin/users/{id}/credit/adjust"): "changeScore reason",
    ("POST", "admin/coupon-templates"): "couponName couponType totalQuantity",
    ("POST", "admin/coupon-templates/{id}/grant"): "userIds reason",
    ("POST", "admin/coupon-event-rules"): "eventType couponTemplateId probability",
    ("POST", "admin/faults"): "pileId faultType faultDescription",
    ("POST", "admin/faults/{id}/resolve"): "handleNote pileStatus",
    ("POST", "admin/after-sales/{id}/handle"): "action handleResult",
    ("POST", "admin/admin-users"): "username password realName roleIds",
    ("POST", "admin/roles"): "roleCode roleName",
    ("PUT", "admin/roles/{id}/permissions"): "permissionIds",
    ("PUT", "admin/system-configs/{id}"): "configValue",
}
NUMBERS = {
    "batteryCapacity",
    "powerKw",
    "longitude",
    "latitude",
    "requestedAmount",
    "refundAmount",
    "electricityPrice",
    "servicePrice",
    "minAmount",
    "discountAmount",
    "discountRate",
    "maxDiscount",
    "maxAmount",
    "probability",
    "minConsumeAmount",
    "pricePerMinute",
}
INTEGERS = {
    "currentSoc",
    "targetSoc",
    "pointsCost",
    "changePoints",
    "changeScore",
    "totalQuantity",
    "perUserLimit",
    "validDays",
    "dailyLimit",
    "freeMinutes",
    "startMinute",
    "endMinute",
    "sortNo",
}
ARRAYS = {"periods", "tiers", "userIds", "roleIds", "permissionIds", "evidence"}
BOOLEANS = {"isDefault"}
FIELDS = {
    "auth/sms-code": "phone",
    "auth/login": "phone username loginMethod password smsCode",
    "auth/password": "oldPassword newPassword",
    "vehicles": "plateNumber vehicleName brand model batteryCapacity currentSoc isDefault",
    "stations": "stationName city address longitude latitude businessStart businessEnd contactPhone parkingNote status reason",
    "piles": "stationId pileNo pileType powerKw qrCode status reason",
    "reservations": "vehicleId stationId pileId reservationTime reason",
    "sessions": "vehicleId pileId targetSoc reservationId reason",
    "orders": "userCouponId payMethod",
    "after-sales": "orderId type reason evidence requestedAmount action handleResult refundType refundAmount",
    "faults": "pileId sessionId faultType faultDescription handleNote pileStatus",
    "price-plans": "planName stationId pileId version effectiveFrom effectiveTo status periods reason",
    "occupancy-fee-rules": "stationId freeMinutes maxAmount status tiers",
    "users": "nickname avatar status reason changePoints changeScore",
    "coupon-templates": "couponName couponType minAmount discountAmount discountRate maxDiscount totalQuantity perUserLimit validType validFrom validTo validDays pointsCost status userIds reason",
    "coupon-event-rules": "eventType couponTemplateId minConsumeAmount probability dailyLimit status",
    "admin-users": "username password realName phone roleIds status",
    "roles": "roleCode roleName status permissionIds",
    "system-configs": "configValue description reason",
    "availability-watch": "pileType",
}


def normalize(path):
    p = re.sub(r"\{[^}]+\}|(?<=/)\d+(?=/|$)", "{id}", path.removeprefix("/api/v1/"))
    if p.startswith("admin/system-configs/"):
        return "admin/system-configs/{id}"
    return p


def fields_for(path):
    p = normalize(path)
    parts = p.split("/")[1:]
    for key in ("auth/login", "auth/password", "auth/sms-code"):
        if "/".join(parts) == key:
            return FIELDS[key].split()
    if "availability-watch" in parts:
        return ["pileType"]
    return FIELDS.get("sessions" if parts[0] == "charging" else parts[0], "").split()


def schema_for(path, method):
    p = normalize(path)
    required = REQUIRED.get((method, p), "").split()
    if p.endswith("/status"):
        required = list(set(required + ["status"]))
    props = {}
    for k in fields_for(path):
        kind = (
            "number"
            if k in NUMBERS
            else "integer"
            if k in INTEGERS or k.endswith("Id")
            else "array"
            if k in ARRAYS
            else "boolean"
            if k in BOOLEANS
            else "string"
        )
        props[k] = {"type": kind}
        if kind == "array":
            props[k]["items"] = {
                "type": "integer"
                if k.endswith("Ids")
                else "object"
                if k in ("periods", "tiers")
                else "string"
            }
        if k not in required:
            props[k]["nullable"] = True
    return {"type": "object", "properties": props, "required": required}


def validate(path, method, b):
    s = schema_for(path, method)
    for k in s["required"]:
        require(k in b and b[k] is not None, message=f"缺少{k}")

    def walk(value, depth=0):
        require(depth < 8, message="请求对象嵌套过深")
        if isinstance(value, dict):
            require(len(value) <= 60, message="请求字段过多")
            for k, v in value.items():
                if v is None:
                    continue
                if k.endswith("Ids"):
                    require(
                        isinstance(v, list)
                        and len(v) <= 200
                        and all(type(x) is int and x > 0 for x in v),
                        message=f"{k}必须为ID数组",
                    )
                elif k in ARRAYS:
                    require(
                        isinstance(v, list) and len(v) <= 100, message=f"{k}必须为数组且最多100项"
                    )
                elif k.endswith("Id") or k in INTEGERS:
                    require(type(v) is int, message=f"{k}必须为整数")
                elif k in NUMBERS:
                    require(type(v) in (int, float), message=f"{k}必须为数字")
                elif k in BOOLEANS:
                    require(type(v) is bool, message=f"{k}必须为布尔值")
                else:
                    require(
                        isinstance(v, str) and len(v) <= 4000, message=f"{k}必须为文本且最长4000字"
                    )
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(value, list):
            for v in value:
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)

    walk(b)
    if path.endswith("/auth/login") and "/app/" in path:
        key = "smsCode" if b.get("loginMethod") == "SMS_CODE" else "password"
        require(b.get(key), message=f"缺少{key}")
