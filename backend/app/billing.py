"""Decimal billing splits each metered interval at tariff boundaries (Asia/Shanghai)."""

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from .db import now, TZ
from .common import dt, require, money


def minute(s):
    h, m = map(int, s.split(":"))
    require(0 <= h <= 24 and 0 <= m < 60 and (h < 24 or m == 0))
    return h * 60 + m


def validate_periods(periods):
    require(isinstance(periods, list) and 0 < len(periods) <= 48, message="需要完整的分时价格")
    periods = sorted(periods, key=lambda p: minute(p["start_time"]))
    cursor = 0
    for p in periods:
        a, b = minute(p["start_time"]), minute(p["end_time"])
        require(a == cursor and b > a, message="分时价格必须无重叠、无空隙地覆盖00:00~24:00")
        require(
            Decimal(str(p["electricity_price"])) >= 0 and Decimal(str(p["service_price"])) >= 0,
            message="价格不可为负",
        )
        cursor = b
    require(cursor == 1440, message="分时价格必须覆盖全天")
    return periods


def split_energy(start, end, energy, periods):
    start, end = dt(start).astimezone(TZ), dt(end).astimezone(TZ)
    energy = Decimal(str(energy))
    seconds = Decimal(str((end - start).total_seconds()))
    if energy <= 0 or seconds <= 0:
        return []
    result = []
    cursor = start
    while cursor < end:
        day = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
        current = cursor.hour * 60 + cursor.minute
        p = next(p for p in periods if minute(p["start_time"]) <= current < minute(p["end_time"]))
        boundary = min(end, day + timedelta(minutes=minute(p["end_time"])))
        qty = energy * Decimal(str((boundary - cursor).total_seconds())) / seconds
        for kind, key in [("ELECTRICITY", "electricity_price"), ("SERVICE", "service_price")]:
            price = Decimal(str(p[key]))
            result.append(
                {
                    "fee_type": kind,
                    "period_start": cursor.isoformat(),
                    "period_end": boundary.isoformat(),
                    "quantity": str(qty),
                    "unit_price": str(price),
                    "amount": str(qty * price),
                    "description": "电费" if kind == "ELECTRICITY" else "服务费",
                }
            )
        cursor = boundary
    return result


def occupancy_details(end, leave, snapshot):
    if not end:
        return []
    end, leave = dt(end), dt(leave)
    mins = int(
        (Decimal(str(max(0, (leave - end).total_seconds()))) / 60).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    result = []
    total = Decimal(0)
    cap = (
        Decimal(str(snapshot["max_amount"]))
        if snapshot.get("max_amount") is not None
        else Decimal("1e12")
    )
    for t in snapshot["tiers"]:
        a = max(t["start_minute"], snapshot["free_minutes"] + 1)
        b = min(mins, t.get("end_minute") or mins)
        qty = max(0, b - a + 1)
        price = Decimal(str(t["price_per_minute"]))
        amount = min(Decimal(qty) * price, max(0, cap - total))
        if qty and amount:
            result.append(
                {
                    "fee_type": "OCCUPANCY",
                    "period_start": (end + timedelta(minutes=a - 1)).isoformat(),
                    "period_end": min(leave, end + timedelta(minutes=b)).isoformat(),
                    "quantity": str(qty),
                    "unit_price": str(price),
                    "amount": str(amount),
                    "description": "占桩费（不足一分钟按一分钟，受封顶限制）",
                }
            )
            total += amount
    return result


def totals(s, at=None):
    details = list(s["fee_segments"]) + occupancy_details(
        s["charge_end_time"], s["leave_time"] or at or now(), s["occupancy_snapshot"]
    )
    vals = {
        k: money(sum((Decimal(d["amount"]) for d in details if d["fee_type"] == kind), Decimal(0)))
        for k, kind in [
            ("electricity_fee", "ELECTRICITY"),
            ("service_fee", "SERVICE"),
            ("occupancy_fee", "OCCUPANCY"),
        ]
    }
    return {
        **vals,
        "energy_kwh": s["energy_kwh"],
        "estimated_amount": sum(vals.values()),
        "calculated_at": now(),
    }, details


def settle_details(details):
    """Allocate rounding cents by largest remainder so invoice lines match each fee subtotal."""
    result = [dict(d) for d in details]
    for kind in ("ELECTRICITY", "SERVICE", "OCCUPANCY"):
        indices = [i for i, d in enumerate(result) if d["fee_type"] == kind]
        if not indices:
            continue
        raw = {i: Decimal(result[i]["amount"]) for i in indices}
        rounded = {i: raw[i].quantize(Decimal(".01"), rounding=ROUND_DOWN) for i in indices}
        target = money(sum(raw.values(), Decimal(0)))
        cents = int((target - sum(rounded.values(), Decimal(0))) * 100)
        for i in sorted(indices, key=lambda x: raw[x] - rounded[x], reverse=True)[:cents]:
            rounded[i] += Decimal(".01")
        for i in indices:
            result[i]["amount"] = str(rounded[i])
    return result
