from sqlalchemy import or_, update
from datetime import timedelta
from decimal import Decimal
from .common import *
from .billing import totals, split_energy, settle_details

ACTIVE = [
    "STARTING",
    "CHARGING",
    "STOPPING",
    "CHARGE_FINISHED",
    "OCCUPYING",
    "SETTLING",
    "ABNORMAL",
]


def select_plan(db, p, at=None):
    at = at or now()
    plans = rows(
        db,
        m.plan,
        m.plan.c.station_id == p["station_id"],
        m.plan.c.status == "ENABLED",
        m.plan.c.effective_from <= at,
        or_(m.plan.c.effective_to.is_(None), m.plan.c.effective_to > at),
        or_(m.plan.c.pile_id.is_(None), m.plan.c.pile_id == p["id"]),
    )
    require(plans, 41001, "此设备暂无有效价格方案")
    return sorted(
        plans, key=lambda r: (r["pile_id"] is not None, r["effective_from"], r["id"]), reverse=True
    )[0]


def idle_notify(db, p):
    watches = db.execute(
        select(m.watch)
        .where(
            m.watch.c.station_id == p["station_id"],
            m.watch.c.status == "ACTIVE",
            m.watch.c.pile_type.in_([p["pile_type"], "ALL"]),
        )
        .order_by(m.watch.c.id)
        .limit(100)
        .with_for_update(skip_locked=True)
    ).mappings()
    for w in watches:
        notify(
            db,
            w["user_id"],
            "PILE_AVAILABLE",
            "有空闲充电桩了",
            f"{p['pile_no']} 已空闲，可前往站点查看",
            "STATION",
            p["station_id"],
        )
        change(db, m.watch, w["id"], status="NOTIFIED", last_notified_at=now())


def start(db, uid, b):
    get(db, m.user, uid, lock=True)
    require(
        not count(
            db,
            m.session,
            m.session.c.user_id == uid,
            m.session.c.status.in_(ACTIVE),
            m.session.c.leave_time.is_(None),
        ),
        41003,
        "当前已有未结束充电会话",
    )
    v = get(db, m.vehicle, b["vehicleId"], uid, lock=True)
    require(v["status"] == "NORMAL", 40900, "车辆已解绑")
    target = int(b["targetSoc"])
    require(
        target in (80, 90, 100) and target > v["current_soc"],
        message="目标电量需高于当前电量，且为80/90/100",
    )
    p = get(db, m.pile, b["pileId"], lock=True)
    st = get(db, m.station, p["station_id"], lock=True)
    require(st["status"] == "OPEN", 41001, "充电站未营业")
    rid = b.get("reservationId")
    if rid:
        r = get(db, m.reservation, rid, uid, lock=True)
        require(
            r["pile_id"] == p["id"]
            and r["vehicle_id"] == v["id"]
            and r["status"] == "ARRIVED"
            and r["expire_time"] > now(),
            42003,
            "请确认预约到场状态及有效时间",
        )
        require(p["status"] == "RESERVED", 42001, "预约设备状态冲突")
        change(db, m.reservation, r["id"], status="CHARGING")
    else:
        require(p["status"] == "IDLE", 41002, "充电桩不是空闲状态")
    plan = select_plan(db, p)
    periods = rows(db, m.period, m.period.c.plan_id == plan["id"])
    require(periods, 41001, "价格未配置")
    rules = rows(
        db,
        m.occupancy,
        m.occupancy.c.status == "ENABLED",
        or_(m.occupancy.c.station_id == p["station_id"], m.occupancy.c.station_id.is_(None)),
    )
    require(rules, 41001, "占桩费未配置")
    rule = sorted(rules, key=lambda x: (x["station_id"] is not None, x["id"]), reverse=True)[0]
    snapshot = {**rule, "tiers": rows(db, m.tier, m.tier.c.rule_id == rule["id"])}
    # Store snake_case JSON snapshots independently from API casing.
    import json

    safe = lambda x: json.loads(json.dumps(x, default=str))
    s = add(
        db,
        m.session,
        session_no=number("CS"),
        user_id=uid,
        vehicle_id=v["id"],
        station_id=p["station_id"],
        pile_id=p["id"],
        reservation_id=rid,
        price_plan_id=plan["id"],
        occupancy_rule_id=rule["id"],
        start_soc=v["current_soc"],
        target_soc=target,
        current_soc=v["current_soc"],
        start_time=now(),
        current_power_kw=p["power_kw"],
        price_snapshot=safe(periods),
        occupancy_snapshot=safe(snapshot),
        battery_capacity=v["battery_capacity"],
        fee_segments=[],
    )
    change(db, m.pile, p["id"], status="CHARGING")
    return s


def meter(db, s, energy, at, seq, power):
    energy = Decimal(str(energy))
    at = dt(at)
    if s["status"] != "CHARGING" or seq <= s["meter_sequence"]:
        return s
    require(
        at >= (s["telemetry_at"] or s["start_time"]) and at <= now() + timedelta(seconds=5),
        message="设备时间倒退或超出当前时间",
    )
    require(energy >= s["energy_kwh"] and power >= 0, message="累计电量不可倒退")
    cap = s["battery_capacity"] * Decimal(s["target_soc"] - s["start_soc"]) / 100
    previous_at = s["telemetry_at"] or s["start_time"]
    require(energy == s["energy_kwh"] or at > previous_at, message="电量增长必须具有正时间间隔")
    if energy > cap and energy > s["energy_kwh"]:
        ratio = (cap - s["energy_kwh"]) / (energy - s["energy_kwh"])
        at = previous_at + (at - previous_at) * float(max(Decimal(0), ratio))
    energy = min(energy, cap)
    extra = split_energy(
        s["telemetry_at"] or s["start_time"], at, energy - s["energy_kwh"], s["price_snapshot"]
    )
    segments = list(s["fee_segments"])
    # Coalesce equal tariff segments to keep snapshots bounded across many telemetry packets.
    for d in extra:
        prior = next(
            (
                x
                for x in reversed(segments[-4:])
                if x["fee_type"] == d["fee_type"]
                and x["unit_price"] == d["unit_price"]
                and x["period_end"] == d["period_start"]
            ),
            None,
        )
        if prior:
            prior["period_end"] = d["period_end"]
            prior["quantity"] = str(Decimal(prior["quantity"]) + Decimal(d["quantity"]))
            prior["amount"] = str(Decimal(prior["amount"]) + Decimal(d["amount"]))
        else:
            segments.append(d)
    soc = min(s["target_soc"], int(Decimal(s["start_soc"]) + energy / s["battery_capacity"] * 100))
    s = change(
        db,
        m.session,
        s["id"],
        energy_kwh=energy,
        current_soc=soc,
        current_power_kw=power,
        meter_sequence=seq,
        telemetry_at=at,
        fee_segments=segments,
    )
    change(
        db,
        m.vehicle,
        s["vehicle_id"],
        current_soc=soc,
        soc_source="CHARGER_SIMULATOR",
        soc_updated_at=at,
    )
    if energy >= cap:
        return stop(db, s, "TARGET_REACHED", at=at)
    return s


def simulate(db, s, at=None):
    if s["status"] != "CHARGING":
        return s
    at = at or now()
    p = get(db, m.pile, s["pile_id"])
    # Simulation is wall-clock based; no invented accelerated timestamps.
    energy = p["power_kw"] * Decimal(str(max(0, (at - s["start_time"]).total_seconds()))) / 3600
    return meter(db, s, max(s["energy_kwh"], energy), at, s["meter_sequence"] + 1, p["power_kw"])


def stop(db, s, reason="USER_STOP", at=None, abnormal=None):
    if s["status"] != "CHARGING":
        return s
    at = at or now()
    s = change(
        db,
        m.session,
        s["id"],
        status="ABNORMAL" if abnormal else "CHARGE_FINISHED",
        stop_reason=None if abnormal else reason,
        abnormal_reason=abnormal,
        charge_end_time=at,
        end_soc=s["current_soc"],
        current_power_kw=0,
        free_leave_deadline=at + timedelta(minutes=s["occupancy_snapshot"]["free_minutes"]),
    )
    notify(
        db,
        s["user_id"],
        "CHARGING_ABNORMAL" if abnormal else "CHARGING_FINISHED",
        "充电异常停止" if abnormal else "充电已结束",
        abnormal or "请在免费时间内驶离车位，驶离后生成订单。",
        "SESSION",
        s["id"],
    )
    return s


def leave(db, s):
    if s["leave_time"]:
        o = one(db, m.order, m.order.c.session_id == s["id"])
        return {**s, "session_id": s["id"], "order_id": o["id"], "order_no": o["order_no"]}
    require(s["status"] in ("CHARGE_FINISHED", "OCCUPYING", "ABNORMAL"), 40900, "请先停止充电")
    s = change(db, m.session, s["id"], leave_time=now(), status="FINISHED")
    total, details = totals(s)
    o = add(
        db,
        m.order,
        order_no=number("OD"),
        user_id=s["user_id"],
        session_id=s["id"],
        vehicle_id=s["vehicle_id"],
        station_id=s["station_id"],
        pile_id=s["pile_id"],
        start_time=s["start_time"],
        charge_end_time=s["charge_end_time"],
        leave_time=s["leave_time"],
        duration_minutes=int((s["charge_end_time"] - s["start_time"]).total_seconds() / 60),
        energy_kwh=s["energy_kwh"],
        electricity_fee=total["electricity_fee"],
        service_fee=total["service_fee"],
        occupancy_fee=total["occupancy_fee"],
        original_amount=total["estimated_amount"],
        payable_amount=total["estimated_amount"],
        overdue_at=now() + timedelta(hours=int(setting(db, "PAYMENT_OVERDUE_HOURS", 24))),
    )
    for d in settle_details(details):
        add(
            db,
            m.fee,
            order_id=o["id"],
            **{**d, "period_start": dt(d["period_start"]), "period_end": dt(d["period_end"])},
        )
    if s["reservation_id"]:
        change(db, m.reservation, s["reservation_id"], status="COMPLETED")
    p = get(db, m.pile, s["pile_id"], lock=True)
    if p["status"] == "CHARGING":
        p = change(db, m.pile, p["id"], status="IDLE")
        idle_notify(db, p)
    notify(
        db,
        s["user_id"],
        "ORDER_UNPAID",
        "充电订单待支付",
        f"应付 ¥{o['payable_amount']}",
        "ORDER",
        o["id"],
    )
    return {**s, "session_id": s["id"], "order_id": o["id"], "order_no": o["order_no"]}


def session_view(db, s):
    if not s:
        return None
    p = get(db, m.pile, s["pile_id"])
    st = get(db, m.station, s["station_id"])
    cost, _ = totals(s)
    return {
        k: v
        for k, v in {
            **s,
            "session_id": s["id"],
            "station_name": st["station_name"],
            "pile_no": p["pile_no"],
            "pile_type": p["pile_type"],
            "power_kw": p["power_kw"],
            "charging_minutes": int(
                ((s["charge_end_time"] or now()) - s["start_time"]).total_seconds() / 60
            ),
            "current_electricity_fee": cost["electricity_fee"],
            "current_service_fee": cost["service_fee"],
            "current_amount": cost["estimated_amount"],
        }.items()
        if k not in ("price_snapshot", "occupancy_snapshot", "fee_segments", "meter_sequence")
    }
